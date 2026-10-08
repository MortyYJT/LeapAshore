# document-review Specification

## Purpose
TBD - created by archiving change stage-2-m3-document-library. Update Purpose after archive.
## Requirements
### Requirement: A review names the exact version it judged

Every `document_reviews` row SHALL name both the document and the version it reviewed, and `version_id` SHALL NOT be null. A review SHALL only be recorded against the document's current version: if a new version arrived while the review was being prepared, the write SHALL be refused with 409 rather than stored against bytes it did not judge.

#### Scenario: A review is stored against the current version

- **WHEN** the operator reviews a document whose current version is 2
- **THEN** the stored review names version 2

#### Scenario: A review of a superseded version is refused

- **WHEN** the operator reviews version 1 of a document whose current version is 2
- **THEN** the write is refused with 409 and no review is stored

### Requirement: Every finding cites a review criterion

`document_review_findings.criterion_id` SHALL NOT be null, enforced in the database, and a criterion that findings cite SHALL NOT be deletable while those findings exist. A review may carry no findings; it may not carry a finding that cites nothing. A finding's `evidence_quote` SHALL be null when it quotes nothing, never an empty string: a quote nobody took is unknown, not empty.

#### Scenario: A finding with no criterion cannot be stored

- **WHEN** a finding is inserted with no `criterion_id`
- **THEN** the database raises an integrity error and no row is stored

#### Scenario: A cited criterion cannot be deleted from under a finding

- **WHEN** something tries to delete a criterion that findings cite
- **THEN** the database refuses the delete and the finding survives

#### Scenario: A review with no findings is allowed

- **WHEN** the operator records a passing review with nothing to flag
- **THEN** the review is stored with no findings

#### Scenario: A finding that quotes nothing reports no quote

- **WHEN** the operator records a finding without quoting the material
- **THEN** the stored finding's quote is null rather than an empty string

### Requirement: A finding's criterion must apply to the material it judges

A finding SHALL only cite a criterion whose `scope` is `general` or equals the reviewed document's `kind`. A mismatch SHALL be refused rather than stored, so that a conclusion about one kind of material can never be justified by a requirement read from another.

#### Scenario: A general criterion applies to any material

- **WHEN** a finding cites a `general` criterion for a document archived as `cv`
- **THEN** the finding is stored

#### Scenario: A criterion for another kind of material is refused

- **WHEN** a finding cites a `gs` criterion for a document archived as `transcript`
- **THEN** the write is refused and no review is stored

### Requirement: A review cannot contradict itself

A review whose overall verdict is `pass` SHALL NOT carry a finding whose severity is `blocker`, and a review whose overall verdict is not `pass` SHALL carry at least one finding. Both SHALL be refused with a mapped error rather than stored, because a passing verdict over a blocker and a "needs revision" with nothing named are conclusions the applicant cannot act on.

#### Scenario: A pass with a blocker is refused

- **WHEN** the operator records `pass` together with a `blocker` finding
- **THEN** the write is refused and no review is stored

#### Scenario: A failing verdict with no findings is refused

- **WHEN** the operator records `needs_revision` with no findings
- **THEN** the write is refused and no review is stored

#### Scenario: Severity is one of the three defined levels

- **WHEN** a finding is recorded with a severity outside `info`, `warning`, `blocker`
- **THEN** the write is refused

### Requirement: Recording a review moves the material's state

Recording a review SHALL set the document's status from the overall verdict in the same transaction: `pass` sets `accepted`, `needs_revision` sets `needs_revision`, and `insufficient_evidence` leaves the document `under_review` because the review reached no conclusion. A review SHALL only be recorded for a document that is `under_review`.

#### Scenario: A passing review accepts the material

- **WHEN** the operator records `pass` for a document that is `under_review`
- **THEN** the document becomes `accepted`

#### Scenario: An inconclusive review leaves the material under review

- **WHEN** the operator records `insufficient_evidence`
- **THEN** the document is still `under_review` and the review is stored

#### Scenario: A review of a document that was not submitted is refused

- **WHEN** the operator records a review for a document that is `archived`
- **THEN** the write is refused with 409

### Requirement: A review says who made it

Every review SHALL carry a non-empty `reviewed_by`, supplied at the time it is recorded. A review with no attribution SHALL be refused.

#### Scenario: A review without an attribution is refused

- **WHEN** a review is recorded with an empty `reviewed_by`
- **THEN** the write is refused and no review is stored

### Requirement: The owner can read the reviews of their own document

The document detail response SHALL carry the document's reviews, each with its overall verdict, summary, attribution, time, and its findings; each finding SHALL carry its severity, its text, the quoted evidence if any, and the criterion it cites together with that criterion's official source. Another subject's review SHALL be reported as absent.

#### Scenario: A finding is served with its criterion and source

- **WHEN** the owner reads a document that has a review with findings
- **THEN** each finding carries the criterion's code and title and the URL of the page that criterion cites

#### Scenario: Another subject's review is absent

- **WHEN** a request presents subject A's cookie and asks for a document owned by subject B
- **THEN** the response is 404

### Requirement: Reviews are recorded by a human operator, not over HTTP in this change

No HTTP route in this change SHALL create, edit, or delete a review: `/api/documents/{id}/reviews` SHALL offer `GET` and answer every other method with 405. Recording a review SHALL be an operator command run against the same database.

#### Scenario: An HTTP write to the review routes is refused

- **WHEN** a caller sends `POST` to `/api/documents/{id}/reviews`
- **THEN** the response is 405 and no review is stored

#### Scenario: The operator command records a complete review

- **WHEN** the operator records a verdict, an attribution, a summary, and one finding citing a criterion code
- **THEN** the review and its finding are stored together, and the material's status follows the verdict
