# requirement-dates Specification

## Purpose
Importing collected deadlines and academic requirements: entered deadlines are never overwritten, past deadlines are labelled rather than scheduled, and one rule decides whether a program states a requirement.
## Requirements
### Requirement: Collected deadlines and academic requirements are imported

The importer SHALL store every deadline and academic requirement whose quote passed `verify`, and
SHALL store nothing for one that did not. It SHALL NOT write `verified_at`.

#### Scenario: Rerunning the import changes nothing

- **WHEN** the importer runs twice over the same files
- **THEN** the second run adds, removes and updates no deadline, program or source row

#### Scenario: A failed deadline is not stored

- **WHEN** a deadline's check is not `ok`
- **THEN** the program has no deadline row for it

### Requirement: An entered deadline is never overwritten

The import SHALL NOT write `applications` or `roadmap_tasks`. A portfolio row's own deadline SHALL be
shown in place of the program's collected one.

#### Scenario: The applicant's date wins

- **WHEN** a portfolio row has its own deadline and source and the program has collected deadlines
- **THEN** the roadmap shows the row's own deadline

### Requirement: Past deadlines are labelled, not scheduled

A deadline before today's Beijing date SHALL be labelled 已截止 and SHALL NOT be drawn as a timeline
milestone.

#### Scenario: Every collected deadline has passed

- **WHEN** all of a portfolio program's collected deadlines are before today
- **THEN** the roadmap lists the latest one as 已截止 and draws no mark for it

#### Scenario: The next round is chosen

- **WHEN** a program has a past round and a future round
- **THEN** the roadmap draws the future round, solid, linked to its source page

### Requirement: One rule for "states a requirement"

A program SHALL count as stating a requirement when it has an English line, a mark, a prerequisite,
an academic requirement or a deadline, in every count and in the frontend badge.

#### Scenario: A deadline-only program counts

- **WHEN** a program has only a collected deadline
- **THEN** the catalogue filter, the school count, the advisor gate and the program badge all count it

