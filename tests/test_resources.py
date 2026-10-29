"""GPU telemetry must not import inference libraries into the web process."""
import subprocess
import sys
import types

import pytest

from crowbarr import capabilities, resources


def no_nvidia(*args, **kwargs):
    raise FileNotFoundError("nvidia-smi")


def test_intel_device_and_cached_memory_are_reported(monkeypatch):
    monkeypatch.setattr(resources.subprocess, "run", no_nvidia)
    monkeypatch.setattr(capabilities, "runtime_capabilities", lambda block=False: {
        "status": "ready", "xpu": {"available": True, "device_name": "Intel Arc A770",
        "vram_total_mb": 16384, "vram_free_mb": 12000, "memory_sampled_at": 1000,
        "memory_source": "torch.xpu.mem_get_info"}})
    data = resources.snapshot(device="xpu")
    assert data["gpu"] == "Intel Arc A770"
    assert data["gpu_backend"] == "xpu"
    assert data["vram_total_mb"] == 16384
    assert data["vram_free_mb"] == 12000
    assert data["gpu_memory_sampled_at"] == 1000


def test_intel_probe_reports_device_and_global_memory(monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", types.ModuleType("whisper"))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        ones=lambda *args, **kwargs: types.SimpleNamespace(cpu=lambda: None),
        xpu=types.SimpleNamespace(is_available=lambda: True,
            get_device_name=lambda _: "Intel Arc A770",
            get_device_properties=lambda _: types.SimpleNamespace(total_memory=16 * 1024**3),
            mem_get_info=lambda _: (12 * 1024**3, 16 * 1024**3))))
    namespace = {}
    exec(capabilities._PROBE, namespace)
    xpu = namespace["result"]["xpu"]
    assert xpu["available"] is True
    assert xpu["device_name"] == "Intel Arc A770"
    assert xpu["vram_free_mb"] == 12288
    assert xpu["vram_total_mb"] == 16384


def test_intel_probe_memory_failure_does_not_hide_device(monkeypatch):
    def unsupported(*_):
        raise RuntimeError("driver does not support global free memory")

    monkeypatch.setitem(sys.modules, "whisper", types.ModuleType("whisper"))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        ones=lambda *args, **kwargs: types.SimpleNamespace(cpu=lambda: None),
        xpu=types.SimpleNamespace(is_available=lambda: True,
            get_device_name=lambda _: "Intel integrated graphics",
            get_device_properties=lambda _: types.SimpleNamespace(total_memory=8 * 1024**3),
            mem_get_info=unsupported)))
    namespace = {}
    exec(capabilities._PROBE, namespace)
    xpu = namespace["result"]["xpu"]
    assert xpu["available"] is True
    assert xpu["vram_total_mb"] == 8192
    assert xpu["vram_free_mb"] is None


@pytest.mark.parametrize("state,available", [("checking", None), ("ready", False), ("ready", True)])
def test_intel_resources_are_nonblocking_and_report_unknown_honestly(monkeypatch, state, available):
    calls = []

    def report(block):
        calls.append(block)
        return {"status": state, "xpu": {"available": available}}

    monkeypatch.setattr(capabilities, "runtime_capabilities", report)
    data = resources.snapshot(device="xpu")
    assert calls == [False]
    assert data["gpu_status"] == ("checking" if state == "checking" else
                                  "available" if available else "unavailable")
    assert data["vram_free_mb"] is None
    assert bool(data["gpu"]) == (available is True)


def test_selected_cuda_does_not_borrow_intel_memory(monkeypatch):
    monkeypatch.setattr(resources.subprocess, "run", lambda *args, **kwargs:
                        types.SimpleNamespace(stdout="NVIDIA Test, 8000, 16000\n"))
    monkeypatch.setattr(capabilities, "runtime_capabilities", lambda **_:
                        pytest.fail("Intel probe requested for selected CUDA"))
    data = resources.snapshot(device="cuda")
    assert data["gpu"] == "NVIDIA Test"
    assert data["gpu_backend"] == "cuda"
    assert data["vram_free_mb"] == 8000
    assert data["gpu_memory_cached"] is False


def test_cpu_image_missing_gpu_does_not_fail_resource_snapshot(monkeypatch):
    monkeypatch.setenv("CROWBARR_IMAGE_VARIANT", "cpu")
    monkeypatch.setattr(resources.subprocess, "run", no_nvidia)
    monkeypatch.setattr(capabilities, "runtime_capabilities", lambda block=False:
                        {"status": "ready", "xpu": {"available": False}})
    data = resources.snapshot(device="cpu")
    assert data["gpu"] is None
    assert data["vram_total_mb"] is None


def test_snapshot_module_does_not_import_torch():
    result = subprocess.run([sys.executable, "-c",
        "import crowbarr.resources; import sys; assert 'torch' not in sys.modules"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
