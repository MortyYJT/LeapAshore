## ADDED Requirements

### Requirement: The backend catalog holds every CRICOS master's program

A seed SHALL write one `programs` row for each course in the CRICOS master's (coursework) extract, with the id
`cricos-<course code>`, linked to a `universities` row per CRICOS provider and to a `sources` row citing the
CRICOS dataset. Running the seed twice SHALL leave the same rows. The table structure SHALL NOT change.

#### Scenario: Every extract course has a row

- **WHEN** the seed has run against the extract
- **THEN** the number of `cricos-` rows equals the number of courses in the extract, and each row's university
  matches its course's provider

#### Scenario: The seed is idempotent

- **WHEN** the seed runs a second time
- **THEN** no row is added, removed, or changed

### Requirement: Unknown requirements stay unknown

A seeded program SHALL have no minimum mark, no non-211 minimum mark, no prerequisites, and no English
requirement unless an official source for that value is recorded, and its data status SHALL be `待核验`. The
seed SHALL NOT set `verified_at`. The interface SHALL show a missing requirement as `未收录`, never as an empty
string or a zero. A program page SHALL name its missing requirements once, on a single `未收录` line, rather
than one `未收录` row each. Only the stored status `已核验` is marked (`已核对`); `待核验` and `机器核对` carry no
label (changed 2026-10-31; PRD §7.7 rule 5 still keeps stored values off the screen).

#### Scenario: A course with no collected requirements

- **WHEN** the applicant opens `/programs/0100139`
- **THEN** the 未收录 line names the minimum mark and the English requirement, and the site footer cites the
  CRICOS dataset for the facts the page does show

### Requirement: The placeholder programs fold into their CRICOS rows

Each of the six former placeholder programs SHALL be matched to its CRICOS course, and its collected
requirements and official source SHALL move onto that course's row, still `待核验`. A placeholder with no
matching course SHALL be dropped with its requirements. No row with a placeholder slug SHALL remain.
`applications` rows that pointed at a placeholder SHALL point at the matching row, or be removed when there is
none.

#### Scenario: A matched placeholder keeps its requirement

- **WHEN** the fold has run and the Monash Master of Artificial Intelligence course exists in the extract
- **THEN** that course's row carries the former placeholder's minimum mark and official page, with data status
  `待核验`, and no `monash-master-ai` row exists

#### Scenario: A portfolio survives the fold

- **WHEN** an applicant had chosen `monash-master-ai` before the fold
- **THEN** after it their portfolio holds the matching `cricos-` program with the same first-choice mark and
  status

### Requirement: The catalog API can be filtered

`GET /api/programs` SHALL accept `ids` (a comma-separated list), `field`, `provider`, and `has_requirements`
filters and a `limit` with an `offset`, and SHALL return at most 100 programs per response.

#### Scenario: Reading the programs in a portfolio

- **WHEN** the client requests `/api/programs?ids=cricos-0100139,cricos-001396M`
- **THEN** exactly those two programs are returned

#### Scenario: A page is capped

- **WHEN** the client requests `/api/programs` with no limit
- **THEN** at most 100 programs are returned
