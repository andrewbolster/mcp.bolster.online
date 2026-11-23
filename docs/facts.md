# Facts

A small, generic store of facts, slightly more structured than a wiki. A fact is `(subject, action, object)` plus an optional validity interval, a signed confidence, provenance and free attributes. Aliases, types, "me" and reviews are all ordinary facts or small tables beside them. This is a fact store, not a reality store: several actors can hold conflicting facts, and confidence says how much each is believed.

## Layers

```
facts_tools.py   MCP adapter: tool wrappers, actor from the verified GitHub login, database location
factstore/       the engine: standard library only, explicit `actor` on every call, no auth, no MCP
SQLite           data/facts.sqlite3 (override with MCP_DATA_DIR); WAL; in-place schema migrations; JSONL export/import for backup
```

`tests/test_factstore_architecture.py` fails if any `factstore` module imports MCP, a web framework or this app, so the engine can be moved to its own repository with `git mv`. Conventions are `factstore.Config` defaults, not hard-coded vocabulary: alias action `Alias of`, type action `Is a`, kinds `person place org date number text actor`.

## A fact

| Field | Meaning |
| --- | --- |
| `id` | UUIDv7 |
| `subject`, `action`, `object` | free text up to 200 characters; names may carry a kind prefix (`person:Ada Example`, `date:1988-05-17`) |
| `confidence` | -1.0 to 1.0, default 1.0. 0 is "no statement"; negative is a falsification. Queries return positive facts unless `include_negative` |
| `valid_from`, `valid_to` | optional ISO 8601 (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or a datetime; UTC when no offset). A coarse `valid_to` includes its whole period |
| `public` | readable by every authenticated user (default private) |
| `attributes` | optional JSON object, up to 4 KB, searchable by key and value |
| `references` | optional list of sources |
| `created_by/at`, `updated_by/at` | provenance, server-set |
| `reviewed_by/at` | the latest confirmation |

Values such as dates are objects with a kind: "my birthday is 17 May 1988" is (`me`, `Has birthday`, `date:1988-05-17`); `--05-17` is a date with no known year. Only the `date` kind is validated. A prefix is parsed only when it is a recognised kind, so `Meeting: standup` stays literal.

## Names, aliases and "me"

- An alias is the fact (`bolster`, `Alias of`, `person:Ada Example`). Names are canonicalised when written, and a queried name matches every alias of its entity, so facts written before the alias existed are still found. Chains are followed ten hops; cycles and self-aliases are refused.
- A name that resolves to more than one entity is an error listing the candidates (with their kind prefixes). A kind prefix on the name (`org:PPS`) or a `subject_kind`/`object_kind` filter picks the candidate of that kind; if that still leaves several, or none, it is an error again. Nothing is guessed.
- `me` and `self` mean the calling actor's entity, bound with `set_self` as the alias fact (`actor:<login>`, `Alias of`, entity). Only the actor can write their own `actor:` name.
- Matching is by folded name and kind. Folding ignores case, spacing and accents, so `Zoë`, `ZOE` and `zoe` are one name; the name is stored and shown as written. A name without a kind matches any kind, and a stored name without a kind matches any queried kind. Actor identifiers are the exception: they fold case only, so `josé` and `jose` are different actors.
- A name that looks like a kind prefix the store does not know (`claim:Foo`) is stored as that literal text, and the reply carries a `warnings` list saying so (only when there is something to say). `Meeting: standup` and URLs are not flagged.
- Values (`date:`, `number:`, `text:`) are never alias-resolved.

## Visibility and reviews

One rule decides what an actor can read, for every tool: scope `mine` (created by the actor), `public`, or `all` (both, plus the single facts the actor has been asked to review). Only the creator changes or deletes a fact; someone else's private fact looks exactly like a missing id.

An owner can ask another actor to review a fact. While the request is open, that actor can read that one fact. `mark_reviewed` records `confirmed` (stamps `reviewed_by/at`), `disputed` or `unsure`, and closes the actor's open requests on the fact. A dispute by someone other than the owner creates the reviewer's own private fact on the same triple with the opposite sign of the disputed fact (-1.0 for a believed fact or one with confidence 0, +1.0 for a falsification) that references the disputed one; the owner's fact is untouched. A reviewer can state a graded dispute with `confidence`, which must have that opposite sign. An owner cannot dispute their own fact: the call is rejected and points to `update_fact` (lower the confidence, or set `valid_to`). An owner can still `confirm` or mark `unsure`.

Outcomes are visible to the fact's owner: `get_fact` lists `reviews` (reviewer, outcome, note, time; newest first, up to 20) and `review_outcomes` lists recent entries across all of the owner's facts. `review_outcomes(role=...)` chooses whose entries: `owner` (default) what others said about the actor's facts, `reviewer` the reviews the actor wrote on any fact (confirmed ones included), `all` both; each entry says which `role` the actor had. A reviewer's counter-fact stays private to them, so the owner learns only that a dispute exists. Anyone else sees only their own entries on a fact, and the fact's wording only while they can still read it, so a reviewer whose request has closed gets the fact id, their verdict and their note, and nothing else. `due_for_review` lists the actor's facts last reviewed (or, never reviewed, created) before a cutoff, 90 days ago by default, filtered by `action`, `subject`, `object_kind` or `created_before` and ordered `oldest_reviewed` (default), `lowest_confidence` or `newest`; `pending_reviews` lists open requests.

## Searching

- **Validity.** `valid_at` keeps facts valid at an instant (an open bound counts as valid). `valid_from`/`valid_to` keep facts whose period *overlaps* that window, and a fact with no period, or an open bound, overlaps any window. With `valid_within=true` the fact's period must lie *entirely inside* the window instead, so facts with no period, or an open bound where the window has one, are excluded. `has_period` keeps facts that have a `valid_from` or `valid_to` (true) or neither (false).
- **Review state.** `reviewed_before` keeps facts last reviewed before a time; facts never reviewed are not included unless `include_never_reviewed` is set, which counts creation as the baseline. `reviewed=true` keeps facts that have been reviewed, `reviewed=false` those that never were.
- **Free text.** `q` needs every word (any order, ignoring case and accents) to appear in the subject, object, action, attribute names and values (nested too), or references. It is a plain substring match, not a ranked search, and attributes are matched only within facts the scope can see.

## Results

Every list reply carries `count` (rows returned), `total` (all matches), `offset`, `limit` and `truncated` (true when more follow), so a cut-off is never silent; `offset` reads the next page. `relationships_between` reports `direct_truncated` and `indirect_truncated`. Facts carry `subject_ref` and `object_ref`, the names with their kind prefix, which can be passed straight back into a query. `describe_entity` has `exists`, which is false for a name no visible fact mentions. `add_fact` lists `untyped` names only when asked (`check_types`), and `add_facts` writes up to 100 facts in one all-or-nothing transaction.

## Portability

`python -m factstore export --db data/facts.sqlite3 --all > backup.jsonl` and `... import` write and read JSON Lines: a header (`format: factstore-jsonl` and the `schema_version` that wrote it), then facts, reviews and review requests. Import keeps ids and `created_at`, skips ids it already has, recomputes the folded name columns, and is all-or-nothing. A file from an older schema version imports into a newer one; a file from a newer one is refused.

**Schema versions.** The current version is 3. Opening a database written by an older version upgrades it in place when every step is known (`MIGRATIONS` in `factstore/schema.py`; version 2 to 3 recomputes the folded name columns with the accent-insensitive fold). The upgrade runs in one transaction with the version bump, so a failure leaves the database as it was, and it first copies the database to `<name>.pre-v<N>.bak` next to it (once). Opening a database written by a *newer* version, or an older one with no known path, is refused without touching it: use matching code, or export with the code that wrote it and import here. So rolling the code back after an upgrade is refused rather than silently damaging the data: restore the `.bak` (anything written since the upgrade is lost) or stay on the newer code.

## Assumptions to confirm

1. `valid_from`/`valid_to` replace `time` from PR 51. `created_at` is the assertion time and is only overridable through import.
1. `valid_to` includes its period (so `valid_to='2015'` means through the end of 2015); `valid_to` before `valid_from` is refused.
1. Only the date kind is validated; numbers and text are stored as given.
1. Alias facts are hidden from `search_facts` unless the action is `Alias of`; `describe_entity` lists them.
1. Only the fact's owner can request a review; a request grants read access to that one fact; anyone who can see a fact (including a public one) can review it.
1. An owner cannot dispute their own fact (rejected, with a pointer to `update_fact`); `unsure` only logs.
1. Folding strips accents by Unicode compatibility decomposition (so `ß` is `ss`, `ﬁ` is `fi` and `…` is `...`). Two names that differ only by accents are the same entity, and upgrading a database merges any that existed separately.
1. A reviewer's `review_outcomes` entry shows the fact's wording only while the reviewer can still read the fact.
1. `describe_entity` counts exclude alias facts and facts with confidence 0 or below; `exists` does not.
1. `relationships_between` matches intermediaries by folded name, ignores alias and non-positive facts, and caps depth at 2, direct facts at 200 and paths at 100 (reporting when it cuts off).
1. A reviewer can read their own entries on a fact only while they can still read the fact: a public fact, or a private one while their request is open.
1. `due_for_review` includes alias facts, like any other fact the actor owns.
1. Import does not canonicalise names, so a backup restores exactly what was stored.
1. `factstore` is a placeholder package name.

## Next

- **Milestone 2:** date helpers (`upcoming`, `age_at`), a per-action single-valued flag so other values are implicitly false, advisory hints for actions not used before.
- **Milestone 3:** elicit the user to review stale facts, generated Markdown page per entity, scheduled backup to the NAS, extraction into its own repository.
