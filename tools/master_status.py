"""Master-folder status: one report that says whether THIS folder is a good-to-go copy of the certified branch.

    python tools/master_status.py                 # git, integrity, certifier, imports, environment, dev database
    python tools/master_status.py --tests         # also runs `pytest tests` (needs nothing else)
    python tools/master_status.py --postgres      # also runs `pytest tests_postgres` (needs TEST_DATABASE_URL, ~3 min)
    python tools/master_status.py --fetch         # first `git fetch origin` (skip when working offline)

Prints a PASS/FAIL table and writes MASTER_STATUS.md (git-ignored: it describes this machine) with every commit id.
Exit code 0 only when every required check passes. It never changes anything except that file. Secrets are never printed:
.env is only checked for which variable names it holds.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
BRANCH = "s0-s11-repair"
BASELINE = "s0-s11-baseline"
REMOTE_URL_PART = "kiranapps2026/S12"


def run(*cmd: str, timeout: int = 900, env: dict | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env={**os.environ, "PYTHONUTF8": "1", **(env or {})})
        return done.returncode, (done.stdout + done.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 99, f"{type(error).__name__}: {error}"


def git(*args: str) -> tuple[int, str]:
    return run("git", *args, timeout=120)


def env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip() and not key.strip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    return values


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []          # group, check, status, detail

    def add(self, group: str, check: str, ok: bool | None, detail: str = "", required: bool = True) -> None:
        status = "PASS" if ok else ("SKIP" if ok is None else ("FAIL" if required else "WARN"))
        self.rows.append((group, check, status, detail))

    @property
    def failed(self) -> bool:
        return any(r[2] == "FAIL" for r in self.rows)


def check_git(report: Report, fetch: bool) -> dict:
    facts: dict = {}
    code, top = git("rev-parse", "--show-toplevel")
    report.add("git", "folder is a git clone", code == 0, top if code == 0 else "not a git repository")
    if code != 0:
        return facts
    facts["root"] = top
    code, url = git("remote", "get-url", "origin")
    facts["remote"] = re.sub(r"//[^@/]+@", "//", url)                # never show credentials embedded in a URL
    report.add("git", "origin is the SuprAgents repository", code == 0 and REMOTE_URL_PART in url, facts["remote"])
    code, branch = git("branch", "--show-current")
    facts["branch"] = branch
    report.add("git", f"on branch {BRANCH}", branch == BRANCH, branch or "(detached HEAD)")
    _, head = git("rev-parse", "HEAD")
    _, short = git("rev-parse", "--short", "HEAD")
    facts["head"], facts["short"] = head, short
    _, subject = git("log", "-1", "--format=%s")
    facts["subject"] = subject
    if fetch:
        code, out = git("fetch", "origin", BRANCH, BASELINE)
        report.add("git", "fetched origin", code == 0, "ok" if code == 0 else out[-200:], required=False)
    code, remote_head = git("rev-parse", f"origin/{BRANCH}")
    if code == 0:
        facts["origin_head"] = remote_head
        _, counts = git("rev-list", "--left-right", "--count", f"HEAD...origin/{BRANCH}")
        ahead, behind = (int(x) for x in counts.split())
        facts["ahead"], facts["behind"] = ahead, behind
        report.add("git", "same commit as origin (last fetch)", ahead == 0 and behind == 0,
                   f"HEAD {short} = origin/{BRANCH} {remote_head[:7]}" if ahead == behind == 0 else f"ahead {ahead}, behind {behind}")
        if ahead:
            _, unpushed = git("log", "--oneline", f"origin/{BRANCH}..HEAD")
            facts["unpushed"] = unpushed
    else:
        report.add("git", "same commit as origin (last fetch)", False, f"origin/{BRANCH} is not known here: run with --fetch")
    _, dirty = git("status", "--porcelain")
    facts["dirty"] = dirty
    report.add("git", "working tree clean", not dirty, "clean" if not dirty else f"{len(dirty.splitlines())} changed file(s)")
    code, base = git("rev-parse", f"origin/{BASELINE}")
    if code == 0:
        code2, _ = git("merge-base", "--is-ancestor", base, "HEAD")
        facts["baseline"] = base
        report.add("git", f"{BASELINE} ({base[:7]}) is the ancestor the repair started from", code2 == 0, base[:7], required=False)
    code, tag = git("rev-parse", "--verify", "--quiet", "refs/tags/s0-s11-certified^{commit}")
    facts["tag"] = tag if code == 0 else None
    report.add("git", "tag s0-s11-certified", None if code != 0 else tag == head,
               "not created yet" if code != 0 else (f"on this commit ({tag[:7]})" if tag == head else f"on {tag[:7]}, HEAD is {short}"))
    _, count = git("rev-list", "--count", "HEAD")
    facts["commits"] = count
    return facts


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def check_integrity(report: Report) -> dict:
    facts = {"certifier": sha(ROOT / "tools" / "owner_certify.py")}
    stored = (ROOT / "docs" / "gates" / "owner_certify.sha256").read_text(encoding="utf-8").strip().upper()
    match = re.search(r'^\$expected\s*=\s*"([0-9A-Fa-f]+)"', (ROOT / "tools" / "owner_verify.ps1").read_text(encoding="utf-8-sig"), re.M)
    expected = match.group(1).upper() if match else "(not found)"
    facts["verify"], facts["stored"] = expected, stored
    ok = facts["certifier"] == expected == stored
    report.add("integrity", "certifier hash = owner_verify.ps1 = docs/gates/owner_certify.sha256", ok, facts["certifier"][:12] + "…")
    return facts


def check_certifier(report: Report) -> None:
    code, out = run(sys.executable, "tools/owner_certify.py")
    line = next((l for l in reversed(out.splitlines()) if re.search(r"\d+/\d+ PASS", l)), out[-200:])
    report.add("certification", "owner_certify.py", code == 0 and "19/19 PASS" in out, line.strip())
    code, out = run(sys.executable, "tools/owner_certify.py", "--selftest")
    report.add("certification", "owner_certify.py --selftest", code == 0, out.splitlines()[-1] if out else "")


def check_environment(report: Report, values: dict) -> None:
    report.add("environment", "Python 3.11+", sys.version_info >= (3, 11), platform.python_version())
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    report.add("environment", "virtual environment active", in_venv, sys.prefix if in_venv else "system Python", required=False)
    try:
        import engine
        path = Path(engine.__file__).resolve()
        report.add("environment", "code is imported from THIS folder", ROOT in path.parents, str(path.parent))
    except ImportError as error:
        report.add("environment", "code is imported from THIS folder", False, f"cannot import engine: {error}")
    report.add("environment", "PYTHONUTF8=1 (Windows: needed by the tests)", os.environ.get("PYTHONUTF8") == "1" or sys.flags.utf8_mode == 1,
               "set" if os.environ.get("PYTHONUTF8") == "1" or sys.flags.utf8_mode else "not set: setx PYTHONUTF8 1", required=platform.system() == "Windows")
    code, out = run(sys.executable, "-m", "pip", "check")
    report.add("environment", "installed packages consistent (pip check)", code == 0, out.splitlines()[0][:100] if out else "")
    names = sorted(values)
    report.add("environment", ".env present", bool(values), ", ".join(names) if names else "missing")
    for name in ("DATABASE_URL",):
        report.add("environment", f".env has {name}", name in values and bool(values[name]), "set" if values.get(name) else "missing")
    report.add("environment", ".env has DEEPSEEK_API_KEY (live model)", bool(values.get("DEEPSEEK_API_KEY")), "set" if values.get("DEEPSEEK_API_KEY") else "missing", required=False)
    code, tracked = git("ls-files", ".env")
    report.add("environment", ".env is NOT tracked by git", not tracked, "git-ignored" if not tracked else "TRACKED: remove it from git")
    code, hits = git("grep", "-lE", r"sk-[A-Za-z0-9]{20,}|postgresql(\+asyncpg)?://[^:\s]+:[^@\s<]{6,}@", "--", ":!tests*", ":!*.md", ":!.env.example")
    report.add("environment", "no key or database password in tracked source", code == 1, "none found" if code == 1 else f"found in: {hits.replace(chr(10), ', ')[:150]}")


async def _database(url: str) -> dict:
    import asyncpg
    from adapters.postgres.database import normalize_url
    connection = await asyncpg.connect(normalize_url(url), timeout=10)
    try:
        facts = {}
        facts["role"] = dict(await connection.fetchrow("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))
        facts["applied"] = [r["name"] for r in await connection.fetch("SELECT name FROM schema_migrations ORDER BY name")]
        facts["tables"] = await connection.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        facts["ops"] = await connection.fetchval("SELECT count(*) FROM kernel_ops")
        facts["caps"] = await connection.fetchval("SELECT count(*) FROM capabilities")
        facts["binds"] = await connection.fetchval("SELECT count(*) FROM bindings")
        facts["versions"] = await connection.fetchval("SELECT count(*) FROM registry_versions")
        facts["blocked"] = await connection.fetchval(
            "SELECT count(*) FROM kernel_ops WHERE truth_state = 'PRODUCTION_ENABLED' AND mutation <> 'R'"
            " AND (observation_method IS NULL OR observation_method = '')")
        facts["tenants"] = await connection.fetchval("SELECT count(*) FROM tenants") if not facts["role"]["rolsuper"] else None
        return facts
    finally:
        await connection.close()


def check_database(report: Report, values: dict) -> dict:
    url = os.environ.get("DATABASE_URL") or values.get("DATABASE_URL")
    if not url:
        report.add("dev database", "DATABASE_URL", False, "not configured")
        return {}
    try:
        facts = asyncio.run(_database(url))
    except Exception as error:  # noqa: BLE001 - report the class only: messages can carry the connection string
        report.add("dev database", "connect and read", False, f"{type(error).__name__} (is PostgreSQL running? is the password right?)")
        return {}
    files = sorted(p.name for p in (ROOT / "src" / "adapters" / "postgres" / "migrations").glob("*.sql"))
    report.add("dev database", "connects as a plain role (not superuser, cannot bypass RLS)",
               facts["role"]["rolsuper"] is False and facts["role"]["rolbypassrls"] is False, str(facts["role"]))
    report.add("dev database", f"all {len(files)} migrations applied", facts["applied"] == files,
               f"{len(facts['applied'])} applied, {len(files)} in the repo", )
    report.add("dev database", "registry loaded (operations, capabilities, bindings, versions)",
               facts["ops"] > 0 and facts["caps"] > 0 and facts["binds"] > 0 and facts["versions"] == 1,
               f"{facts['ops']} ops, {facts['caps']} capabilities, {facts['binds']} bindings, versions row: {facts['versions']}")
    report.add("dev database", "registry readiness: no production write/delete without an observation method", facts["blocked"] == 0,
               f"{facts['blocked']} blocked")
    return facts


def pytest_counts(report: Report, group: str, label: str, target: str, env: dict | None = None) -> str:
    code, out = run(sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider", env=env, timeout=1800)
    summary = next((l for l in reversed(out.splitlines()) if re.search(r"\d+ (passed|failed|error)", l)), out[-200:])
    match = re.search(r"(\d+) passed", summary)
    ok = code == 0 and match is not None and "failed" not in summary and "error" not in summary
    report.add(group, label, ok, summary.strip("= ").strip())
    return summary


def write_markdown(report: Report, facts: dict, integrity: dict, db: dict, path: Path) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ok = not report.failed
    lines = [f"# Master status: {'GOOD TO GO' if ok else 'NOT READY'}", "",
             f"Generated {now} by `tools/master_status.py` on {platform.node()} ({platform.system()}, Python {platform.python_version()}).", "",
             "## Commit ids", "",
             f"| What | Commit |", "|---|---|",
             f"| This folder (`{facts.get('branch', '?')}`) | `{facts.get('head', '?')}` {facts.get('subject', '')} |",
             f"| origin/{BRANCH} (last fetch) | `{facts.get('origin_head', 'unknown')}` |",
             f"| {BASELINE} (untouched snapshot) | `{facts.get('baseline', 'unknown')}` |",
             f"| tag s0-s11-certified | `{facts.get('tag') or 'not created yet'}` |",
             f"| commits on this branch | {facts.get('commits', '?')} |", ""]
    if facts.get("unpushed"):
        lines += ["Unpushed local commits:", "", "```", facts["unpushed"], "```", ""]
    lines += ["## Integrity hashes (must all be equal)", "", f"- certifier file: `{integrity.get('certifier')}`",
              f"- owner_verify.ps1: `{integrity.get('verify')}`", f"- docs/gates/owner_certify.sha256: `{integrity.get('stored')}`", "",
              "## Checks", "", "| Group | Check | Result | Detail |", "|---|---|---|---|"]
    for group, check, status, detail in report.rows:
        lines.append(f"| {group} | {check} | **{status}** | {detail.replace('|', '/')} |")
    if db:
        lines += ["", f"Dev database: {db.get('tables')} tables, {len(db.get('applied', []))} migrations applied."]
    lines += ["", "PASS = verified now. SKIP = not applicable yet. WARN = not required for a good-to-go folder. FAIL = fix before working here.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    report, values = Report(), env_file()
    facts = check_git(report, args.fetch)
    integrity = check_integrity(report)
    check_certifier(report)
    check_environment(report, values)
    db = check_database(report, values)
    if args.tests:
        pytest_counts(report, "tests", "pytest tests (unit, contract, architecture, golden)", "tests")
    if args.postgres:
        url = os.environ.get("TEST_DATABASE_URL") or values.get("TEST_DATABASE_URL")
        if not url or not re.search(r"_test\s*$", url):
            report.add("tests", "pytest tests_postgres", False, "TEST_DATABASE_URL must be set and end in _test")
        else:
            pytest_counts(report, "tests", "pytest tests_postgres (real PostgreSQL, RLS enforced)", "tests_postgres", env={"TEST_DATABASE_URL": url})
    width = max(len(r[1]) for r in report.rows)
    for group, check, status, detail in report.rows:
        print(f"{status:4}  {group:13} {check:{width}}  {detail}")
    out = ROOT / "MASTER_STATUS.md"
    write_markdown(report, facts, integrity, db, out)
    print(f"\n{'GOOD TO GO' if not report.failed else 'NOT READY'} - report written to {out.name}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
