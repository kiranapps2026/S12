#!/usr/bin/env python3
"""
OWNER CERTIFIER for the S12–S15 milestones (1SuperAgents).

Owned by the project owner. The coding agent must NOT modify this file. Its SHA-256 is recorded in
docs/gates/owner_certify_s12.sha256 and checked by tools/owner_verify_s12.ps1. Certification of a milestone =
this script exits 0 for it.

Usage (repository root):
    python tools/owner_certify_s12.py --milestone M03        # certify M0..M03 (every earlier milestone again)
    python tools/owner_certify_s12.py                        # the current milestone from docs/gates/s12_milestones.json
    python tools/owner_certify_s12.py --milestone M03 --fast # skip sabotage and the 5x concurrency repeats
    python tools/owner_certify_s12.py --selftest             # prove every check can fail
    python tools/owner_certify_s12.py --pin                  # OWNER ONLY: write docs/gates/s12_pins.sha256
    python tools/owner_certify_s12.py --progress             # also regenerate docs/gates/S12_PROGRESS.md

Checks (plan v3 §4 "every milestone's exit also requires", §5):
  S12-PIN   pinned files (tests_golden/**, this certifier's companions, S12_AUTOPILOT.md) equal docs/gates/s12_pins.sha256
  S12-S011  tools/owner_certify.py (S0–S11) is 19/19
  S12-FRZ   frozen S0–S11 source (src/ at the tag minus the prototype list, CONF-011) is byte-identical to the tag
  S12-DOC   tools/doc_consistency.py exits 0
  S12-REC   no open CONF and no open/ruled STOP for any milestone up to the target (S12_RECORDS.md, S12_STOPS.md)
  G-Mxx     the golden file of every milestone up to the target: 0 failed, 0 error, 0 skipped, 0 xfail
  C-Mxx     milestones with concurrency tests: the golden file passes 5 consecutive runs
  X-Mxx     every sabotage patch of the target milestone makes >=1 case FAIL and none ERROR

Results are read from pytest's JUnit XML, never from its console text. TEST_DATABASE_URL comes from the environment
or the repository .env (never printed); its database name must end in _test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / "docs" / "gates"
GOLDEN = ROOT / "tests_golden"
PIN_FILE = GATES / "s12_pins.sha256"
MILESTONES = GATES / "s12_milestones.json"
TAG = "s0-s11-certified"

ORDER = ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M8a", "M9", "M10", "M11", "M12", "M13", "M14",
         "M15", "M16", "M17", "M18", "M19", "M20", "M21"]
CONCURRENCY = {"M2", "M5", "M7", "M8a", "M9", "M20"}      # plan §4: concurrency golden tests pass 5 consecutive runs
REPEATS = 5
PINNED_GLOBS = ("tests_golden/**/*.py", "tests_golden/**/*.sql", "tests_golden/README.md",
                "tools/owner_verify_s12.ps1", "tools/owner_pin_s12.ps1", "docs/gates/S12_AUTOPILOT.md",
                "tools/doc_consistency.py", "tools/s12_tracker.py")


# --- helpers ---------------------------------------------------------------------------------------------------

def norm(mid: str) -> str:
    m = re.fullmatch(r"[Mm]0*(\d+)(a?)", mid.strip())
    if not m:
        raise SystemExit(f"bad milestone id {mid!r}")
    return f"M{int(m.group(1))}{m.group(2)}"


def file_id(mid: str) -> str:
    n = re.fullmatch(r"M(\d+)(a?)", mid)
    return f"M{int(n.group(1)):02d}{n.group(2)}"


def golden_file(root: Path, mid: str) -> Path | None:
    found = sorted((root / "tests_golden" / "s12").glob(f"{file_id(mid)}_*.py"))
    return found[0] if found else None


def sabotage_files(root: Path, mid: str) -> list[Path]:
    prefix = file_id(mid) + "_"
    return sorted(p for p in (root / "tests_golden" / "sabotage").glob(prefix + "*") if p.suffix in (".py", ".sql"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def pinned_paths(root: Path) -> list[str]:
    out = set()
    for pattern in PINNED_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and "__pycache__" not in p.parts:
                out.add(p.relative_to(root).as_posix())
    return sorted(out)


def test_database_url(root: Path) -> str | None:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    env = root / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            key, _, value = line.strip().removeprefix("export ").partition("=")
            if key.strip() == "TEST_DATABASE_URL" and value.strip():
                return value.strip().strip("\"'")
    return None


def junit_counts(xml_path: Path) -> dict:
    """tests / failures / errors / skipped (xfail is reported as skipped) summed over every testsuite."""
    tree = ET.parse(xml_path)
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    suites = [tree.getroot()] if tree.getroot().tag == "testsuite" else tree.getroot().iter("testsuite")
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.get(key, 0))
    return counts


def clean(counts: dict) -> bool:
    return counts["tests"] > 0 and counts["failures"] == counts["errors"] == counts["skipped"] == 0


def run_pytest(root: Path, target: Path, sabotage: Path | None = None) -> dict:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)])}
    env.pop("GOLDEN_SABOTAGE", None)
    if sabotage is not None:
        env["GOLDEN_SABOTAGE"] = str(sabotage)
    url = test_database_url(root)
    if url:
        env["TEST_DATABASE_URL"] = url
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        subprocess.run([sys.executable, "-m", "pytest", str(target), "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                        f"--junitxml={xml}"], cwd=root, env=env, capture_output=True, text=True, timeout=1800)
        if not xml.exists():
            return {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
        return junit_counts(xml)


def records_open(root: Path, upto: list[str]) -> list[str]:
    out = []
    row = re.compile(r"^\|\s*((?:CONF|STOP)-\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|")
    for name, blocking in (("S12_RECORDS.md", {"open"}), ("S12_STOPS.md", {"open", "ruled"})):
        path = root / "docs" / "gates" / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = row.match(line)
            if m:
                mid = re.search(r"M\d+a?", m.group(2))
                if mid and mid.group(0) in upto and m.group(3).strip().lower() in blocking:
                    out.append(f"{m.group(1)} ({mid.group(0)}, {m.group(3).strip()})")
    return out


def git(root: Path, *args: str) -> tuple[int, str]:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return out.returncode, out.stdout


# --- checks: each returns (ok, detail lines) -------------------------------------------------------------------

def chk_pins(root: Path) -> tuple[bool, list[str]]:
    pin = root / "docs" / "gates" / "s12_pins.sha256"
    if not pin.exists():
        return False, ["docs/gates/s12_pins.sha256 missing: owner runs tools/owner_pin_s12.ps1"]
    expected = {}
    for line in pin.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, rel = line.strip().partition("  ")
            expected[rel] = digest
    problems = []
    for rel in sorted(set(expected) | set(pinned_paths(root))):
        path = root / rel
        if rel not in expected:
            problems.append(f"{rel}: not pinned (new file in a pinned area)")
        elif not path.exists():
            problems.append(f"{rel}: pinned but missing")
        elif sha256(path) != expected[rel]:
            problems.append(f"{rel}: changed (expected {expected[rel][:12]}…, got {sha256(path)[:12]}…)")
    return not problems, problems


def chk_s011(root: Path) -> tuple[bool, list[str]]:
    out = subprocess.run([sys.executable, "tools/owner_certify.py"], cwd=root, capture_output=True, text=True,
                         env={**os.environ, "PYTHONUTF8": "1"}, timeout=3600)
    last = (out.stdout.strip().splitlines() or [""])[-1]
    ok = out.returncode == 0 and re.fullmatch(r"(\d+)/\1 PASS", last.strip()) is not None
    return ok, [] if ok else [f"owner_certify.py: {last or out.stderr.strip()[-200:]}"]


def chk_frozen(root: Path) -> tuple[bool, list[str]]:
    sys.path.insert(0, str(root))
    try:
        from tests_golden.fixtures.code_scan import frozen_changes
        changed = frozen_changes()
    except AssertionError as exc:
        return False, [str(exc)]
    finally:
        sys.path.remove(str(root))
    return not changed, [f"{p}: differs from {TAG}" for p in changed]


def chk_docs(root: Path) -> tuple[bool, list[str]]:
    out = subprocess.run([sys.executable, "tools/doc_consistency.py"], cwd=root, capture_output=True, text=True)
    lines = [l for l in out.stdout.splitlines() if l.startswith(("CONFLICT?", "ERROR"))]
    return out.returncode == 0, lines


def chk_records(root: Path, upto: list[str]) -> tuple[bool, list[str]]:
    found = records_open(root, upto)
    return not found, found


def chk_golden(root: Path, mid: str, repeats: int = 1) -> tuple[bool, list[str]]:
    target = golden_file(root, mid)
    if target is None:
        return False, [f"no golden file tests_golden/s12/{file_id(mid)}_*.py"]
    for i in range(repeats):
        c = run_pytest(root, target)
        if not clean(c):
            return False, [f"run {i + 1}/{repeats}: {c['tests']} tests, {c['failures']} failed, {c['errors']} error,"
                           f" {c['skipped']} skipped/xfail"]
    return True, [f"{c['tests']} passed" + (f" x{repeats}" if repeats > 1 else "")]


def chk_sabotage(root: Path, mid: str) -> tuple[bool, list[str]]:
    target, patches = golden_file(root, mid), sabotage_files(root, mid)
    if target is None or not patches:
        return False, [f"{mid}: no golden file or no sabotage patch"]
    problems = []
    for patch in patches:
        c = run_pytest(root, target, patch)
        if c["failures"] < 1 or c["errors"]:
            problems.append(f"{patch.name}: {c['failures']} failed, {c['errors']} error (needs >=1 failed, 0 error)")
    return not problems, problems


# --- run -------------------------------------------------------------------------------------------------------

def current_milestone(root: Path) -> str:
    data = json.loads((root / "docs" / "gates" / "s12_milestones.json").read_text(encoding="utf-8"))
    for m in data["milestones"]:
        if m["status"] not in ("green", "reviewed"):
            return norm(m["id"])
    return ORDER[-1]


def certify(root: Path, target: str, fast: bool) -> list[tuple[str, str, bool, list[str]]]:
    upto = ORDER[: ORDER.index(target) + 1]
    rows = [("S12-PIN", "pinned golden set and owner files unchanged", *chk_pins(root)),
            ("S12-S011", "S0–S11 certifier N/N", *chk_s011(root)),
            ("S12-FRZ", "frozen S0–S11 source identical to the tag", *chk_frozen(root)),
            ("S12-DOC", "document consistency", *chk_docs(root)),
            ("S12-REC", f"no open CONF/STOP for M0..{target}", *chk_records(root, upto))]
    for mid in upto[1:]:
        rows.append((f"G-{mid}", f"golden {mid} clean", *chk_golden(root, mid)))
        if mid in CONCURRENCY and not fast:
            rows.append((f"C-{mid}", f"golden {mid} {REPEATS} consecutive runs", *chk_golden(root, mid, REPEATS)))
    if target != "M0" and not fast:
        rows.append((f"X-{target}", f"sabotage patches of {target} caught", *chk_sabotage(root, target)))
    return rows


def write_progress(root: Path, target: str, rows) -> None:
    ok = {r[0]: r[2] for r in rows}
    detail = {r[0]: (r[3][0] if r[3] else "") for r in rows}
    _, head = git(root, "rev-parse", "--short", "HEAD")
    lines = ["# S12–S15 progress (generated)", "",
             f"Generated {date.today().isoformat()} by `tools/owner_certify_s12.py --progress` at commit `{head.strip()}`,"
             f" target {target}. Do not edit. This file, not the agent's log, is the progress of record (plan §6).", "",
             "| Milestone | Golden | Concurrency x5 | Sabotage |", "|---|---|---|---|"]
    for mid in ORDER[1: ORDER.index(target) + 1]:
        def cell(key):
            return "—" if key not in ok else ("PASS " if ok[key] else "FAIL ") + detail[key]
        lines.append(f"| {mid} | {cell('G-' + mid)} | {cell('C-' + mid)} | {cell('X-' + mid)} |")
    lines += ["", "| Standing check | Result |", "|---|---|"]
    for key in ("S12-PIN", "S12-S011", "S12-FRZ", "S12-DOC", "S12-REC"):
        lines.append(f"| {key} | {'PASS' if ok[key] else 'FAIL'} {detail[key]} |")
    (root / "docs" / "gates" / "S12_PROGRESS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def pin(root: Path) -> None:
    lines = [f"{sha256(root / rel)}  {rel}" for rel in pinned_paths(root)]
    (root / "docs" / "gates" / "s12_pins.sha256").write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"pinned {len(lines)} files")


# --- selftest: every check must detect its violation and pass a clean input -------------------------------------

def selftest() -> bool:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        # pins
        (t / "tests_golden").mkdir()
        (t / "docs" / "gates").mkdir(parents=True)
        (t / "tests_golden" / "a.py").write_text("x = 1\n")
        pin(t)
        clean_ok = chk_pins(t)[0]
        (t / "tests_golden" / "a.py").write_text("x = 2\n")
        results.append(("S12-PIN", not chk_pins(t)[0] and clean_ok))
        # records
        gates = t / "docs" / "gates"
        (gates / "S12_RECORDS.md").write_text("| CONF-001 | M2 | ruled | x | y | z |\n")
        (gates / "S12_STOPS.md").write_text("| STOP-001 | M3 | applied | x |\n")
        clean_ok = chk_records(t, ["M0", "M1", "M2", "M3"])[0]
        (gates / "S12_STOPS.md").write_text("| STOP-001 | M3 | ruled | x |\n")
        results.append(("S12-REC", clean_ok and not chk_records(t, ["M0", "M1", "M2", "M3"])[0]
                        and chk_records(t, ["M0", "M1", "M2"])[0]))
        # junit parsing: failure, error, skip and xfail are all not clean
        def junit(**kw):
            path = t / "j.xml"
            attrs = " ".join(f'{k}="{v}"' for k, v in {"tests": 3, "failures": 0, "errors": 0, "skipped": 0, **kw}.items())
            path.write_text(f'<testsuites><testsuite name="p" {attrs}></testsuite></testsuites>')
            return junit_counts(path)
        results.append(("G-junit", clean(junit()) and not any(clean(junit(**{k: 1})) for k in
                                                               ("failures", "errors", "skipped")) and not clean(junit(tests=0))))
        # milestone ids
        results.append(("ids", norm("m8a") == "M8a" and file_id("M3") == "M03" and file_id("M8a") == "M08a"))
    # golden, concurrency and sabotage checks through real pytest runs on a synthetic milestone
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "tests_golden" / "s12").mkdir(parents=True)
        (t / "tests_golden" / "sabotage").mkdir()
        golden = t / "tests_golden" / "s12" / "M03_synthetic.py"
        golden.write_text("import os\n\ndef test_a():\n    assert 'bad' not in os.environ.get('GOLDEN_SABOTAGE', '')\n")
        (t / "tests_golden" / "sabotage" / "M03_bad.py").write_text("def apply():\n    pass\n")
        clean_golden = chk_golden(t, "M3")[0] and chk_golden(t, "M3", 2)[0]
        caught = chk_sabotage(t, "M3")[0]
        (t / "tests_golden" / "sabotage" / "M03_harmless.py").write_text("def apply():\n    pass\n")
        uncaught_detected = not chk_sabotage(t, "M3")[0]
        failing = []
        for body in ("def test_a():\n    assert False\n",
                     "import pytest\n\ndef test_a():\n    pytest.skip('x')\n",
                     "import pytest\n\n@pytest.mark.xfail\ndef test_a():\n    assert False\n",
                     "import pytest\n\n@pytest.fixture\ndef f():\n    raise RuntimeError\n\ndef test_a(f):\n    pass\n",
                     "x = 1\n"):
            golden.write_text(body)
            failing.append(not chk_golden(t, "M3")[0])
        results.append(("G-M", clean_golden and all(failing)))
        results.append(("X-M", caught and uncaught_detected))
    for name, ok in results:
        print(f"  {name:<12} {'OK' if ok else 'BROKEN'}")
    return all(ok for _, ok in results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--milestone")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--pin", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.pin:
        pin(ROOT)
        return
    target = norm(args.milestone) if args.milestone else current_milestone(ROOT)
    if target not in ORDER:
        raise SystemExit(f"unknown milestone {target}")
    rows = certify(ROOT, target, args.fast)
    for key, title, ok, detail in rows:
        print(f"{key:<9} {title:<52} {'PASS' if ok else 'FAIL'}")
        for d in detail if not ok else []:
            print(f"          - {d}")
    passed = sum(1 for r in rows if r[2])
    print(f"\n{passed}/{len(rows)} PASS  (target {target}{', fast' if args.fast else ''})")
    if args.progress:
        write_progress(ROOT, target, rows)
    sys.exit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
