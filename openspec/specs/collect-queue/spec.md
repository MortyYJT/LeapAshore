# collect-queue Specification

## Purpose
The background collection queue: polite per-host fetching, no model call for unchanged pages, a record of requirement changes, a cap on model spend, and the rule that the queue never writes the catalogue or verification state.
## Requirements
### Requirement: Collection is polite per host

The queue SHALL take at most one request per host every 2 seconds across all workers, SHALL honour
robots.txt, and SHALL record a 401, 403 or 429 and never retry the page or ask the host again until
the refusal expires.

#### Scenario: Two workers share one host

- **WHEN** two tasks fetch pages on the same host at the same time
- **THEN** the second request starts at least 2 seconds after the first

#### Scenario: A refused page is not retried

- **WHEN** a page answers 403
- **THEN** its row is `blocked` with the reason, the task is not retried, and later pages on that host are not fetched

#### Scenario: A transient failure backs off

- **WHEN** a page times out
- **THEN** the task is retried after an exponentially growing delay, at most 4 times, then the row is `failed`

### Requirement: An unchanged page costs no model call

The queue SHALL compare a fetched page's HTML and visible-text sha256 with the last ones it knows
for that page and SHALL NOT call the model when either matches.

#### Scenario: Same snapshot

- **WHEN** a page is fetched again and its HTML is identical
- **THEN** the row is `unchanged`, no model call is made and no change is recorded

### Requirement: Requirement changes are recorded

When a page's verified values differ from its last verified values, the queue SHALL record one row
per changed field with the old value, the new value and both snapshots. Values that failed `verify`
SHALL NOT be compared or recorded.

#### Scenario: An IELTS minimum changes

- **WHEN** a page's verified IELTS overall goes from 6.5 to 7.0
- **THEN** `requirement_changes` has one `changed` row for `ielts` with both values and both sha256s

#### Scenario: A page that lost every value

- **WHEN** a re-collected page keeps no verified value but had some before
- **THEN** no `removed` rows are written and the row is `needs_human`

### Requirement: Model spend is capped

The queue SHALL check the budget before every model call and SHALL NOT call the model once the
budget's spend reaches its cap.

#### Scenario: Budget reached

- **WHEN** the spend recorded for the budget is at or above its cap
- **THEN** the page is `deferred` and the model is not called

### Requirement: The queue never writes the catalogue or verification

The queue SHALL NOT write `programs`, `sources` or `verified_at`; its results reach the catalogue
only through requirement files and the importer.

#### Scenario: Export writes a requirement file

- **WHEN** `export` runs after pages were collected
- **THEN** each school's file holds the collected programs, replaced by URL, and no `verified_at`

