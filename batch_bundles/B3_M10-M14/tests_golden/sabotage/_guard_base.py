"""Shared by the M10 sabotage patches: capture the components a ReliabilityGuard was built with (public keyword
arguments only), so a patch can wrap them. Not a sabotage patch itself (the certifier only runs files named Mxx_*)."""


def capture(transform=None):
    """Patch ReliabilityGuard.__init__ to keep its keyword arguments in ``guard._sabotage`` (after ``transform``)."""
    from engine.stages.s12_execute.reliability import ReliabilityGuard
    original = ReliabilityGuard.__init__

    def __init__(self, adapter, **kw):
        if transform is not None:
            kw = transform(kw)
        original(self, adapter, **kw)
        self._sabotage = kw
    ReliabilityGuard.__init__ = __init__


class BreakerProxy:
    """Delegates to a real breaker; ``overrides`` maps a method name to a replacement ``fn(breaker, provider)``."""
    def __init__(self, breaker, **overrides):
        self._b, self._o = breaker, overrides

    def __getattr__(self, name):
        if name in self._o:
            return lambda provider: self._o[name](self._b, provider)
        return getattr(self._b, name)
