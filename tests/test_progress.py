import wave

import pytest

from crowbarr import inference
from crowbarr.config import Settings
from crowbarr.subtitles import Word


def test_sample_progress_accumulates_windows_and_restores_callback(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 16000 * 8)
    events = []

    def notify(current, total):
        events.append((current, total))

    def recognize(*_args):
        recognize.progress(1, 2)
        return [Word(0, 1, "hello", 0.9)], []

    recognize.progress = notify
    monkeypatch.setattr(inference, "transcribe", recognize)
    words, issues = inference.transcribe_windows(audio, [(0, 2), (6, 8)], Settings(), tmp_path)
    assert [w.start for w in words] == [0, 6]
    assert not issues
    assert events == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert recognize.progress is notify


def test_sample_progress_restores_callback_after_decoder_failure(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 16000 * 2)

    def notify(*_args):
        pass

    def recognize(*_args):
        raise RuntimeError("decoder stopped")

    recognize.progress = notify
    monkeypatch.setattr(inference, "transcribe", recognize)
    with pytest.raises(RuntimeError):
        inference.transcribe_windows(audio, [(0, 2)], Settings(), tmp_path)
    assert recognize.progress is notify


@pytest.mark.parametrize('fail', [False, True])
def test_recognition_hardware_is_published_live_and_scoped_to_one_job(tmp_path, monkeypatch, fail):
    import json

    from crowbarr import processor
    from crowbarr.db import Database

    db = Database(tmp_path / 'jobs.db')
    db.enqueue('/media/test.mkv', 'sig', None, 0)
    job = db.claim()
    runtime = {'backend': 'xpu', 'device_name': 'Intel Arc A770', 'device_index': 0, 'compute_type': 'float16'}
    monkeypatch.setattr(inference.transcribe, 'runtime', runtime, raising=False)

    def recognize(*args):
        inference.publish_runtime()
        # Visible to the dashboard before the job finishes.
        active = next(row for row in db.snapshot()['jobs'] if row['state'] == 'processing')
        assert json.loads(active['recognition_runtime']) == runtime
        if fail:
            raise RuntimeError('recognition stopped')
        return {'state': 'unchanged'}

    monkeypatch.setattr(processor, '_process', recognize)
    if fail:
        with pytest.raises(RuntimeError, match='recognition stopped'):
            processor.process(job, Settings(), tmp_path, db)
    else:
        processor.process(job, Settings(), tmp_path, db)
    assert inference.runtime_reporter.get() is None
    inference.publish_runtime()  # No callback leaks into later inference calls.
    db.update(job['id'], state='retry')
    assert db.claim()['recognition_runtime'] is None


def test_new_inputs_and_restored_results_do_not_inherit_another_runs_gpu(tmp_path):
    import json

    from crowbarr.db import Database

    db = Database(tmp_path / 'jobs.db')
    media = '/media/test.mkv'
    job = db.enqueue(media, 'old', None, 0)
    original = {'runtime': {'backend': 'xpu', 'device_name': 'Intel Arc A770'}}
    db.update(job, state='unchanged', report=json.dumps(original), recognition_runtime=json.dumps(original['runtime']))
    db.enqueue(media, 'new', None, 0)
    assert db.get(job)['recognition_runtime'] is None
    db.update(job, recognition_runtime=json.dumps({'backend':'xpu', 'device_name':'Intel UHD Graphics 770'}))
    assert db.restore_results([(media, 'old', None)]) == {media}
    restored = db.get(job)
    assert restored['recognition_runtime'] is None
    assert json.loads(restored['report'])['runtime']['device_name'] == 'Intel Arc A770'
