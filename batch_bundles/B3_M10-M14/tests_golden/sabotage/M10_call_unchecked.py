"""M10 sabotage: a GuardedCall is built without checking itself, so a call for one tenant may carry another's
metadata (C34), and attempt 0 or a zero deadline are accepted."""
def apply():
    from contracts.adapter_interface import GuardedCall
    GuardedCall.__post_init__ = lambda self: None
