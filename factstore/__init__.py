"""factstore: a small, generic store of facts, slightly more structured than a wiki.

A fact is (subject, action, object) plus an optional validity interval, a signed confidence, provenance and free
attributes. Aliases, types, 'me' and reviews are all built from ordinary facts. The engine has no dependency on any
transport or framework (it uses only the standard library) and takes the acting ``actor`` explicitly on every call,
so it can be wrapped as MCP tools, a CLI or an HTTP API without change.
"""

from .config import Config
from .errors import (
    AmbiguousEntityError,
    DatabaseBusyError,
    FactsError,
    NoSelfBindingError,
    NotFoundError,
    PermissionDeniedError,
    SchemaVersionError,
    ValidationError,
)
from .schema import SCHEMA_VERSION
from .store import UNSET, FactStore
from .values import parse_date_value, parse_when, uuid7

__all__ = [
    "SCHEMA_VERSION",
    "UNSET",
    "AmbiguousEntityError",
    "Config",
    "DatabaseBusyError",
    "FactStore",
    "FactsError",
    "NoSelfBindingError",
    "NotFoundError",
    "PermissionDeniedError",
    "SchemaVersionError",
    "ValidationError",
    "parse_date_value",
    "parse_when",
    "uuid7",
]
