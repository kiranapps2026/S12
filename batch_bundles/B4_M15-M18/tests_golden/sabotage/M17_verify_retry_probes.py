"""M17 sabotage: every dead-letter retry asks the provider probe, whatever its retry_mode (D5: VERIFY re-runs only the
verifier; probe 0 calls)."""
def apply():
    from engine.stages.s14_dead_letter import retry
    original = retry.retry_dead_letter

    async def retry_dead_letter(tenant_id, dead_letter_id, *, dead_letters, probe, reverify):
        async def both(record):
            await probe(record)
            return await reverify(record)
        return await original(tenant_id, dead_letter_id, dead_letters=dead_letters, probe=probe, reverify=both)
    retry.retry_dead_letter = retry_dead_letter
