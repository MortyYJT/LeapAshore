# privacy-policy Specification

## Purpose
A public privacy policy page, and deleting an account deletes everything it owns.
## Requirements
### Requirement: A privacy policy page is public

`/privacy` SHALL state what is collected (email, profile, portfolio, materials, advisor messages, IP for rate
limits), why, where it is processed (including the model provider and the mail provider), how long it is kept,
and how to delete it. It SHALL be marked as a draft until MortyYJT reviews it. The login dialog SHALL link it.

#### Scenario: The policy is reachable without login

- **WHEN** a logged-out visitor opens `/privacy`
- **THEN** the page renders the policy and says it is a draft awaiting review

### Requirement: Deleting the account deletes everything it owns

`DELETE /api/auth/account` with the account's email as confirmation SHALL delete the account, its sessions,
its login codes, its subject and every row the subject owns, and every uploaded file no other material
references, then clear the cookies.

#### Scenario: Deletion is complete

- **WHEN** an account with a profile, portfolio, tasks and an uploaded material is deleted
- **THEN** no row in any table references its subject or email, the blob is gone from storage, and the old
  session cookie answers 401

#### Scenario: A shared blob survives

- **WHEN** another subject uploaded the same file bytes
- **THEN** that subject's file is still on disk

