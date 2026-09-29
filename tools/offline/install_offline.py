"""Install SuprAgents on a machine WITHOUT internet access, from an offline bundle.

Run inside the unzipped bundle folder:
    python install_offline.py                    # verify, create .venv, install, run the checks
    python install_offline.py --skip-checks      # install only
    python install_offline.py --migrate          # also create the tables (needs DATABASE_URL)

Nothing is downloaded: pip installs only from ./wheelhouse (--no-index).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
VENV = BUNDLE / ".venv"


def main() -> int:
    args = _arguments()
    _verify_checksums()
    python = _create_venv()
    _run([str(python), "-m", "pip", "install", "--no-index", "--find-links", str(BUNDLE / "wheelhouse"),
          "supragents[test]"])
    if args.migrate:
        _run([str(python), "-m", "supragents", "migrate"])
    if not args.skip_checks:
        _run([str(python), "verify_s0_s11.py"], cwd=BUNDLE / "source")
    activate = r".venv\Scripts\activate" if os.name == "nt" else "source .venv/bin/activate"
    print(f"\nInstalled. Activate with: {activate}")
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-checks", action="store_true", help="do not run verify_s0_s11.py")
    parser.add_argument("--migrate", action="store_true", help="run database migrations (DATABASE_URL)")
    return parser.parse_args()


def _verify_checksums() -> None:
    for line in (BUNDLE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        if hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() != expected:
            sys.exit(f"bundle is damaged: checksum mismatch for {name}")
    print("bundle checksums OK")


def _create_venv() -> Path:
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11 or newer is required.")
    if not VENV.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, cwd=cwd)


if __name__ == "__main__":
    sys.exit(main())
