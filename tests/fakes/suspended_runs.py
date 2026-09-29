"""In-memory SuspendedRunStore that stores the encoded JSON, like the real store."""
from __future__ import annotations

import json

from supragents.contracts.codec import decode, encode
from supragents.contracts.state import PipelineState


class InMemorySuspendedRuns:
    def __init__(self, fail: bool = False) -> None:
        self.rows: dict[tuple[str, str], str] = {}
        self.fail = fail

    async def save(self, state, *, tenant_id, execution_id, confirmation_id) -> None:
        if self.fail:
            raise ConnectionError("store down")
        self.rows[(tenant_id, confirmation_id)] = json.dumps(encode(state))

    async def load(self, *, tenant_id, confirmation_id):
        row = self.rows.get((tenant_id, confirmation_id))
        return None if row is None else decode(PipelineState, json.loads(row))
