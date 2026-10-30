# advisor-retrieval Specification

## Purpose
How the advisor finds programs: schools recognised by every common spelling, subjects mapped to study areas, refusals worded from what the catalogue holds, and filtering done in SQL.
## Requirements
### Requirement: Schools are recognised by every common spelling

The evidence gate SHALL recognise a school named by its stored Chinese name in simplified or traditional
characters, its English name, the abbreviation in its English name's parentheses, or a short form listed
in `api/data/advisor/university_aliases.json`. Recognition SHALL NOT depend on code that names a school.

#### Scenario: Short form

- **WHEN** an applicant asks 帝国理工计算机硕士的语言要求
- **THEN** the evidence comes from Imperial College London

#### Scenario: Simplified for a traditional name

- **WHEN** an applicant asks 香港大学计算机科学硕士申请要求 and the school is stored as 香港大學
- **THEN** the evidence comes from that school

### Requirement: Subjects select the program's study area

A question that names a subject SHALL only receive evidence from programs whose `Program.field` is that
subject's area.

#### Scenario: Computing at Imperial

- **WHEN** an applicant asks 帝国理工学院计算机
- **THEN** every evidence row is in 计算机与数据, computing-named programs first

### Requirement: Refusals are worded from the catalogue

A refused question SHALL be told why in terms of the catalogue's own counts (schools and programs held,
the named school's collected programs, the named subject), never from a fixed list of schools.

#### Scenario: Uncollected school

- **WHEN** an applicant asks about a school the catalogue does not hold
- **THEN** the reply states how many schools have collected requirements and asks for a full or common name

### Requirement: Retrieval is filtered in SQL

The gate SHALL read at most K program rows per named school and SHALL NOT load the catalogue into the
application. K SHALL equal the number of rows handed to the model.

#### Scenario: Bounded rows

- **WHEN** a question names one school
- **THEN** the rows returned by the database are the universities table plus at most a few times K

