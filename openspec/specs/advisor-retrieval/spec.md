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

### Requirement: Rows inside the named schools are ordered by full text and vectors

The advisor SHALL order the evidence rows inside each named school by Reciprocal Rank Fusion of a
PostgreSQL full-text ranking over the program's names and a cosine-distance ranking against the
question's embedding, and SHALL fall back to the full-text ranking alone when no question embedding is
available. The ranking SHALL NOT change which rows may be evidence.

#### Scenario: The applicant names a program in English

- **WHEN** a requirement question names a school and a word that appears in one program's name ("哥大 TESOL")
- **THEN** that program is the first evidence row

#### Scenario: Embeddings are unavailable

- **WHEN** no embedding key is configured or the embedding service fails
- **THEN** the question is answered with rows ranked by full text, nothing is sent to the service when no
  key is set, and the trace records the ranking used

### Requirement: A country narrows the named schools

A country or region in a requirement question SHALL narrow a school name that several schools share to
the schools in that country, SHALL NOT drop a school named without ambiguity, and SHALL NOT by itself
make a question answerable.

#### Scenario: Two schools share a name

- **WHEN** the question names a school whose name two schools in different countries share, and one country
- **THEN** only the school in that country is searched

#### Scenario: A country beside an unambiguous school

- **WHEN** the question mentions a country and names a school that is not in it and shares its name with no other
- **THEN** that school is still searched

#### Scenario: Only a country is named

- **WHEN** the question names a country and a subject but no school
- **THEN** the gate refuses it as naming no school

### Requirement: Program embeddings stay current without re-sending unchanged programs

The system SHALL store each program's embedding with its model and a hash of the embedded text, SHALL
embed only programs whose embedding is missing or stale, and SHALL keep what one run stored when a later
batch fails.

#### Scenario: A second run over an unchanged catalogue

- **WHEN** the backfill runs twice and no program changed
- **THEN** the second run sends nothing

#### Scenario: The service fails halfway

- **WHEN** the service fails after some batches were stored
- **THEN** those batches stay stored and the next run embeds only the rest

