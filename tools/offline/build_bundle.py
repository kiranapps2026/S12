"""Build an offline bundle on a machine WITH internet access.

    python tools/offline/build_bundle.py                        # for this machine
    python tools/offline/build_bundle.py --target windows --python 3.11

Produces ``offline_bundle/`` (and ``offline_bundle.zip``) containing:
  wheelhouse/   every Python package needed (asyncpg, pytest and their dependencies)
                plus supragents itself, as installable wheel files
  source/       the repository files needed to run the tests and verify_s0_s11.py
  SHA256SUMS    checksums; the installer refuses a bundle that does not match
Copy the zip to the offline machine and run ``python install_offline.py`` inside it.
PostgreSQL itself is not a Python package: install it on the offline machine separately.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ("asyncpg>=0.29", "fastapi>=0.110", "uvicorn>=0.29", "pytest>=8", "httpx>=0.27")
WINDOWS_ONLY = ("colorama",)  # pytest and click need it on Windows; pip cannot infer it cross-platform
SOURCE_ITEMS = ("src", "tests", "pyproject.toml", "verify_s0_s11.py", "README.md",
                "WORK_PACKAGES.md", ".env.example")
TARGETS = {"windows": "win_amd64", "linux": "manylinux2014_x86_64", "current": None}


def main() -> int:
    args = _arguments()
    bundle = Path(args.output).resolve()
    if bundle.exists():
        shutil.rmtree(bundle)
    wheelhouse = bundle / "wheelhouse"
    _download(wheelhouse, args.target, args.python)
    _build_own_wheel(wheelhouse)
    _copy_source(bundle / "source")
    shutil.copy2(Path(__file__).with_name("install_offline.py"), bundle / "install_offline.py")
    _write_checksums(bundle)
    archive = shutil.make_archive(str(bundle), "zip", root_dir=bundle)
    print(f"bundle ready: {archive}")
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=sorted(TARGETS), default="current")
    parser.add_argument("--python", default=f"{sys.version_info.major}.{sys.version_info.minor}",
                        help="Python version on the offline machine, e.g. 3.11 or 3.12")
    parser.add_argument("--output", default=str(ROOT / "offline_bundle"))
    return parser.parse_args()


def _download(wheelhouse: Path, target: str, python: str) -> None:
    command = [sys.executable, "-m", "pip", "download", "-d", str(wheelhouse), *REQUIREMENTS]
    platform = TARGETS[target]
    if platform is not None:
        command += ["--platform", platform, "--python-version", python, "--only-binary=:all:"]
    if target == "windows" or (target == "current" and sys.platform == "win32"):
        command += list(WINDOWS_ONLY)
    _run(command)


def _build_own_wheel(wheelhouse: Path) -> None:
    """Build the supragents wheel, leaving no build/ or egg-info folders in the checkout."""
    _run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(wheelhouse)])
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    for leftover in (ROOT / "src").glob("*.egg-info"):
        shutil.rmtree(leftover)


def _copy_source(destination: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.egg-info")
    for item in SOURCE_ITEMS:
        path = ROOT / item
        if path.is_dir():
            shutil.copytree(path, destination / item, ignore=ignore)
        elif path.exists():
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination / item)


def _write_checksums(bundle: Path) -> None:
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(bundle).as_posix()}"
             for p in sorted(bundle.rglob("*")) if p.is_file()]
    (bundle / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True)


if __name__ == "__main__":
    sys.exit(main())
