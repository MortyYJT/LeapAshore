# knowledge-gaps Specification

## Purpose
The advisor's refusals become knowledge gaps that an admin can review, with the asker stored only as a keyed hash, and a review can queue a re-collection of the school.
## Requirements
### Requirement: Advisor refusals are recorded as knowledge gaps

The system SHALL record every refusal of the requirement gate and the page-topic gate, every page-topic
answer left with no checkable sentence when the model's answer and the support check reported no error,
and every school a requirement answer had to leave out, as a report of a knowledge gap. Refusals with the
same route, reason, schools, areas, subject words and topics SHALL add to one gap. A failure to record
SHALL NOT change the turn. A turn ended by an unavailable model SHALL NOT be recorded.

#### Scenario: The same question twice

- **WHEN** two subjects ask about a school with no requirement data, in different words that name the
  same school and subject
- **THEN** one gap exists with two reports and two askers

#### Scenario: Recording fails

- **WHEN** writing the report raises
- **THEN** the applicant still receives the refusal and the error is logged

### Requirement: The asker is stored only as a keyed hash

A report SHALL identify its asker only by an HMAC of the subject id under a key held outside the
database; no account id, email or IP SHALL be stored with it. Deleting a subject SHALL delete its
reports; merging an anonymous subject into an account SHALL re-key its reports; reports older than the
retention period SHALL be deleted by the daily cleanup, and the gaps SHALL be kept.

#### Scenario: Account deletion

- **WHEN** a subject that reported a gap is deleted
- **THEN** its reports are gone and the gap's report count is unchanged

### Requirement: Only an admin reviews gaps, and a review can queue a re-collection

The review API SHALL answer 401 without a session, 403 for an account without the admin role and in
anonymous mode, and SHALL let an admin list gaps, read one with its recent questions, dismiss it or
queue its re-collection. Queuing a re-collection SHALL re-queue the mapped schools' pending, failed and
deferred pages and send a discovery task per school with listing URLs, on the daily collection budget;
it SHALL never re-queue a blocked page. A gap with nothing to send SHALL be refused with 409 and stay open.

#### Scenario: A reviewed gap queues the school

- **WHEN** an admin reviews a `school_not_collected` gap with `recollect`
- **THEN** the school's failed pages are queued, a discovery task is sent, and the gap is
  `recollect_queued` with what was sent

