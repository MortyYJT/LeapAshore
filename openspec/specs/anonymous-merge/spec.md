# anonymous-merge Specification

## Purpose
At first sign-in a browser's anonymous data moves into the account without overwriting the account's own, and anonymous data nobody claims is deleted after 90 days.
## Requirements
### Requirement: The first login of a browser claims its anonymous data

When a browser holding an anonymous subject logs in, its profile, portfolio, roadmap tasks, materials and
history SHALL become the account's. Data the account already has SHALL NOT be overwritten.

#### Scenario: New account claims the anonymous subject

- **WHEN** a browser with an anonymous profile, two portfolio rows and one material registers
- **THEN** the account sees that profile, both rows and the material

#### Scenario: Existing account keeps its profile

- **WHEN** an account with a filled profile logs in from a browser whose anonymous profile differs
- **THEN** the account's profile is unchanged

#### Scenario: Existing empty profile takes the anonymous one

- **WHEN** the account's profile has no answered field
- **THEN** it takes every field of the anonymous profile

#### Scenario: Portfolio rows merge without duplicates

- **WHEN** the account holds program P as 冲 and the anonymous portfolio holds P as 保 and Q as 稳
- **THEN** the account holds P as 冲 and Q as 稳, and at most one first choice

#### Scenario: Materials always move, and their task links survive

- **WHEN** the anonymous subject has a material attached to a roadmap task the account also has
- **THEN** the material belongs to the account and points at the account's task

#### Scenario: The anonymous subject is gone after the merge

- **WHEN** the merge finishes
- **THEN** the anonymous client row no longer exists and the anonymous cookie is cleared

### Requirement: Unclaimed anonymous data is deleted after 90 days

`python -m app.cleanup --apply` SHALL delete every anonymous subject (no account) whose last activity is more
than 90 days old, with its uploaded files that nothing else references. Without `--apply` it SHALL only report.

#### Scenario: Old anonymous data is swept

- **WHEN** an anonymous subject was last seen 91 days ago and another 10 days ago
- **THEN** the first is deleted and the second is kept, and no account's subject is touched

