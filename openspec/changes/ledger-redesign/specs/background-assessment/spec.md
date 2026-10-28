## ADDED Requirements

### Requirement: The assessment is one page backed by the server profile

`/assess` SHALL be a single page holding the ten questions of the former onboarding: current education level,
where the school is, the school, the major, the average mark with its scale, the target degree, the target
field, the English score, the annual budget, and the intake. On open it SHALL fill every field from
`GET /api/profile`; on submit it SHALL write the fields with `PATCH /api/profile` and only then go to
`/assess/result`. The page SHALL NOT read or write the background in `sessionStorage` or `localStorage`.

#### Scenario: The form opens with the saved profile

- **WHEN** an applicant whose profile holds a major of 软件工程 and an intake of 2027 S1 opens `/assess`
- **THEN** the major and intake fields show those values

#### Scenario: Submitting saves before moving on

- **WHEN** the applicant submits the form and the `PATCH` succeeds
- **THEN** the browser goes to `/assess/result`, and a fresh `GET /api/profile` returns the submitted values

#### Scenario: A failed save keeps the applicant on the form

- **WHEN** the `PATCH` fails
- **THEN** the page stays on `/assess`, keeps every value entered, and says in one sentence that the
  background was not saved

### Requirement: Required fields decide whether an assessment is complete

The education level, school origin, major, average mark and scale, target degree, target field, English score,
and intake SHALL be required to submit. The school name and the annual budget MAY be left empty. An assessment
SHALL count as complete exactly when the server profile holds every required field.

#### Scenario: A missing required field blocks submission

- **WHEN** the applicant submits without an intake
- **THEN** the form is not sent, and the intake field is marked as required with its reason beside it

#### Scenario: An undisclosed school is allowed and stays unknown

- **WHEN** the applicant leaves the school name empty and submits
- **THEN** the profile is saved with no school name, and the result page treats the institution tier as unknown
  rather than as any tier

### Requirement: The school is chosen from the official list

The school field SHALL search the Ministry of Education list of 3,167 institutions for mainland schools and
SHALL set the 985 / 211 / 双一流 tags from that list, citing it beside the field. A school not on the list SHALL
be accepted as typed, with its tier recorded as unknown.

#### Scenario: Choosing a listed school sets its tier

- **WHEN** the applicant picks 北京邮电大学 from the search
- **THEN** the saved profile records the school and the 211 tier, and the page cites the Ministry list

#### Scenario: An unlisted school has an unknown tier

- **WHEN** the applicant types a school name the list does not contain
- **THEN** the profile records the name and no tier, and nothing on the page labels it 985, 211, or 双一流
