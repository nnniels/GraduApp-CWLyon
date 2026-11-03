class EngineError(Exception):
    """Base class for rule violations."""


class InvalidTransition(EngineError):
    """Action not allowed now (wrong phase, stale step, closed window...).

    Lazy expiry may already have changed the state before the action was refused.
    `state` and `events` carry that outcome so the caller can still persist it.
    """

    def __init__(self, message: str, *, state=None, events=()):
        super().__init__(message)
        self.state = state
        self.events = tuple(events)
