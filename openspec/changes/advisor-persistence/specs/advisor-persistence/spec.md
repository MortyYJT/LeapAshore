## ADDED Requirements

### Requirement: A paused portfolio change survives a restart

The advisor SHALL keep every conversation, including a portfolio change waiting for the applicant's
confirm, in PostgreSQL, so that the change can be confirmed after the API process has restarted.

#### Scenario: Confirm after a restart

- **WHEN** a turn is waiting for a confirm, the API restarts, and the applicant then confirms
- **THEN** the change is written once and the advisor replies that it was done

#### Scenario: The process is killed while the turn waits

- **WHEN** the process holding a paused turn is killed with SIGKILL and a new process resumes it
- **THEN** the change is written once, and resuming again finds nothing pending and writes nothing

### Requirement: A confirmed change is written exactly once

A portfolio change SHALL be written at most once however many times, and from however many tabs, it
is confirmed.

#### Scenario: Two confirms at the same time

- **WHEN** two confirms for the same change arrive together
- **THEN** one resumes the turn and writes the change, and the other is told the change is being
  handled or that nothing is pending

#### Scenario: A late repeat of an answered confirm

- **WHEN** a confirm names a change that is no longer the pending one
- **THEN** nothing is resumed and nothing is written

### Requirement: Conversations belong to their subject

A conversation SHALL be reachable only by the subject that started it, and SHALL be deleted with it.

#### Scenario: Another subject answers someone's change

- **WHEN** a different subject sends a confirm with the same conversation id
- **THEN** nothing is pending for it, nothing is written, and the owner can still confirm

#### Scenario: Account deletion

- **WHEN** a subject is deleted (account deletion or the 90-day anonymous sweep)
- **THEN** its conversations are deleted in the same transaction, and no other subject's

#### Scenario: Anonymous data merged at first login

- **WHEN** an anonymous subject is merged into an account
- **THEN** its conversations move to the account, except a conversation id the account already has

#### Scenario: Idle conversations

- **WHEN** a conversation has not been used for 90 days
- **THEN** the daily sweep deletes it, in anonymous mode as well as in login mode
