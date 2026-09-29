"""S0–S11 through bootstrap.build_runner on real PostgreSQL (only the LLM is scripted)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from supragents.bootstrap import build_runner
from supragents.contracts.reply import ConfirmationReply
from supragents.contracts.vocabulary import ConfirmationStatus, StageStatus
from supragents.pipeline.result import RunOutcome
from tests.builders import entry
from tests.fakes.ports import ScriptedIntentModel, intent_json

IDENTITY = dict(tenant_id="tenant-a", workspace_id="tenant-a.ws", user_id="tenant-a.user",
                membership_id="tenant-a.member", connection_id="tenant-a.conn")


def _request(text: str):
    return entry(text, **IDENTITY)


async def _events(db, trace_id):
    async with db.tenant_transaction("tenant-a") as connection:
        return [r["stage"] for r in await connection.fetch(
            "SELECT stage FROM pipeline_events WHERE trace_id = $1 ORDER BY event_id", trace_id)]


def test_read_request_completes_with_database_versions(pg):
    async def body(db):
        result = await build_runner(db, ScriptedIntentModel(intent_json("contact.list"))).run(
            _request("list contacts"))
        return result, await _events(db, result.state.execution_context.trace_id)
    result, stages = pg(body)
    assert result.outcome is RunOutcome.COMPLETED
    assert result.manifest.policy_version == "tenant-a.policy-1"
    assert result.manifest.capability_version == "cap-7"
    assert stages == [f"S{i}" for i in range(12)]


def test_delete_waits_for_confirmation_then_completes(pg):
    async def body(db):
        runner = build_runner(db, ScriptedIntentModel(intent_json("contact.delete", id="c-1")))
        suspended = await runner.run(_request("delete contact c-1"))
        reply = ConfirmationReply(suspended.pending_confirmation.confirmation_id, "tenant-a.user", True)
        resumed = await runner.resume(suspended, reply)
        again = await runner.resume(suspended, reply)
        return suspended.outcome, resumed, again.halt.reason
    first, resumed, second = pg(body)
    assert first is RunOutcome.AWAITING_CONFIRMATION
    assert resumed.outcome is RunOutcome.COMPLETED
    assert resumed.state.confirmation_check.status is ConfirmationStatus.CONSUMED
    assert second == "confirmation_not_consumable"


def test_paused_tenant_is_denied_at_s0(pg):
    async def body(db):
        model = ScriptedIntentModel()
        result = await build_runner(db, model).run(_request("list contacts"))
        return result.halt, model.calls
    halt, calls = pg(body, "UPDATE tenants SET paused_until = now() + interval '1 hour' WHERE tenant_id = 'tenant-a'")
    assert (halt.stage, halt.status, halt.reason, calls) == ("S0", StageStatus.DENY, "tenant_paused", [])


def test_workspace_of_another_tenant_is_refused(pg):
    async def body(db):
        request = entry("list contacts", **{**IDENTITY, "workspace_id": "tenant-b.ws"})
        return (await build_runner(db, ScriptedIntentModel()).run(request)).halt
    halt = pg(body)
    assert (halt.stage, halt.reason) == ("S0", "activation_state_unavailable")


def test_command_line_check(database_url, pg):
    pg(_seed_only)
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "DATABASE_URL": database_url, "PYTHONPATH": str(root / "src")}
    result = subprocess.run([sys.executable, "-m", "supragents", "check"], env=environment,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "database OK" in result.stdout


async def _seed_only(db):
    return None
