## ADDED Requirements

### Requirement: A review criterion must cite an official source

A `review_criteria` row SHALL NOT be storable without a `source_id`, and the constraint SHALL live in the database, not in the seed or the service layer. A source that a criterion cites SHALL NOT be deletable while that criterion exists.

#### Scenario: A criterion with no source is refused by the database

- **WHEN** a criterion is inserted with no `source_id`
- **THEN** the database raises an integrity error and no row is stored

#### Scenario: A cited source cannot be deleted out from under a criterion

- **WHEN** something tries to delete a source that a criterion cites
- **THEN** the database refuses the delete and both rows survive

### Requirement: A criterion's verification state is set by a human and is never defaulted

A criterion SHALL start as `待核验` with `verified_at` unset. Only the operator command SHALL move it to `已核验`, and that command SHALL stamp the current time rather than any written-out date. No HTTP route in this change SHALL create, modify, verify, or delete a criterion, and `/api/review-criteria` SHALL answer every method other than `GET` with 405.

#### Scenario: Seeded criteria are unverified

- **WHEN** the criteria are seeded and then read back
- **THEN** every one reports `待核验` and a null verification date

#### Scenario: No HTTP route can change a criterion

- **WHEN** a caller sends `POST`, `PUT`, `PATCH`, or `DELETE` to `/api/review-criteria`
- **THEN** the response is 405 and no criterion is changed

#### Scenario: The operator command verifies a criterion

- **WHEN** the operator verifies a criterion by its code
- **THEN** it becomes `已核验` and carries the time the command ran

#### Scenario: The operator command can take a verification back

- **WHEN** the operator un-verifies a criterion
- **THEN** it returns to `待核验` and its verification date is cleared

### Requirement: The seeded criteria trace to the Genuine Student requirement page

The seed SHALL write the transcribed Genuine Student criteria, each citing the same official Department of Home Affairs page that the visa materials already cite. The seed SHALL NOT write a verification date, and SHALL NOT write a criterion whose text the source does not support.

#### Scenario: Every seeded criterion cites the official page

- **WHEN** the seeded criteria are read with their sources
- **THEN** each one cites the Genuine Student requirement page

#### Scenario: The word limit is machine-checkable

- **WHEN** the seeded criterion for the answer length is read
- **THEN** its check type is the length check and its rule states a maximum of 150 words

#### Scenario: The seed is repeatable

- **WHEN** the seed runs twice
- **THEN** the criteria are the same rows, with no duplicates

### Requirement: A criterion states only what it can be checked against

Each criterion SHALL carry a `code` unique across criteria, a `scope` from `gs`, `transcript`, `cv`, `ps`, `recommendation`, `language`, `general`; a `check_type` from `presence`, `length`, `language`, `evidence`, `consistency`; and a `rule` that is either a machine-checkable object or `null`. A criterion with no machine-checkable rule SHALL serve `null` rather than an empty object.

#### Scenario: A criterion with no machine-checkable rule serves null

- **WHEN** a criterion that can only be judged by a human is read
- **THEN** its rule is `null`

#### Scenario: A check type outside the defined set cannot be stored

- **WHEN** a criterion row is inserted with a `check_type` outside the five defined values, or a `scope` outside the seven
- **THEN** the database refuses the row and nothing is stored

### Requirement: Criteria are readable with the page they came from

`GET /api/review-criteria` SHALL serve the criteria with their code, scope, title, description, check type, rule, status, and the source each one cites, including that source's URL, title, and status. Reading the criteria SHALL NOT require a subject cookie, because the criteria are shared configuration rather than anyone's data.

#### Scenario: Reading the criteria returns each one's source

- **WHEN** a caller reads the criteria
- **THEN** each entry carries its source's URL and verification status

#### Scenario: The criteria are the same for every caller

- **WHEN** two callers with different cookies read the criteria
- **THEN** both receive the same list
