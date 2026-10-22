"""Package verified, unmodified Whisper sources without the CUDA Triton dependency.

XPU Torch supplies its own Triton distribution. Installing CUDA Triton alongside it
overwrites that distribution's modules. Whisper uses CUDA Triton only for CUDA
timestamp kernels; XPU uses the upstream Torch/Numba timestamp implementations.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import tarfile
import urllib.request
import zipfile
from pathlib import Path

UPSTREAM_URL = (
    "https://files.pythonhosted.org/packages/35/8e/"
    "d36f8880bcf18ec026a55807d02fe4c7357da9f25aebd92f85178000c0dc/"
    "openai_whisper-20250625.tar.gz"
)
UPSTREAM_SHA256 = "37a91a3921809d9f44748ffc73c0a55c9f366c85a3ef5c2ae0cc09540432eb96"
VERSION = "20250625+crowbarr.1"
FILENAME = f"openai_whisper-{VERSION}-py3-none-any.whl"
DEPENDENCIES = ("more-itertools", "numba", "numpy", "tiktoken", "torch~=2.8.0", "tqdm")


def build(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA256:
        raise ValueError("Upstream Whisper checksum mismatch")
    info = f"openai_whisper-{VERSION}.dist-info"
    files = {}
    with tarfile.open(fileobj=io.BytesIO(source), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[-1]
            if name.startswith("whisper/") or name == "LICENSE":
                target = f"{info}/licenses/LICENSE" if name == "LICENSE" else name
                files[target] = archive.extractfile(member).read()
    if "whisper/__init__.py" not in files or f"{info}/licenses/LICENSE" not in files:
        raise ValueError("Whisper sources or license missing")
    files[f"{info}/METADATA"] = (
        f"Metadata-Version: 2.4\nName: openai-whisper\nVersion: {VERSION}\n"
        "Summary: Reference Whisper, packaged for Crowbarr XPU\n"
        "Requires-Python: >=3.8\nLicense-Expression: MIT\nLicense-File: licenses/LICENSE\n"
        + "".join(f"Requires-Dist: {dep}\n" for dep in DEPENDENCIES)
        + "\nUnmodified upstream modules and assets; CUDA Triton dependency omitted.\n"
    ).encode()
    files[f"{info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: crowbarr-reference-whisper\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files[f"{info}/PROVENANCE.md"] = (
        f"Source: {UPSTREAM_URL}\nSHA256: {UPSTREAM_SHA256}\n\n"
        "All whisper modules and assets are byte-for-byte upstream copies.\n"
        "Dependency metadata omits CUDA Triton to avoid overwriting XPU Triton.\n"
        "Crowbarr adapts sparse alignment buffers and DTW device transfers at runtime.\n"
    ).encode()
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, content in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={digest}", len(content)))
    writer.writerow((f"{info}/RECORD", "", ""))
    files[f"{info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as wheel:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            wheel.writestr(entry, content)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with urllib.request.urlopen(UPSTREAM_URL, timeout=60) as response:
        source = response.read()
    result = build(source)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / FILENAME).write_bytes(result)
    print(f"{FILENAME} sha256:{hashlib.sha256(result).hexdigest()}")


if __name__ == "__main__":
    main()
