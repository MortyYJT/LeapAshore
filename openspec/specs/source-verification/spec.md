# source-verification Specification

## Purpose
Manual verification of official pages: only an admin can confirm a page after reading it, and nothing else can set the verification date.
## Requirements
### Requirement: Only an admin confirms a page, after reading it

The system SHALL let an account with the admin role read, for a page that backs imported programs, each
program's stored values with their quotes and the page's snapshot text, and confirm it. Confirming SHALL
set `sources.verified_at` and `status = 已核验` and record the account and moment. It SHALL be refused
when the page's latest version is not the snapshot the admin read, when that snapshot has no text, or
when the page is already verified. Every admin request SHALL answer 401 without a session and 403 for
any other account and in anonymous mode; the web page SHALL answer 404 to them.

#### Scenario: An admin confirms

- **WHEN** an admin confirms a page with the sha of its latest version
- **THEN** the page is 已核验 with a date, and the history names the admin and the moment

#### Scenario: The page changed while the admin read it

- **WHEN** an admin confirms with a sha that is not the latest version's
- **THEN** the request is refused with 409 and the page stays 待核验

### Requirement: Nothing else can set the verification date

A non-null `sources.verified_at` SHALL be accepted by the database only in a transaction that recorded
an admin's confirmation for that page and moment. A static check SHALL fail when any code other than the
allow-listed writers writes a `verified_at` column.

#### Scenario: An importer or script sets the date

- **WHEN** any statement sets `sources.verified_at` to a value without a matching confirmation by an admin
- **THEN** the database refuses the statement

#### Scenario: Clearing is allowed

- **WHEN** the importer sees new content on a verified page and sets `verified_at` to NULL
- **THEN** the database accepts it and the page is 待核验

