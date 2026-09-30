"""The observation-method proposal: read-only, conservative, and never invents a read for an effect it cannot name."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import propose_observation as proposal  # noqa: E402


def _op(op_id, mutation="W", inverse=None):
    return {"kernel_op_id": op_id, "mutation": mutation, "inverse": inverse}


def test_create_update_and_delete_get_a_read_and_delete_expects_absence():
    ops = [_op("crm.contact_create"), _op("crm.contact_update"), _op("crm.contact_delete", "D")]
    sql = "\n".join(proposal.propose(ops, {o["kernel_op_id"] for o in ops}))
    assert "observation_method = 'get_contact', observation_identifier_field = 'id' WHERE kernel_op_id = 'crm.contact_create'" in sql
    assert "observation_expects_absent = true WHERE kernel_op_id = 'crm.contact_delete'" in sql
    assert "inverse = 'crm.contact_delete' WHERE kernel_op_id = 'crm.contact_create'" in sql


def test_an_existing_inverse_is_not_overwritten_and_a_missing_delete_is_not_invented():
    lines = proposal.propose([_op("crm.contact_create", inverse="crm.contact_remove")], {"crm.contact_create"})
    assert not any("SET inverse" in line for line in lines)
    lines = proposal.propose([_op("crm.contact_create")], {"crm.contact_create"})
    assert not any("SET inverse" in line for line in lines)


def test_operations_without_a_readable_effect_are_left_for_the_owner():
    lines = proposal.propose([_op("msg.email_send"), _op("pay.charge", "IRREVERSIBLE"), _op("oddname", "W")], set())
    assert all(line.startswith("-- NEEDS OWNER") for line in lines) and len(lines) == 3
