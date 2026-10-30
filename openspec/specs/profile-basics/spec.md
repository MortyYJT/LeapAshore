# profile-basics Specification

## Purpose
The four facts tiering needs (undergraduate school, average mark, study area, English score), asked after the first registration and skippable, and the tiers page asking for them when missing.
## Requirements
### Requirement: Four facts after the first registration, skippable

After an account is created the login dialog SHALL ask for the undergraduate school, the average mark with
its scale, the target field, and the English score, unless the profile already holds all four. The step SHALL
offer 跳过. Every other profile field SHALL be editable on `/me`.

#### Scenario: Info step then the original action

- **WHEN** a logged-out visitor types a question in the advisor, presses 发送, registers, fills the four facts
- **THEN** the dialog closes and the advisor sends the question that was typed

### Requirement: The tiers page asks a skipped user for the basics

`/tiers` SHALL tier programs when the four facts are present. Otherwise it SHALL show 先补信息 with the same
four-field form. `/assess` and `/assess/result` SHALL redirect to `/tiers`.

#### Scenario: Skipped user

- **WHEN** a user who skipped the info step opens `/tiers`
- **THEN** the page shows 先补信息 and no tier list

