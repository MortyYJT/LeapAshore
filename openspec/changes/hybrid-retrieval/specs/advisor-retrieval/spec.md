## ADDED Requirements

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
