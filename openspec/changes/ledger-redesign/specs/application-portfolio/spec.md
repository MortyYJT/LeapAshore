## ADDED Requirements

### Requirement: The portfolio is chosen from the result page

The result page SHALL let the applicant add any program to a draft portfolio. A program tiered 保底, 稳妥, or
冲刺 SHALL be added with that band (保, 稳, 冲). A program that is 不满足 or listed under 要求未收录 SHALL be added
only after the applicant picks its band, and SHALL be saved with `needsReview` set, so the row says the system
did not tier it. `/portfolio` SHALL list the draft, one row per program, with the school, the program, its band,
whether it needs review, its official deadline (or 未收录), and its application status. Saving SHALL replace the
stored portfolio with `PUT /api/applications` only after the applicant presses a confirm action that names how
many programs will be saved.

#### Scenario: Confirming saves the portfolio

- **WHEN** the applicant has four programs in the draft and presses 确认 4 个项目
- **THEN** `GET /api/applications` returns those four programs, and the roadmap is recomputed from them

#### Scenario: An untiered program is added with the applicant's band

- **WHEN** the applicant adds a 要求未收录 program and picks 冲
- **THEN** the saved row has tier 冲 and `needsReview` true, and `/portfolio` marks it as not tiered by the
  system

#### Scenario: Leaving without confirming changes nothing on the server

- **WHEN** the applicant edits the draft and closes the page without confirming
- **THEN** `GET /api/applications` returns the portfolio as it was before the edit

### Requirement: At most one first choice

The applicant SHALL be able to mark one program as 首选. Marking another program SHALL move the mark. A portfolio
of one or more programs MAY be saved without a first choice, and the page SHALL say that none is set.

#### Scenario: Moving the first choice

- **WHEN** program A is 首选 and the applicant marks program B
- **THEN** B is 首选 and A is not, before and after saving

### Requirement: Each application has a status

Each portfolio row SHALL show one status from 考虑中 (`considering`), 申请中 (`applying`), 已提交 (`submitted`),
已获 offer (`offered`), 被拒 (`rejected`), and 不考虑 (`excluded`), and the applicant SHALL be able to change it
on the row. The API SHALL accept exactly these six values and SHALL reject any other with 422. A new row SHALL
start as `considering`.

#### Scenario: Recording an offer

- **WHEN** the applicant sets a row's status to 已获 offer and saves
- **THEN** `GET /api/applications` returns that program with status `offered`

#### Scenario: An unknown status is refused

- **WHEN** a client sends `PUT /api/applications` with a status of `waitlisted`
- **THEN** the response is 422 and the stored portfolio is unchanged

### Requirement: An empty portfolio is a first step, not a blank page

With no programs, `/portfolio` SHALL keep its title and table frame and show one sentence with a link to
`/assess/result`.

#### Scenario: No programs yet

- **WHEN** an applicant with an empty portfolio opens `/portfolio`
- **THEN** the page shows the table header, a sentence saying no program is chosen yet, and a link to the
  result page
