"""Verify installed Intel packages and the speech adapter on a CPU CI runner.

The runner has no Intel GPU. This checks real recognition, VAD, timestamps and
confidence through the Intel adapter; XPU execution must be checked on the host.
"""
import faulthandler
import tempfile
from pathlib import Path
from unittest.mock import patch

from packaging_smoke import check_imports, smoke


def main():
    faulthandler.dump_traceback_later(90, repeat=True)
    print("Importing the installed Intel inference runtime", flush=True)
    import torch
    import whisper

    from crowbarr.capabilities import _run_probe
    from crowbarr.config import Settings
    from crowbarr.intel_inference import _recognize

    check_imports()
    print("Checking complete runtime detection in a fresh subprocess", flush=True)
    capabilities = _run_probe()
    for name in ("cpu", "refinement"):
        assert capabilities[name]["available"], capabilities[name]["reason"]
    assert "+xpu" in torch.__version__, f"Expected XPU Torch, found {torch.__version__}"
    torch.set_num_threads(2)
    fixture = Path(__file__).parent / "fixtures" / "speech.flac"
    with tempfile.TemporaryDirectory(prefix="crowbarr-intel-") as directory:
        cache = Path(directory)
        print("Loading the tiny English checkpoint on CPU", flush=True)
        model = whisper.load_model("tiny.en", device="cpu", download_root=str(cache))
        settings = Settings(model="tiny.en", device="xpu", compute_type="float32", cpu_threads=2)
        # Test the installed adapter against real audio without pretending this
        # hosted runner has a GPU. Production uses the XPU model loader here.
        with patch("crowbarr.intel_inference._load_model", return_value=model):
            print("Running VAD and word-timestamp recognition on the speech fixture", flush=True)
            words, issues = _recognize(fixture, settings, cache)
        assert len(words) >= 20, f"Too few recognized words: {len(words)}"
        assert all(word.end > word.start and 0 <= word.probability <= 1 for word in words)
        assert any(word.probability > 0.8 for word in words)
        print(f"Intel adapter CPU fixture passed: {len(words)} words; warnings: {issues}", flush=True)
    print("Checking spawned application processing", flush=True)
    smoke(check_inference=False)
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
