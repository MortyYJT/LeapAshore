# LeapAshore PRD: multi-device application tool

Status: in the repository since 2026-11-20 (drafted 2026-11-19 with MortyYJT). Item 1, sign-in, has been live in production since 2026-11-19; item 2, the installable app, is implemented (PR #100; see [measurements](../measurements.md#installable-app-pr-100)); item 3, sync conflict handling, is implemented (PR #94; see [measurements](../measurements.md#sync-conflict-handling-pr-94)); item 6, the agent tools, is implemented (PR #98); its evaluation set of 103 cases was run against the model twice on 2026-11-21, before and after a change to the tools' wording that the first run led to (tool choice 61 of 103, then 102 of 103 on the same cases, so the second is not a held-out figure; the cases were written by a model and not reviewed by a person; [measurements](../measurements.md#tool-choice-evaluation-two-live-runs-and-the-prompt-change-between-them-pr-106)); item 7, material merging, has its data model, per-material checklist, advisor tick and extraction tooling (PR #103) and its merged view, the materials line map (PR #104), with 41 of the catalogue's programs extracted so far (11 chosen, 30 drawn at random; see 3.7 for what the two scores do and do not show), and the faithfulness judge does not cover the new fields yet ([measurements](../measurements.md#random-sample-extraction-30-programs-and-one-entry-from-a-linked-page-pr-107)). Each remaining large item gets an OpenSpec change, and work follows this repository's rules (branch, TDD, `make verify`, review, CI, deploy).

## 1. Why this iteration

LeapAshore is already positioned as a personal tool for managing master's applications. Two things do not yet match that positioning:

- Production runs in anonymous mode. Data lives in one browser session, so it cannot follow the applicant across devices.
- Material readiness is one self-reported checkbox per application. The tool does not know what each program asks for, so it cannot tell shared materials from program-specific ones.

This iteration makes the tool usable across devices, makes it remind the applicant, and makes the agent do the part only a language model can do: turn official requirement text into a material checklist.

## 2. Scope

Batch 1 is the base that makes "multi-device tool" true. Batch 2 builds on it.

| # | Item | Batch | Depends on |
| --- | --- | --- | --- |
| 1 | Turn on account sign-in in production (live since 2026-11-19) | 1 | MortyYJT fills the SMTP authorisation code on the server (done) |
| 2 | Installable app (PWA) | 1 | none |
| 3 | Sync conflict handling | 1 | 1 |
| 4 | Deadline reminders by email | 1 | 1 |
| 5 | Bring-your-own model key, with a small free quota | 2 | none |
| 6 | Agent tools for managing applications | 2 | 3 |
| 7 | Material merging | 2 | none for collection; 6 for the agent entry |
| 8 | Front-end work needed by items 1–7 | both | each item |

Target: batch 1 deployed before applications start (2026-11-21). Batch 2 continues while MortyYJT applies. The resume only gains a line after the feature is deployed and measured.

## 3. Requirements

### 3.1 Sign-in in production
- Email + 6-digit code as already built (existing PRD F8.1–F8.7).
- First sign-in merges the browser's anonymous data into the account without overwriting account data.
- Check after enabling: sign in on two devices and see the same applications; `/api/auth/me` reports the account; anonymous use still works where the existing PRD allows it.

### 3.2 Installable app
- Web app manifest, icons, standalone window, light and dark theme colours.
- An unobtrusive "install" hint on supported browsers; instructions for iOS (add to home screen).
- No offline mode in this iteration. Opening without a network shows a clear message.

### 3.3 Sync conflict handling
- Every applicant-editable record carries a version. An update states the version it was based on.
- A stale update is refused with the current server state. The client shows what changed and lets the applicant keep theirs or take the server's. Nothing is lost silently.
- Creating a record is idempotent: a retried request does not create a duplicate.
- Tests cover two concurrent updates to the same record and a retried create.

### 3.4 Deadline reminders by email
- Signed-in applicants only, sent to the sign-in email. On by default at 14, 7, 3 and 1 days before a deadline; each applicant can change the lead times or turn reminders off. Every email has a one-click unsubscribe link.
- A daily scheduled job finds due reminders. Each reminder is sent at most once per application, deadline date and lead time; a changed deadline re-arms it. Failed sends retry with backoff and are recorded.
- Closed, submitted or withdrawn applications and unknown deadlines get no reminder.
- Deadlines are stored as dates without a time zone. The email states the date as collected and tells the applicant to check the official page for the exact time and zone. Lead times are counted in Beijing time.
- Daily cap on emails per account.

### 3.5 Model key
- The advisor works out of the box on the owner's key with the existing limits and quotas, so anyone can try it.
- An applicant can enter their own key in settings. It is kept only in that browser, sent over HTTPS with each advisor request, used in memory for that request, and never written to the database or logs. A test asserts that the key does not appear in logs. The privacy page states this.
- Requests with a user key skip the daily token quotas but keep the rate windows.
- Allowed providers are a fixed list (starting with DeepSeek); no arbitrary base URL.
- Query embeddings stay on the owner's key.

### 3.6 Agent tools for managing applications
- The advisor can read the applicant's applications with rounds, deadlines and status, and can propose: add an application, set a round or deadline, change status, tick a material.
- Every write is proposed first and executed only after the applicant confirms (existing confirm-before-write flow, executed once under retries and concurrency).
- A labelled evaluation set measures whether the agent picks the right tool and arguments. Numbers are measured, not preset.

### 3.7 Material merging
- Collection extracts, per program, the application materials the official page asks for: type, count, notes, verbatim quote and source. Quotes are verified against the page snapshot as other fields are. Unknown stays unknown; nothing is invented.
- Material types are normalised to a fixed list (CV, personal statement, recommendation letters, transcripts, language score, test scores, portfolio, writing sample, other).
- For one applicant, the tool shows across all their applications which materials are shared and which are specific to one program (different count, a program-specific prompt, an extra item), each with its source link.
- The single "materials ready" checkbox becomes a per-material checklist. Ticks are still the applicant's own check, not an automated review.
- Manual applications without catalogue data keep a free-form checklist.
- A labelled set measures extraction precision and recall, and the faithfulness judge covers the new fields.
- Status (2026-11-21): 11 of the catalogue's programs have been extracted (the signed-out demo's), by a Claude subagent reading stored pages, and scored against labels written by another Claude subagent, not by a person. That is a pilot check of the pipeline and not a measure of precision or recall for the catalogue ([measurements](../measurements.md#first-material-extraction-the-11-demo-programs-pr-105)). A further 30 programs drawn at random from the other 7,540 were extracted and labelled the same way: the extraction found a document on 12 of the 30 program pages (40%), and on (program, type) pairs it has precision 30/31 and recall 30/33 against the model's labels. The sample is small, the labels are a model's, and each program is one page, so this measures what a program page says and not what a program asks for ([measurements](../measurements.md#random-sample-extraction-30-programs-and-one-entry-from-a-linked-page-pr-107)). The judge is not wired to materials: it calls a paid model, and none was called for this item.

### 3.8 Front end
- Only the screens the items above need: sign-in entry and return, install hint, conflict notice, reminder settings, key settings, material checklist and merged view.
- Problems found during the browser walkthrough are fixed. No new visual polish in this iteration.

## 4. Non-goals
- Native Mac or mobile app. Offline editing. Browser push notifications.
- Payments or paid plans.
- Automated submission, automatic multi-round scheduling, automated document review.
- Cache or message-queue additions that current traffic does not need.

## 5. Decisions taken with MortyYJT (2026-11-19)
- Keep web + server; multi-device sync is what justifies the server.
- Reminders go by email first.
- Both key modes: owner's key for trying it, user's own key as an option.
- Applications start by 2026-11-21 at the latest and do not wait for batch 2.

## 6. Needed from MortyYJT
- Fill the SMTP authorisation code on the server (blocks items 1 and 4).
- Say what "agent optimisation" and "front-end optimisation" should cover beyond 3.6 and 3.8, if anything.
- Review this draft.

## 7. Risks
- Batch 1 is four deployable changes in under two days under the repository's full workflow. If something slips, the order of sacrifice is: 2 (installable), then 4 (reminders). Sign-in and conflict handling come first.
- The existing task list deferred reminders until the core flow had real use. This iteration brings them forward; the daily cap and unsubscribe link limit the damage of a mistake.
- Extraction quality for materials is unknown until measured. If precision is low the merged view ships only for programs that pass verification.
