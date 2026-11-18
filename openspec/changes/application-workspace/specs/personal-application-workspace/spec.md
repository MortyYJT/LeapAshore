## ADDED Requirements

### Requirement: Scoped personal applications
The system SHALL combine saved catalogue selections with manually entered applications without replacing existing selection APIs. Every read and write MUST be scoped to the authenticated or anonymous applicant.

#### Scenario: Manual project persists
- **WHEN** an applicant adds a school and project not in the catalogue
- **THEN** the project persists after reload and another applicant cannot read, modify or delete it

#### Scenario: Legacy portfolio remains usable
- **WHEN** a saved catalogue selection exists
- **THEN** it appears in the personal workspace and normal selection confirmation remains operational

### Requirement: Honest deadline and material state
The system SHALL support round, date, source, status and self-reported material readiness. Unknown dates MUST remain unknown. Explicit confirmation MUST require a date and valid HTTP(S) source; editing date, source or round MUST invalidate prior confirmation unless reconfirmed by the applicant.

#### Scenario: User-entered date without source
- **WHEN** an applicant records a date without a source
- **THEN** the date is saved as unconfirmed and no official verification claim is made

#### Scenario: Confirmation becomes stale
- **WHEN** a confirmed date or its round/source changes
- **THEN** its previous check timestamp is cleared

### Requirement: Actionable homepage and truthful documentation
The homepage SHALL display persisted application attention items and editable roadmap tasks, with a first-project empty state and contextual advisor entry. README and PRD MUST describe the application-management focus and use current actual screenshots, with demonstration accounts labelled.

#### Scenario: Returning applicant
- **WHEN** an applicant has saved applications
- **THEN** active dated applications are ordered by deadline and unknown dates are separately identified for confirmation

#### Scenario: First visit
- **WHEN** an applicant has no applications
- **THEN** the homepage offers adding a project without invented metrics or example applicant data
