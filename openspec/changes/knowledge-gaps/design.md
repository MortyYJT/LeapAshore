## Context

TASKS.md P2 #1. The advisor refuses in four places, all deterministic (no model call decides a gap):

- the requirement gate (`evidence.gate`): no school recognised, the school has no requirement data, no
  program of the named subject has data, or no citable source;
- the page-topic gate (`passages.gate`): no page of the school, none in the subject, no passage on the
  topic (tuition, recommendation letters, interview);
- the page-topic answer (`answer_passages`): the model answered, but no sentence survived the quote,
  number and support checks;
- a requirement answer that names several schools and had evidence for only some (`missing_schools`):
  the advisor answers for the others and is told not to answer for these.

Each already words its refusal from counts and ends with "已记录为待采集", and logs one line. The
collection queue (P1 #2) has `collect_pages` per page, a discovery task per school, a daily budget, and
deferral on a model outage (PR #65). Accounts (P0 #3) have no role; login mode is off in production, so
every production user is an anonymous cookie subject.

## Decisions

### D1. Two tables: the gap, and the reports that make it up

`knowledge_gaps` is the unit a person reviews: one row per key (D2) with the route, reason, university
ids, subject areas, subject words and page topics; `report_count`, `first_seen_at`, `last_seen_at`; and
the review (`status` open / recollect_queued / dismissed, `reviewed_at`, `reviewed_by` account id with
`ON DELETE SET NULL`, `review_note`, `recollect` — what the review sent, as JSON). It holds no personal
data, so it is kept.

`knowledge_gap_reports` is one row per refusal: `gap_id`, `reporter_hash` (D4), `question` (first 500
characters), `created_at`. It is what a reviewer reads to understand a gap, and it is the only place a
question's words and its asker's hash are kept; it is deleted with the subject and after 90 days (D5).

Inserted with `INSERT … ON CONFLICT (gap_key) DO UPDATE` so concurrent refusals of the same gap add up
instead of colliding. The distinct askers are counted at read time from the reports still kept
("askers in the last 90 days"), not stored: a stored distinct count could not be kept right once
reports are deleted.

### D2. What counts as the same gap

The key is the sha256 of `route | reason | sorted university ids | sorted areas | sorted subject words |
sorted topics`. "墨大数据科学雅思" and "墨尔本大学 data science 语言要求" are one gap (same school, same
area, same subject word after folding). When no school is recognised (`no_school`) the structured part
is nearly empty, so the folded question (NFKC, lower case, spaces and punctuation removed) is added to
the key: identical questions add up, different unknown schools stay apart. No model and no fuzzy
matching: the gate's own signals are the dedupe, so a reviewer can always see why two refusals were
merged.

For `school_missing` (the partial answer) the key's schools are the missing ones only.

### D3. When a refusal is recorded

In the graph, after the gate or the answer decided to refuse: `refuse` (both gates), `answer_passages`
when nothing checkable was left **and** neither the answer nor the support check reported an error (a
malformed answer says nothing about the knowledge), and `retrieve_requirements` for missing schools.
Best effort: a failure is logged and the turn goes on. A model outage ends the turn before any of these
(PR #65), so an unavailable provider is never recorded as a gap. The evals call the gates directly and
record nothing. `KNOWLEDGE_GAPS_RECORD` (default on) lets the test suite switch recording off except in
the tests about it.

### D4. The asker is a keyed hash of the subject

`reporter_hash = HMAC-SHA256(KNOWLEDGE_GAP_HASH_KEY, "knowledge-gap-reporter\n" + subject id)`, hex. The
subject id is the anonymous cookie id or, in login mode, the account's subject id; the account id,
email and IP are never used. Without the key (it lives only in the server's `deploy/.env`) the hash
cannot be recomputed from an id, so the table alone links a report to nobody. One hash per subject (not
per gap), so a deletion can find a subject's reports with one query; the cost is that the reports of
one subject can be grouped, which the question text could do anyway.

Without a key configured no report is stored at all (a report without a hash could not be found again
to delete with its subject, so its words would outlive the deletion; review of #67): the gap's count
still moves, and one warning is logged per process. The list shows `reports` (all time),
`keptReports` and `askers` (both over the reports still kept).

### D5. Deletion, merge, retention

- Deleting a subject (account deletion, the 90-day anonymous sweep) deletes its reports in the same
  transaction: `delete_subject` computes the hash and deletes by it. The gap rows keep their counts,
  which describe the catalogue, not a person.
- Merging an anonymous subject into an account re-keys its reports to the account's hash, so a later
  deletion of the account deletes them too.
- Reports older than `KNOWLEDGE_GAP_RETENTION_DAYS` (90) are deleted by the daily cleanup in both modes
  (the questions are free text an applicant may have put details in). A gap whose reports are all gone
  stays reviewable from its structured key.
- Rotating the key makes the existing reports unlinkable; they still expire after 90 days.

### D6. Admin role: `accounts.role`, granted from the server shell

P2 #3 plans a role field; none exists. Added now, minimal: `accounts.role` VARCHAR(16) NULL, `admin` the
only value used, granted and revoked by `python -m app.roles grant|revoke|list` on the server (no API
can grant it). `require_admin` answers 401 without a valid session and 403 for a non-admin account; in
anonymous mode (production today) every admin request is 403, because there are no accounts. Review in
production therefore goes through the CLI (`python -m app.knowledge_gaps`) until login mode is on. The
admin web page is P2 #3's.

### D7. What a review sends to the collection queue

`recollect` maps each university id to collection keys (the id itself when `_schools.json` has it;
otherwise the `school_key`s its snapshot pages were collected under; otherwise a `_schools.json` row
with the same English or Chinese name). The reviewer may pass `school_keys` instead, which is how a
`no_school` gap (a school the catalogue does not know) is sent, if the school is in `_schools.json`.
For each key: the school's pages that are `pending`, `failed` or `deferred` are queued again (not
`blocked`: refusals are never retried around; not `needs_human`: a person has to look), and one
discovery task is sent when the school has listing URLs (new program pages are queued by the worker).
Both run on the day's collection budget (`daily:<date>`), like the beat. No key, or nothing to send:
409, the gap stays open, so the reviewer can dismiss it instead. Database changes are committed first,
then the tasks are sent; if sending fails the review is undone (the pages back to their earlier states,
the gap's status and review fields as before, the failure added to its note) and the API answers 503,
so the same review can simply be made again (review of #67).

A reviewed gap keeps collecting reports; the list shows how many arrived since the review, so a gap the
recollection did not close is visible again without changing its status automatically.

## Risks

- Re-collecting a school's pages does not help a page-topic gap whose topic is on a page the queue does
  not know (tuition on a fees page): the review note says so; adding a URL is a person's job.
- Free text: a question may contain personal details; mitigated by truncation, deletion with the
  subject and the 90-day limit, and by not showing questions anywhere but the admin review.
