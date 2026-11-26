"""Regenerate Linux/Python 3.12 locks with uv 0.12.11 after reviewing dependency changes.

Each variant is resolved in full, then split: the image lock keeps what the runtime needs,
and the packages that exist only for WhisperX refinement go to crowbarr/refinement.lock,
which Crowbarr installs on request.
Intel keeps its full lock because XPU Torch is required for recognition itself.
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from split_locks import split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--variant", choices=("cpu", "cuda", "intel"), action="append")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    root = directory.parents[1]
    addons = {}
    with tempfile.TemporaryDirectory() as wheels:
        subprocess.run(["python3", str(directory / "build_alignment.py"), "--output", wheels], check=True)
        variants = args.variant or ("cpu", "cuda", "intel")
        if "intel" in variants:
            subprocess.run([
                "python3", str(directory / "build_reference_whisper.py"), "--output", wheels
            ], check=True)
        for variant in variants:
            target = directory / f"{variant}.lock"
            subprocess.run([
                args.uv, "pip", "compile", str(directory / f"{variant}.in"),
                "--python-version", "3.12", "--python-platform", "x86_64-manylinux_2_28",
                "--generate-hashes", "--find-links", wheels, "--no-build",
                "--output-file", str(target), "--emit-index-url", "--emit-index-annotation",
                "--index-url", "https://pypi.org/simple", "--quiet",
                "--custom-compile-command", "python3 packaging/inference/compile_locks.py",
            ], cwd=root, check=True)
            text = target.read_text().replace(
                f"# from file://{wheels}", "# from checksum-verified wheels built by packaging/inference"
            ).replace(str(root) + "/", "")
            if variant == "intel":
                # Recognition itself requires XPU Torch; refinement is bundled too.
                target.write_text(text)
            else:
                core, addons[variant] = split(text)
                target.write_text(core)
    if len(set(addons.values())) > 1:
        raise ValueError("The CPU and CUDA locks resolve different refinement packages")
    if addons:
        (root / "crowbarr" / "refinement.lock").write_text(next(iter(addons.values())))


if __name__ == "__main__":
    main()
