"""Policy correctness and bounded queue work, independent of host timing."""
import json
import sqlite3
import time
from contextlib import contextmanager

import pytest

from crowbarr import catalog, policy
from crowbarr.db import Database, StaleJob


def managed(db, count=4):
    records = [dict(file_id=i + 1, item_id=1, path=f"/tv/Show S01E{i + 1:02}.mkv",
                    remote_path=f"/tv/Show S01E{i + 1:02}.mkv", title="Show",
                    season=1, episodes=[i + 1], audio_languages=["hi"])
               for i in range(count)]
    db.replace_catalog("sonarr", records)
    for record in records:
        db.enqueue(record["path"], "revision", None, 0)
    return records


@pytest.mark.parametrize("rules", [[], [("title", "sonarr:1", "include")],
    [("title", "sonarr:1", "skip"), ("season", "sonarr:1:1", "include")],
    [("season", "sonarr:1:1", "include"), ("file", "sonarr:1:episode:1:1", "skip")]])
def test_single_file_policy_matches_full_catalog(tmp_path, rules):
    db = Database(tmp_path / "queue.db")
    records = managed(db)
    db.enqueue("/old/Unmanaged S01E01.mkv", "old", None, 0)
    with db.connect() as connection:
        connection.executemany("INSERT INTO library_rules VALUES (?,?,?)", rules)
        connection.execute("UPDATE library_metadata SET metadata=? WHERE path=?",
                           (json.dumps({"season": 1, "episodes": [1, 2],
                                        "audio_languages": ["hi"]}), records[0]["path"]))
        for languages in (["hi"], ["hi", "en"], ["und"], []):
            connection.execute("INSERT OR REPLACE INTO audio_metadata VALUES (?,?,?)",
                               (records[1]["path"], "revision", json.dumps(languages)))
            expected = [(r["path"], catalog.decision(r, *catalog.preferences(connection)))
                        for r in catalog.rows(connection)]
            for path, decision in expected:
                assert db.check_current_policy(connection, path) == decision


def test_idle_claim_does_not_load_full_catalog(tmp_path, monkeypatch):
    db = Database(tmp_path / "queue.db")
    managed(db)
    with db.connect() as connection:
        connection.execute("UPDATE jobs SET state='completed'")
    monkeypatch.setattr(catalog, "rows", lambda *_: pytest.fail("full catalog loaded by idle claim"))
    assert db.claim() is None


def test_four_claimers_preserve_single_worker(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db = Database(tmp_path / "queue.db")
    for i in range(4):
        db.enqueue(f"/tv/{i}.mkv", "sig", None, time.time() - 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: db.claim(), range(4)))
    assert sum(job is not None for job in jobs) == 1


def drain(db):
    for _ in range(1000):
        if db.refresh_policy_batch() == 0:
            return
    pytest.fail("Projection did not converge")


def legacy_database(path):
    db = Database(path)
    managed(db, 2)
    with db.connect() as c:
        c.execute("UPDATE jobs SET state='review',error='keep me',attempts=2 WHERE id=1")
        for row in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'policy_%'"):
            c.execute(f'DROP TRIGGER "{row[0]}"')
        for table in ("policy_dirty", "policy_inputs", "policy_scan"):
            c.execute(f"DROP TABLE {table}")
        for column in ("policy_revision", "policy_input_revision"):
            c.execute(f"ALTER TABLE jobs DROP COLUMN {column}")
        c.execute("DELETE FROM meta WHERE key IN ('policy_revision','policy_projection_v1')")
        c.execute("DROP INDEX managed_item")
    return db


def test_legacy_migration_is_lazy_idempotent_and_preserves_data(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy_database(path)
    monkeypatch.setattr(policy, "record", lambda *_: pytest.fail("eager policy backfill during open"))
    for _ in range(2):
        db = Database(path)
        job = db.get(1)
        assert (job["state"], job["error"], job["attempts"]) == ("review", "keep me", 2)
        with db.connect() as c:
            assert c.execute("SELECT pending FROM policy_scan").fetchone()[0] == 1
            assert c.execute("SELECT COUNT(*) FROM managed_media").fetchone()[0] == 2


def test_policy_migration_failure_rolls_back_all_new_schema(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy_database(path)
    original = policy.global_sql
    monkeypatch.setattr(policy, "global_sql", lambda: (_ for _ in ()).throw(RuntimeError("migration fault")))
    with pytest.raises(RuntimeError, match="migration fault"):
        Database(path)
    with sqlite3.connect(path) as c:
        assert "policy_revision" not in {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'policy_%'").fetchone()
        assert c.execute("SELECT error FROM jobs WHERE id=1").fetchone()[0] == "keep me"
    monkeypatch.setattr(policy, "global_sql", original)
    assert Database(path).get(1)["policy_revision"] == -1


def test_metadata_and_rule_mutations_advance_fences_and_coalesce(tmp_path):
    db = Database(tmp_path / "queue.db")
    path = managed(db, 1)[0]["path"]
    drain(db)
    with db.connect() as c:
        before = policy.revision(c)
        c.execute("INSERT INTO library_rules VALUES ('title','sonarr:1','include')")
        assert policy.revision(c) > before
        c.execute("UPDATE library_metadata SET metadata='{}' WHERE path=?", (path,))
        first = c.execute("SELECT revision FROM policy_dirty WHERE path=?", (path,)).fetchone()[0]
        c.execute("INSERT INTO audio_metadata VALUES (?,?,?)", (path, "v", '["en"]'))
        assert c.execute("SELECT COUNT(*) FROM policy_dirty").fetchone()[0] == 1
        assert c.execute("SELECT revision FROM policy_dirty WHERE path=?", (path,)).fetchone()[0] > first
    drain(db)
    assert db.get(1)["state"] == "queued"


@pytest.mark.parametrize("change", ["rule", "metadata", "audio", "identity"])
def test_projection_cannot_apply_a_stale_snapshot(tmp_path, monkeypatch, change):
    db = Database(tmp_path / "queue.db")
    path = managed(db, 1)[0]["path"]
    with db.connect() as c:
        c.execute("UPDATE library_metadata SET metadata=? WHERE path=?",
                  ('{"audio_languages":["en"]}', path))
        c.execute("INSERT INTO library_rules VALUES ('title','sonarr:2','skip')")
    drain(db)
    db.mark_policy_dirty([path])
    decide = policy.decide
    changed = False

    def race(connection, item):
        nonlocal changed
        result = decide(connection, item)
        if not changed:
            changed = True
            with db.connect() as writer:
                if change == "rule":
                    writer.execute("INSERT INTO library_rules VALUES ('title','sonarr:1','skip')")
                elif change == "identity":
                    writer.execute("UPDATE managed_media SET item_id=2 WHERE path=?", (path,))
                else:
                    if change == "metadata":
                        writer.execute("UPDATE library_metadata SET metadata=? WHERE path=?",
                                       ('{"audio_languages":["ja"]}', path))
                    else:
                        writer.execute("INSERT INTO audio_metadata VALUES (?,?,?)", (path, "v", '["ja"]'))
        return result

    monkeypatch.setattr(policy, "decide", race)
    db.refresh_policy_batch()
    assert db.get(1)["state"] == "queued"  # The stale batch did not apply an outdated skip/allow.
    drain(db)
    assert db.get(1)["state"] == "skipped"


def test_global_cursor_batches_cover_folder_only_and_unmanaged_jobs(tmp_path, monkeypatch):
    db = Database(tmp_path / "queue.db")
    managed(db, 205)
    extra = db.enqueue("/old/Other S01E01.mkv", "v", None, 0)
    with db.connect() as c:
        c.execute("INSERT INTO library_rules VALUES ('title','sonarr:1','include')")
    seen = []
    project = policy.project

    def count(*args, **kwargs):
        seen.append(args[1]["path"])
        return project(*args, **kwargs)

    monkeypatch.setattr(policy, "project", count)
    for _ in range(20):
        start = len(seen)
        remaining = db.refresh_policy_batch(limit=50)
        assert len(seen) - start <= 50
        if not remaining:
            break
    else:
        pytest.fail("global cursor failed to finish")
    assert len(set(seen)) == 206
    assert db.get(extra)["policy_revision"] >= 0
    assert db.get(1)["state"] == "queued"
    db.mark_policy_dirty()
    Database(db.path)  # Does not reset an existing cursor.
    drain(db)


@pytest.mark.parametrize("size", [3000, 15000])
def test_claim_and_single_file_work_do_not_scale_with_catalog(tmp_path, monkeypatch, size):
    db = Database(tmp_path / "queue.db")
    records = [dict(file_id=i, item_id=i, path=f"/tv/{i}.mkv", remote_path=f"/tv/{i}.mkv",
                    title=f"Show {i}", audio_languages=["en"]) for i in range(size)]
    db.replace_catalog("sonarr", records)
    for r in records[-500:]:
        db.enqueue(r["path"], "v", None, 0)
    statements, objects = [], []
    connect, record = db.connect, policy.record

    @contextmanager
    def traced():
        with connect() as c:
            c.set_trace_callback(statements.append)
            yield c

    def counted(c, path):
        objects.append(path)
        return record(c, path)

    monkeypatch.setattr(db, "connect", traced)
    monkeypatch.setattr(policy, "record", counted)
    monkeypatch.setattr(catalog, "rows", lambda *_: pytest.fail("full catalog loader"))
    assert db.claim(["sonarr"])
    assert len(objects) == 1
    assert len(statements) < 25
    claim_statements = len(statements)
    statements.clear()
    objects.clear()
    assert db.claim(["sonarr"]) is None
    assert objects == []
    assert len(statements) < 5
    idle_statements = len(statements)
    statements.clear()
    db.refresh_library_policy(paths=[records[-1]["path"]])
    assert len(objects) == 1
    assert len(statements) < 25
    print(f"catalog={size}: claim={claim_statements} SQL/1 object; idle={idle_statements} SQL/0 objects; "
          f"single-file={len(statements)} SQL/1 object; full_loads=0")


def test_fresh_policy_check_refuses_unprojected_skip_on_publication(tmp_path, monkeypatch):
    from crowbarr import processor
    from crowbarr.config import Settings

    db = Database(tmp_path / "queue.db")
    job_id = db.enqueue(str(tmp_path / "movie.mkv"), "v", None, 0)
    job = db.claim()
    with db.connect() as c:
        c.execute("INSERT INTO library_rules VALUES ('file',?,'skip')", (job["media"],))
    assert db.get(job_id)["library_blocked"] == ""  # Deliberately stale projection.
    monkeypatch.setattr(processor, "current", lambda *_: True)
    with pytest.raises(StaleJob):
        processor.publish_candidate(job, Settings(), tmp_path, db, "text", {"output_sha256": "bad"})
    assert not (tmp_path / "movie.crowbarr.en.srt").exists()


@pytest.mark.parametrize("change", ["skip", "generation"])
def test_publication_rechecks_after_journaling(tmp_path, monkeypatch, change):
    from crowbarr import processor
    from crowbarr.config import Settings

    db = Database(tmp_path / "queue.db")
    db.enqueue(str(tmp_path / "movie.mkv"), "v", None, 0)
    job = db.claim()
    monkeypatch.setattr(processor, "current", lambda *_: True)
    update = db.update

    def after_journal(*args, **kwargs):
        result = update(*args, **kwargs)
        if kwargs.get("stage") == "Publishing subtitles":
            if change == "skip":
                with db.connect() as c:
                    c.execute("INSERT INTO library_rules VALUES ('file',?,'skip')", (job["media"],))
            else:
                db.enqueue(job["media"], "replacement", None, 0)
        return result

    monkeypatch.setattr(db, "update", after_journal)
    with pytest.raises(StaleJob):
        processor.publish_candidate(job, Settings(), tmp_path, db, "text", {"output_sha256": "bad"})
    assert not (tmp_path / "movie.crowbarr.en.srt").exists()


def test_policy_maintenance_runs_while_paused(tmp_path, monkeypatch):
    from crowbarr import service
    from crowbarr.config import ConfigStore

    store = ConfigStore(tmp_path / "config")
    settings = store.get()
    settings.paused = True
    store.save(settings)
    db = Database(store.directory / "crowbarr.db")
    managed(db, 2)
    assert db.get(1)["state"] == "skipped"
    with db.connect() as c:
        c.execute("INSERT INTO library_rules VALUES ('title','sonarr:1','include')")
    daemon = service.Service(store, db)
    ticks = iter([False, True])
    monkeypatch.setattr(daemon.stop_event, "wait", lambda *_: next(ticks))
    monkeypatch.setattr(service, "resource_snapshot", lambda **_: {"ram_available_mb": 4096, "cpu_load": 0})
    daemon.worker()
    assert db.get(1)["state"] == "queued"
    assert db.get(1)["attempts"] == 0


@pytest.mark.parametrize("limit", [0, 201, True, 1.5])
def test_projection_rejects_unbounded_batch_sizes(tmp_path, limit):
    db = Database(tmp_path / "queue.db")
    with pytest.raises(ValueError):
        db.refresh_policy_batch(limit=limit)


def test_file_api_operations_never_load_full_catalog(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from crowbarr.app import create_app

    app = create_app(tmp_path / "config", background=False)
    media = tmp_path / "Show S01E01.mkv"
    media.write_bytes(b"media")
    record = dict(file_id=1, item_id=1, path=str(media), remote_path=str(media), title="Show",
                  season=1, episodes=[1])
    app.state.db.replace_catalog("sonarr", [record])
    job_id = app.state.db.enqueue(str(media), "v", None, 0)
    monkeypatch.setattr(catalog, "rows", lambda *_: pytest.fail("full catalog loader in file API"))
    with TestClient(app, headers={"X-Api-Key": app.state.store.token}) as client:
        assert client.put("/api/library/preferences", json={
            "scope": "file", "target": str(media), "decision": "skip"}).status_code == 200
        assert client.post("/api/process", json={"media": str(media)}).status_code == 409
        assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


@pytest.mark.parametrize("target", ["sonarr:1:01", "sonarr:1:99", "sonarr:" + "9" * 100])
def test_invalid_preference_targets_are_rejected(tmp_path, target):
    db = Database(tmp_path / "queue.db")
    managed(db, 1)
    with db.connect() as c, pytest.raises(LookupError):
        policy.rule_targets(c, "season" if target.count(":") == 2 else "title", target)


def test_manual_approval_cannot_bypass_unprojected_skip(tmp_path, monkeypatch):
    import hashlib

    from fastapi.testclient import TestClient

    from crowbarr import media as media_module
    from crowbarr import processor
    from crowbarr.app import create_app

    app = create_app(tmp_path / "config", background=False)
    db = app.state.db
    media = str(tmp_path / "movie.mkv")
    job_id = db.enqueue(media, "a" * 64, None, 0)
    rendered = "1\n00:00:01,000 --> 00:00:03,000\nHello there\n"
    candidate = processor.new_review_candidate_path(app.state.store.directory, db.get(job_id))
    candidate.parent.mkdir(parents=True)
    candidate.write_text(rendered)
    db.update(job_id, state="review", report=json.dumps({
        "candidate": str(candidate), "output_sha256": hashlib.sha256(rendered.encode()).hexdigest()}))
    with db.connect() as c:
        c.execute("INSERT INTO library_rules VALUES ('file',?,'skip')", (media,))
    monkeypatch.setattr(processor, "current", lambda *_: True)
    monkeypatch.setattr(media_module, "probe", lambda *_: {"format": {"duration": "100"}})
    with TestClient(app, headers={"X-Api-Key": app.state.store.token}) as client:
        assert client.post(f"/api/jobs/{job_id}/approve").status_code == 409
    assert not (tmp_path / "movie.crowbarr.en.srt").exists()


def test_claim_caps_revalidation_at_200_candidates(tmp_path, monkeypatch):
    db = Database(tmp_path / "queue.db")
    records = managed(db, 205)
    with db.connect() as c:
        c.execute("UPDATE jobs SET state='queued',library_blocked=''")
        c.execute("INSERT INTO audio_metadata VALUES (?,?,?)", (records[-1]["path"], "v", '["en"]'))
    seen = []
    original = policy.record

    def count(c, path):
        seen.append(path)
        return original(c, path)

    monkeypatch.setattr(policy, "record", count)
    assert db.claim() is None
    assert len(seen) == 200
    seen.clear()
    assert db.claim()["media"] == records[-1]["path"]
    assert len(seen) == 5


def test_manual_approval_completion_is_generation_fenced(tmp_path, monkeypatch):
    import hashlib

    from fastapi.testclient import TestClient

    from crowbarr import media as media_module
    from crowbarr import processor
    from crowbarr.app import create_app

    app = create_app(tmp_path / "config", background=False)
    db = app.state.db
    media = str(tmp_path / "movie.mkv")
    job_id = db.enqueue(media, "a" * 64, None, 0)
    rendered = "1\n00:00:01,000 --> 00:00:03,000\nHello there\n"
    candidate = processor.new_review_candidate_path(app.state.store.directory, db.get(job_id))
    candidate.parent.mkdir(parents=True)
    candidate.write_text(rendered)
    db.update(job_id, state="review", report=json.dumps({
        "candidate": str(candidate), "output_sha256": hashlib.sha256(rendered.encode()).hexdigest()}))

    def replace_request(*_):
        db.enqueue(media, "new signature", None, 0)
        return {"state": "completed"}

    monkeypatch.setattr(processor, "publish_candidate", replace_request)
    monkeypatch.setattr(media_module, "probe", lambda *_: {"format": {"duration": "100"}})
    with TestClient(app, headers={"X-Api-Key": app.state.store.token}) as client:
        assert client.post(f"/api/jobs/{job_id}/approve").status_code == 409
    assert db.get(job_id)["state"] == "queued"
    assert db.get(job_id)["signature"] == "new signature"
