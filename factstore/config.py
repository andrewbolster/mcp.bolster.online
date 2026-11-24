"""Conventions the engine uses, as configurable defaults rather than hard-coded vocabulary."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Every convention the engine relies on. Change them by passing a different ``Config`` to ``FactStore``."""

    alias_action: str = "Alias of"
    type_action: str = "Is a"
    #: Prefixes that are parsed off a name (``person:Ada``). Any other ``word:`` prefix stays part of the name.
    kinds: frozenset[str] = frozenset({"person", "place", "org", "date", "number", "text", "actor"})
    #: Kinds whose names are values, not entities (so they are never nagged about for a missing type).
    value_kinds: frozenset[str] = frozenset({"date", "number", "text"})
    #: Kind of the alias fact that binds an actor to an entity (``actor:alice`` alias of ``person:Alice Example``).
    actor_kind: str = "actor"
    #: Names that always mean "the entity the calling actor is bound to".
    self_tokens: frozenset[str] = frozenset({"me", "self"})
    max_text: int = 200
    max_attributes_bytes: int = 4096
    max_references: int = 20
    max_reference_length: int = 500
    max_alias_depth: int = 10
    max_type_depth: int = 10
    max_entity_names: int = 200
    default_limit: int = 50
    max_limit: int = 200
    #: Most facts ``add_many`` accepts in one call (one transaction).
    max_batch: int = 100
    #: Most review entries ``get_fact`` lists for one fact.
    max_reviews_shown: int = 20
    #: Most entities one ``dependents`` walk collects before it stops and reports ``capped``.
    max_dependents: int = 1000
    #: A fact counts as due for review once this many days have passed since it was created or last reviewed.
    review_interval_days: int = 90
