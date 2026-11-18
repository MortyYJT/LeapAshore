## Context
The existing portfolio is catalogue-keyed and whole-replaced. It must remain compatible with selection and advisor tools.

## Goals / Non-Goals
Goals: scoped manual applications, persistent per-application preparation state, sourced deadline editing, actionable home and accurate product docs. Non-goals: reminders, autonomous submission, invented dates, replacing existing catalogue/agent APIs.

## Decisions
Add an application_plans table for manual records and optional overlays of saved catalogue selections. GET /api/application-records combines saved selections with their overlays and manual records; reads never create planning rows. Existing selections retain their IDs and confirmation behavior. Catalogue status/date edits also update the existing selection so the roadmap remains consistent. Removing a selection uses the same persisted application row; removing a manual record only removes its plan.

Unknown dates stay null. A user-entered date can exist without a source but is labelled unconfirmed. A check timestamp is written only when a human explicitly confirms a date with an HTTP(S) source. Editing date, source or round invalidates confirmation. No automatic writes to source verification metadata.

Reuse the current shell and theme. /applications becomes the personal workspace; /portfolio remains the selection editor. Home groups active dated applications by date, then undated applications needing confirmation, and presents real roadmap tasks with the existing tick API. New users get an add-project empty state. Materials readiness is a self-reported checklist/notes field, not an automated document review claim; the existing document library remains available.

## Risks / Trade-offs
Existing portfolio replacement can remove a catalogue selection: overlays are only displayed while the selection exists and cascade on account deletion. Concurrent creation of the same overlay is handled by a unique applicant/program constraint and retry-safe lookup. Legacy read/write APIs remain unchanged.

## Migration Plan
Add the new table through Alembic; deploy API and worker-compatible models before the frontend. Back up production first. Rollback uses prior images while leaving the additive table intact; never downgrade away user records.
