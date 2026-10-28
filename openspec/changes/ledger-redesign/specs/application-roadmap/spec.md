## ADDED Requirements

### Requirement: The roadmap is dated backwards from the applicant's intake

`/roadmap` SHALL draw every phase returned by `GET /api/roadmap`, in order, each with a suggested start date
counted back from the intake in the server profile by the phase's offset. When the profile has no intake the
page SHALL NOT assume one: it SHALL show the phases undated and ask for the intake with a link to `/assess`.

#### Scenario: An intake dates every phase

- **WHEN** the profile's intake is 2027 S1 and a phase's offset is 330 days
- **THEN** that phase's suggested start is 330 days before the 2027 S1 anchor date

#### Scenario: No intake, no invented dates

- **WHEN** the profile has no intake
- **THEN** no phase shows a date, and the page asks for the intake with a link to `/assess`

### Requirement: Three kinds of date are drawn three ways

The roadmap SHALL show a time axis from today to the intake. A date the system suggested SHALL be drawn as a
dashed mark and labelled 系统建议 · 非官方日期. An official deadline with a recorded source SHALL be drawn as a
solid mark, labelled with its date and linked to its source. A deadline that is expected but not recorded SHALL be
drawn as a hollow mark labelled 未收录, with a link to the program's official page. A legend SHALL show
each mark that appears on screen, drawn the same way as on the axis.

#### Scenario: A suggested date is never shown as official

- **WHEN** a phase has only a system-suggested date
- **THEN** its mark is dashed, its label includes 非官方, and no solid mark appears for it

#### Scenario: An official deadline links to its source

- **WHEN** a portfolio program has an official deadline of 2026-12-15 with a source URL
- **THEN** a solid mark at 2026-12-15 names the program and links to the source

#### Scenario: An unrecorded deadline stays unknown

- **WHEN** a portfolio program has no official deadline
- **THEN** the axis shows a hollow mark labelled 未收录 for it, and no date is printed for it

### Requirement: Today and the current phase are the only coloured marks

Inside the timeline, the today line and the current phase SHALL be the only elements drawn in the accent. The current phase SHALL
be the earliest phase with an unticked task. An overdue phase SHALL carry one small mark in the negative colour
and the words 已过建议时间, without filling the phase in that colour.

#### Scenario: The current phase follows the ticks

- **WHEN** every task in the first phase is ticked and the second phase has an unticked task
- **THEN** the second phase is drawn as current

### Requirement: A phase opens to its tasks

Selecting a phase SHALL show its tasks with a tick box each, the phase's suggested start, the official deadline
or 未收录, and the source of each requirement. Ticking a task SHALL save it with `PATCH /api/roadmap/tasks/{id}`,
and the phase's progress SHALL update from the server's answer. A task row SHALL offer uploading a file, which
attaches the document to that task (as the `document-library` spec requires).

#### Scenario: A tick survives a reload

- **WHEN** the applicant ticks a task and reloads the page
- **THEN** the task is still ticked and the phase progress counts it

#### Scenario: A failed tick is undone visibly

- **WHEN** the `PATCH` for a tick fails
- **THEN** the box returns to unticked, and the row says the change was not saved
