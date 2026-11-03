class EngineError(Exception):
    """Base class for rule violations."""


class InvalidTransition(EngineError):
    """Action not allowed in the current phase or step."""


class WrongCode(EngineError):
    """Supervisor validation code does not match."""
