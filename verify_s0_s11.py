"""Master verification for the S0–S11 pipeline: one file, one command, one verdict.

Usage (from the repository root, Python 3.11+ and pytest installed):
    python verify_s0_s11.py               # run every test group
    python verify_s0_s11.py --sabotage    # also prove the tests catch 14 known bugs
    python verify_s0_s11.py --report verification.md

Exit code 0 means every group passed (and, with --sabotage, every bug was caught).
Sabotage patches are applied to a temporary copy; the files here are never modified.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = (
    ("contracts", "tests/contracts", "write-once state, plan hash, confirmation store"),
    ("unit", "tests/unit", "each stage S0–S11 on its own"),
    ("journeys", "tests/journeys", "full S0→S11 runs, every stop and the confirmation flow"),
    ("architecture", "tests/architecture", "no dead code, layering, size limits, no test doubles"),
)
SABOTAGE = (
    ("runner ignores halts", "src/supragents/pipeline/runner.py",
     "            if state.halt is not None:\n                return RunResult(RunOutcome.STOPPED, state)\n", ""),
    ("runner ignores pending confirmation", "src/supragents/pipeline/runner.py",
     "            if _awaiting_confirmation(stage_id, state):", "            if False:"),
    ("S0 sets workspace = tenant", "src/supragents/stages/s00_entry.py",
     "request_id=str(uuid.uuid4()), **identity)",
     "request_id=str(uuid.uuid4()), **{**identity, 'workspace_id': identity['tenant_id']})"),
    ("S0.1 pause check skipped", "src/supragents/stages/s00_entry.py",
     "    return await _check_activation(state, deps)", "    return state"),
    ("S1 lets injection through", "src/supragents/stages/s01_normalize.py",
     "    if sanitized.high_severity:\n        return state.halted(STAGE, StageStatus.DENY, \"injection_detected\")\n", ""),
    ("S5 risk ignores the registry", "src/supragents/policy/risk.py", "    return risk\n", "    return 0.0\n"),
    ("S5 skips policy versions", "src/supragents/stages/s05_binding.py",
     "    return await _record_policy_versions(state, deps)", "    return state"),
    ("S7 deny does not stop", "src/supragents/stages/s07_path.py", "    PathDecision.DENY: StageStatus.DENY,\n", ""),
    ("S8 ignores the kill switch", "src/supragents/stages/s08_safety/gate.py",
     "    if policy.kill_switch_engaged is not False:", "    if False:"),
    ("S9–S11 safety guard disabled", "src/supragents/stages/guards.py",
     "    if safety is not None and safety.allowed and context is not None and context.auth_passed:",
     "    if True:"),
    ("S10 ignores expiry", "src/supragents/stages/s10_confirmation.py",
     "    if stored.confirmation.expires_at <= deps.clock.now():", "    if False:"),
    ("S11 skips the confirmation check", "src/supragents/stages/s11_validation.py",
     "    return [] if check.status in _CONFIRMED else [\"confirmation_missing\"]", "    return []"),
    ("S11 skips the cycle check", "src/supragents/stages/s11_validation.py",
     "    if _has_cycle(plan):", "    if False:"),
    ("state allows overwriting a field", "src/supragents/contracts/state.py",
     "        if getattr(self, name) is not None:", "        if False:"),
)


@dataclass(frozen=True)
class Outcome:
    name: str
    ok: bool
    detail: str


def main() -> int:
    args = _arguments()
    _require_layout()
    outcomes = [_run_group(name, path, about) for name, path, about in GROUPS]
    if args.sabotage:
        outcomes += _run_sabotage()
    report = _render(outcomes)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    return 0 if all(outcome.ok for outcome in outcomes) else 1


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the S0–S11 pipeline.")
    parser.add_argument("--sabotage", action="store_true", help="prove the tests catch known bugs")
    parser.add_argument("--report", metavar="FILE", help="also write the result table to FILE")
    return parser.parse_args()


def _require_layout() -> None:
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11 or newer is required.")
    missing = [p for p in ("src/supragents", "tests", "pyproject.toml") if not (ROOT / p).exists()]
    if missing:
        sys.exit(f"Put this file in the repository root; not found here: {', '.join(missing)}")
    if subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True).returncode:
        sys.exit("pytest is not installed. Run: python -m pip install pytest")


def _pytest(root: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=root, capture_output=True, text=True,
    )


def _run_group(name: str, path: str, about: str) -> Outcome:
    result = _pytest(ROOT, path)
    summary = (result.stdout.strip().splitlines() or ["no output"])[-1]
    return Outcome(f"tests: {name} ({about})", result.returncode == 0, summary)


def _run_sabotage() -> list[Outcome]:
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "repo"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        return [_sabotage_case(copy, *case) for case in SABOTAGE]


def _sabotage_case(copy: Path, name: str, relative: str, old: str, new: str) -> Outcome:
    path = copy / relative
    original = path.read_text(encoding="utf-8")
    if original.count(old) != 1:
        return Outcome(f"sabotage: {name}", False, "patch no longer applies: update SABOTAGE")
    path.write_text(original.replace(old, new), encoding="utf-8")
    try:
        caught = _pytest(copy, "tests").returncode != 0
    finally:
        path.write_text(original, encoding="utf-8")
    return Outcome(f"sabotage: {name}", caught, "caught by the tests" if caught else "NOT caught")


def _render(outcomes: list[Outcome]) -> str:
    lines = ["| Result | Check | Detail |", "|---|---|---|"]
    lines += [f"| {'PASS' if o.ok else 'FAIL'} | {o.name} | {o.detail} |" for o in outcomes]
    failed = sum(not o.ok for o in outcomes)
    verdict = "VERIFIED" if failed == 0 else f"NOT VERIFIED — {failed} check(s) failed"
    return "\n".join(["# S0–S11 verification", "", *lines, "", f"**{verdict}**"])


if __name__ == "__main__":
    sys.exit(main())
