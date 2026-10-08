## ADDED Requirements

### Requirement: A document belongs to exactly one subject

Every `documents` row SHALL be scoped to one `clients` row, and every route that reads, writes, or serves a file SHALL address the calling subject's own rows. A document that belongs to another subject SHALL be reported as absent rather than as forbidden, so that a caller cannot learn which document ids exist.

#### Scenario: Listing returns only the caller's documents

- **WHEN** two subjects have each uploaded a document and one of them requests the library
- **THEN** the response contains that subject's document only

#### Scenario: Reading another subject's document

- **WHEN** a request presents subject A's cookie and asks for a document id owned by subject B
- **THEN** the response is 404 and no document data is returned

#### Scenario: Downloading another subject's file

- **WHEN** a request presents subject A's cookie and asks for the file of a version owned by subject B
- **THEN** the response is 404 and no bytes are served

#### Scenario: Attaching a document to another subject's requirement

- **WHEN** an upload for subject A names a task that belongs to subject B
- **THEN** the response is 422 and no document is created

### Requirement: Every document has at least one immutable version

An upload SHALL create the document together with its first version, or append a new version to a document the caller already owns. `version_no` SHALL start at 1 and increase by exactly one per document, enforced by a unique constraint on `(document_id, version_no)`. An existing version SHALL never be modified in place.

#### Scenario: First upload creates the document and its first version

- **WHEN** a subject uploads a file with no existing document
- **THEN** one document row and one version row with `version_no = 1` are stored, and the document's current version is that version

#### Scenario: A second upload appends a version

- **WHEN** the subject uploads another file to that document
- **THEN** a version with `version_no = 2` is stored and the document's current version becomes it

#### Scenario: A document's title defaults to the uploaded filename

- **WHEN** a caller uploads a file without naming the document
- **THEN** the document's title is the filename the upload carried

#### Scenario: Two uploads racing for the next version number

- **WHEN** two uploads for the same document compute the same next version number and one of them loses the unique constraint
- **THEN** the loser is retried once and, if it still cannot be stored, answered with 409 rather than 500

### Requirement: An upload is bounded in size

A single uploaded file SHALL be at most 20 MiB. A request that declares a content length above the limit SHALL be refused with 413 before its body is read, and the bytes actually written SHALL be counted as they are copied so that a body which exceeds the limit is aborted partway. Either way the refusal SHALL leave no document row, no version row, and no file under the storage root. An upload with no bytes SHALL be refused with 422.

#### Scenario: An oversized upload is refused and leaves nothing behind

- **WHEN** a caller uploads more than 20 MiB
- **THEN** the response is 413, no document or version row is created, and no new file exists under the storage root

#### Scenario: An oversized body that declares itself small is aborted

- **WHEN** a caller streams more than 20 MiB while declaring a smaller content length
- **THEN** the copy is aborted at the limit, the response is 413, and no file remains under the storage root

#### Scenario: An empty upload is refused

- **WHEN** a caller uploads a file with zero bytes
- **THEN** the response is 422

### Requirement: An upload's type is decided by its bytes, not by the caller's claim

The system SHALL accept only PDF, PNG, JPEG, and DOCX. The type SHALL be determined from the file's own signature, and the detected type SHALL be what is stored and later served; the `Content-Type` the caller declared SHALL NOT be trusted for either purpose. A DOCX SHALL additionally be a ZIP archive containing `word/document.xml`. Anything else SHALL be refused with 415.

#### Scenario: A text file renamed to look like a PDF is refused

- **WHEN** a caller uploads a text file with the declared type `application/pdf`
- **THEN** the response is 415 and nothing is stored

#### Scenario: A ZIP that is not a Word document is refused

- **WHEN** a caller uploads a ZIP archive that does not contain `word/document.xml`
- **THEN** the response is 415 and nothing is stored

#### Scenario: The stored type is the detected one

- **WHEN** a caller uploads a real PNG while declaring `application/octet-stream`
- **THEN** the version row records `image/png`

### Requirement: Identical bytes are stored once

The file content SHALL be addressed by its SHA-256 digest. When the same bytes are uploaded again — to the same document or to a different one, for the same subject or another — the stored file SHALL be reused rather than written a second time. Sharing bytes between subjects SHALL NOT make one subject's file reachable from another subject.

#### Scenario: Uploading the same bytes twice leaves one file on disk

- **WHEN** the same bytes are uploaded as two versions
- **THEN** both version rows carry the same `storage_path` and exactly one file exists under the storage root for that digest

#### Scenario: Deleting nothing keeps a shared file alive

- **WHEN** two subjects have uploaded identical bytes and one subject's document is no longer referenced by that subject
- **THEN** the other subject's version still downloads its bytes unchanged

### Requirement: The file content lives outside the database, under a relative path

The database SHALL NOT store file content. A version row SHALL carry the filename, the detected MIME type, the byte size, the SHA-256 digest, and a storage path relative to a configured storage root. The storage root SHALL be read from configuration for each request rather than captured at import time.

#### Scenario: A stored version points at a relative path

- **WHEN** a version is stored
- **THEN** its `storage_path` is relative to the configured root, and the file exists at that path under the root

### Requirement: Archiving classifies a document

Archiving SHALL set the document's `kind` to one of `transcript`, `cv`, `ps`, `recommendation`, `language`, `passport`, `gs`, `other`, set `status` to `archived`, and record `archived_by` and `archived_at`. A `kind` SHALL be required: a document SHALL never be archived without one, and a value outside the set SHALL be refused. Archiving SHALL be refused with 409 while the document's status is `under_review`, under any kind: the running review cites the criteria for the document's kind, so changing that classification would move the ground under it.

#### Scenario: Archiving sets the classification and the status

- **WHEN** the owner archives their document as `transcript`
- **THEN** the document reports `kind = transcript`, `status = archived`, and a non-null archive time

#### Scenario: Archiving without a kind is refused

- **WHEN** an archive request carries no `kind`
- **THEN** the response is 422 and the document's kind stays unset

#### Scenario: An unknown kind is refused

- **WHEN** an archive request carries a kind outside the eight defined values
- **THEN** the response is 422 and the document is unchanged

#### Scenario: Archiving while under review is refused

- **WHEN** a document is `under_review` and its owner archives it, whether or not the kind changes
- **THEN** the response is 409 and the document keeps the kind the review was run against

### Requirement: A document moves through a defined set of review states

The system SHALL allow only these transitions, and SHALL answer a transition it does not allow with 409 rather than storing the requested state:

- an upload sets `uploaded`;
- archiving sets `archived`, except from `under_review`, which is refused with 409;
- submitting sets `under_review`, and SHALL require `kind` to be set and the current status to be `archived` or `needs_revision`;
- a human review of the current version sets `accepted` or `needs_revision`; a review whose verdict is inconclusive leaves the document `under_review`, which is a recorded review that changes no status rather than an unlisted transition;
- uploading a new version sets `uploaded` from any status and SHALL preserve `kind` and `archived_at`.

#### Scenario: Submitting requires a classification

- **WHEN** a document has just been uploaded and is not yet archived, and its owner submits it for review
- **THEN** the response is 409 and the document stays `uploaded`

#### Scenario: A revision can be resubmitted

- **WHEN** a document is `needs_revision` and its owner submits it again
- **THEN** the document becomes `under_review`

#### Scenario: An accepted document needs a new version before it can be reviewed again

- **WHEN** a document is `accepted` and its owner submits it again without uploading a new version
- **THEN** the response is 409

#### Scenario: A new version returns the document to uploaded and keeps the classification

- **WHEN** the owner uploads a new version of an `accepted` transcript
- **THEN** the document is `uploaded`, its `kind` is still `transcript`, and its archive time is unchanged

### Requirement: An upload names the file and may name a requirement

An upload SHALL be a multipart form whose file arrives in a field named `file`, optionally accompanied by a document `title` and a `task_id` naming the roadmap requirement the document satisfies. With no title the document's title SHALL be the uploaded filename. With no `task_id` the document SHALL still be stored, with a null `task_id`. A `task_id` that names another subject's task, or that names no row at all, SHALL be refused with 422 and SHALL create nothing.

#### Scenario: An upload with no requirement is stored

- **WHEN** a caller uploads a file and names no task
- **THEN** the document is stored and its `task_id` is null

#### Scenario: A requirement that belongs to the caller is attached

- **WHEN** a caller uploads a file naming one of their own task ids
- **THEN** the document is stored with that `task_id`

#### Scenario: A requirement that names nothing is refused

- **WHEN** an upload names a task id that no row carries
- **THEN** the response is 422 and no document is created

#### Scenario: A requirement that is deleted later does not take the document with it

- **WHEN** a document is attached to a task and that task is later removed by a recomputation
- **THEN** the document and its versions still exist and the document's `task_id` is null

### Requirement: The applicant can read their own material library

`GET /api/documents` SHALL serve the caller's documents, each with its title, its classification, its status, and its current version. `GET /api/documents/{id}` SHALL serve that document with its complete version list — newest first — its reviews, and the findings of each review with the criterion and the official source each cites. A value nobody has established SHALL be served as `null`, never as an empty string or a zero.

#### Scenario: An unclassified document reports no kind

- **WHEN** a document has been uploaded but not archived
- **THEN** its `kind` is `null` rather than `other` or an empty string

#### Scenario: The list carries the current version and the detail carries them all

- **WHEN** a document has three versions
- **THEN** the list names only its current version, and the detail names all three, newest first

#### Scenario: A document with no reviews reports none

- **WHEN** the owner reads a document nobody has reviewed
- **THEN** its reviews are an empty list rather than a review with an invented verdict

### Requirement: A stored file can be downloaded and cannot be rendered as a page

`GET /api/documents/{id}/versions/{version_no}/file` SHALL serve the stored bytes to the owning subject with the detected content type, a `Content-Disposition: attachment` header carrying the original filename (RFC 5987 encoded so non-ASCII names survive), and `X-Content-Type-Options: nosniff`. A version number that does not belong to the named document SHALL be 404.

#### Scenario: Downloading serves the stored bytes as an attachment

- **WHEN** the owner downloads a stored version
- **THEN** the response carries the stored bytes, the detected content type, an attachment disposition naming the original filename, and `X-Content-Type-Options: nosniff`

#### Scenario: A version number that belongs to another document is absent

- **WHEN** a caller asks for version 3 of a document that has two versions
- **THEN** the response is 404

### Requirement: This change removes nothing

No route in this change SHALL delete a document, a version, a review, or a stored file. Every declared path SHALL answer a method it does not offer with 405 rather than 404 — in particular `DELETE /api/documents/{id}`, `PUT /api/documents/{id}`, and any method other than `GET` on `/api/documents/{id}/versions/{n}/file`.

#### Scenario: A delete request is refused

- **WHEN** a caller sends `DELETE /api/documents/{id}` for their own document
- **THEN** the response is 405 and the document, its versions, and its files are unchanged

#### Scenario: A write to the file route is refused

- **WHEN** a caller sends `POST` to `/api/documents/{id}/versions/{n}/file`
- **THEN** the response is 405 and the stored bytes are unchanged

### Requirement: The material library is usable from the interface

The web application SHALL let the applicant upload a file from a roadmap task row, with that requirement attached to the document; SHALL list the applicant's materials with their classification, status, and current version; and SHALL let the applicant download a version, archive a material, and submit it for review.

#### Scenario: Uploading from a task row attaches the document to that requirement

- **WHEN** the applicant uploads a file from a task row in the roadmap
- **THEN** the stored document names that task, and the library lists the document under it

#### Scenario: The library reports a material's state from the server

- **WHEN** the applicant opens the library after uploading and archiving a file
- **THEN** the material is shown with the classification and status the server holds, and a reload shows the same values
