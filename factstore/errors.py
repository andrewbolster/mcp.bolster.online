"""Errors raised by the fact store. None of them knows about any transport or framework."""


class FactsError(Exception):
    """Base class: anything the caller can fix by changing the request."""


class ValidationError(FactsError):
    """A value is malformed or out of range."""


class NotFoundError(FactsError):
    """No such fact, or it exists but the actor may not see it (the two are deliberately indistinguishable)."""


class PermissionDeniedError(FactsError):
    """The actor can see the fact but may not change it."""


class AmbiguousEntityError(FactsError):
    """A name resolves to more than one entity. Carries the candidates so the caller can choose."""

    def __init__(self, name: str, candidates: list[str], hint: str | None = None):
        self.name = name
        self.candidates = candidates
        listed = ", ".join(repr(c) for c in candidates)
        super().__init__(f"{name!r} is ambiguous: it resolves to {listed}. {hint or 'Use one of those full names.'}")


class NoSelfBindingError(FactsError):
    """'me' was used but the actor has not said which entity they are."""


class SchemaVersionError(FactsError):
    """The database was written by a different schema version than this code understands."""
