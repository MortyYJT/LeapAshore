## ADDED Requirements

### Requirement: Official page text is stored as chunks without local paths

The system SHALL store the visible text of the official pages the committed requirement files cite as
chunks in the database, each tied to its school, its program when it is a program's own page, its URL,
its snapshot sha256 and its fetch date, and SHALL NOT store any file system path. Ingesting the same
pages again SHALL NOT write any row.

#### Scenario: A second ingest

- **WHEN** the ingest runs twice over unchanged files and snapshots
- **THEN** the second run writes no page and no chunk

#### Scenario: The collection queue re-collects a page

- **WHEN** the queue collects a page as done or unchanged at a new snapshot
- **THEN** that page's chunks are re-cut from the new snapshot, and a failure to do so leaves the
  page's collection state as it is

### Requirement: Page-topic questions are answered from checked quotes only

A question that names a school and asks about tuition, recommendation letters or an interview, routed as
a requirement or general question, SHALL be answered only from chunks of the named schools' pages. Every
sentence shown SHALL cite a passage with a quote that appears verbatim in the stored chunk and that
contains every number the sentence states; a sentence that fails SHALL be removed, and when none is
left the advisor SHALL refuse without stating any judgement.

#### Scenario: One sentence misquotes

- **WHEN** the model's answer has a sentence whose quote is not in its passage
- **THEN** that sentence is not shown and the others are

#### Scenario: Nothing checks out

- **WHEN** no sentence of the answer passes the check
- **THEN** the advisor refuses and lists the official pages it read

#### Scenario: No page states the topic

- **WHEN** none of the named school's stored pages in scope mentions the topic
- **THEN** the advisor refuses with the number of pages searched, without calling the model

#### Scenario: A named subject

- **WHEN** the question names a subject
- **THEN** only that subject's program pages and pages owned by no program are searched
