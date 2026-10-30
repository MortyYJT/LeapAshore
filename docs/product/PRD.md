# LeapAshore (鱼跃彼岸) product requirements document (PRD)

| Item | Value |
| --- | --- |
| Version | v0.1 first draft |
| Date | 2026-10-28 (translated into English 2026-10-31) |
| Author | MortyYJT |
| Status | Draft; items marked **[Open]** need a decision |
| Sources | `note/decisions.md`, `openspec/specs/`, the `/prototype` prototype |

Interface text is Chinese; it is quoted in Chinese with an English gloss. Counts in section 8 are as of the 2026-10-30 import before the summary faithfulness check; the current numbers are in `note/handoff.md` and [`docs/measurements.md`](../measurements.md).

---

## 1. Positioning

**LeapAshore is a study-abroad application agent covering 287 universities in 29 countries and regions (mostly the QS 2027 World University Rankings top 300).** It turns an application into a visual roadmap: what to prepare at each stage, when to prepare it, and which official page each requirement comes from, all one click away.

**[Decided D5] Coverage follows the school list:** the 241 schools of the QS 2027 top 300 that are inside the covered regions, plus 46 schools added to complete regional coverage, 287 in total across 29 countries and regions (`web/prototype-fixtures/overseas-institutions.json`, fetched 2026-10-10). Covered regions (decided 2026-10-29): the United States, the United Kingdom, Australia, Canada, New Zealand, Hong Kong, Macau, Singapore, South Korea, Malaysia, 16 European countries (Germany, the Netherlands, Switzerland, France, Belgium, Sweden, Italy, Spain, Ireland, Denmark, Norway, Austria, Finland, Portugal, Czechia, Poland) and 3 Middle Eastern countries (UAE, Saudi Arabia, Qatar). The 59 out-of-scope schools (mainland China, Japan, India, Taiwan, Indonesia, Thailand, Kazakhstan, South Africa, Latin America, Israel, Lebanon, Turkey, Russia) were removed from the school list on 2026-10-30.

The difference is not "recommending schools" but two things:

1. **Every fact traces back to an official source**; without a source it is marked `待核验` (unverified).
2. **When the system cannot judge, it says so** instead of inventing a threshold or a conclusion.

## 2. Background and problem

### 2.1 Target users

Chinese undergraduates, current or graduated, applying for taught or research master's degrees at universities in the school list (see D5).

### 2.2 What they do today

| Approach | Problem |
| --- | --- |
| An agency | Expensive; opaque, and students can hardly tell whether the thresholds they are given are real |
| Official sites + Excel | Information is spread over dozens of pages per school; deadlines, language sub-scores and document lists are easy to miss |
| Asking an AI chatbot | It invents admission requirements and deadlines, and students who act on them get it wrong |

### 2.3 Core problem

An application is not one question but **a state that lasts 6–12 months and keeps changing**: today a program's requirements, next week an IELTS result, next month which schools to apply to. Existing tools either answer single questions or do not guarantee the information.

## 3. Goals and non-goals

### 3.1 Goals

| ID | Goal | How it is measured (metric definitions, no preset values) |
| --- | --- | --- |
| G1 | Students see in one place "where to apply, what each needs, when to do it" | Conversion from onboarding to seeing the roadmap |
| G2 | Every official requirement the system shows is traceable | Share of requirement entries with a source; share of `待核验` entries |
| G3 | The agent does not make things up | Evidence-gate refusal rate; unsourced claims found in manual spot checks |
| G4 | Students come back to update their state | Number of and intervals between document ticks and profile updates |

### 3.2 Non-goals

- No admission probability prediction or school ranking. A conclusion without reliable data is worse than none.
- No model-generated admission requirements, deadlines or mark thresholds.
- No visa, immigration or other advice with legal consequences.
- No fabricated data, metrics or sources for demos.

## 4. Current state (2026-10-28)

The repository has **two front ends** that do not quite agree:

| | Main flow (`/`) | Static prototype (`/prototype`) |
| --- | --- | --- |
| Shape | Onboarding questionnaire → generated plan → portfolio → roadmap main screen | School list / program list / background assessment / advisor chat / application progress / consultant back office |
| Focus | Personal application planning (the agent keeps the state) | Browsing programs and assessment, ending in "contact a consultant" |
| Data | 6 placeholder programs, all `待核验` | Real CRICOS program facts (2,920 Australian master's programs), 3,167 Chinese institutions, 287 overseas institutions; admission requirements are labelled sample data |
| Back end | FastAPI + PostgreSQL (profile, roadmap, portfolio, document library) | None; reads local fixtures |
| Agent | None; the advisor chat returns a fixed message | None |

**[Decided D1] How the two front ends merge:** the prototype's school list, program list and background assessment become the "learn and assess" entry, the main flow's roadmap becomes the "plan and execute" main screen, and the advisor chat is the agent's entry. Lead-generation features ("contact a consultant", the consultant back office) move to a later version so the product does not turn into an agency's lead funnel.

**Effect of going global:** existing data and rules were built for Australia. CRICOS covers only Australia; the roadmap's sixth stage uses the CoE, an Australian visa document, while the US and UK use the I-20 and CAS. Going global needs a program data source per country and roadmap stage templates per country.

## 5. User flow

```
Home
 ├─ Browse schools / programs / a sample roadmap / open the advisor page (no sign-in)
 └─ Sign in (email + 6-digit code; the first sign-in registers)
       ↓
   Profile step (undergraduate school, average mark, study area, English score; can be skipped)
       ↓
   Program tiers (reach / match / safety / not eligible; users who skipped the profile see "fill in your information first")
       ↓
   Choose the application portfolio (user confirms)
       ↓
   Application roadmap (main screen) ── open a stage → document list, suggested dates, official deadlines, sources
       ↑        ↓
   AI advisor chat: ask about requirements, add to the profile, adjust the portfolio (writes need confirmation)
```

## 6. Functional requirements

Priority: **P0 = must ship in the MVP**, P1 = do before interviews if possible, P2 = later versions.

### 6.1 School and program lists

| ID | Requirement | Priority |
| --- | --- | --- |
| F1.1 | Filter schools by region, QS rank and university group; show the Chinese name and logo | P0 (in the prototype) |
| F1.2 | Filter programs by school, subject and tuition; program facts come from CRICOS with their source | P0 (in the prototype) |
| F1.3 | Compare several programs side by side | P1 (in the prototype) |
| F1.4 | The program page lists admission requirements, each with its source and verification state | P0 |

### 6.2 Profile step and tiers

The background assessment page (`/assess`) was removed on 2026-10-30. Tiering needs only four items, entered in the profile step after first registration; the other fields live on the "Me" (我的) page.

| ID | Requirement | Priority |
| --- | --- | --- |
| F2.1 | After first registration a profile step appears with four required items that can be skipped: undergraduate school (985 / 211 / other recognised automatically), average mark (with scale), study area, English score; degree level, major, target degree, intake and budget are entered and edited on "Me" | P0 |
| F2.2 | Each program is compared requirement by requirement, giving a tier and the reason for each requirement | P0 (in the prototype) |
| F2.3 | Tiers appear only when all four profile items are filled; users who skipped see "fill in your information first" on the tiers page; programs whose requirements are not collected are not tiered and are listed separately as "requirements not collected" | P0 |
| F2.4 | Suggest what it would take to reach the next tier | P1 (in the prototype) |

### 6.3 Application portfolio

| ID | Requirement | Priority |
| --- | --- | --- |
| F3.1 | Choose programs to apply to from the tiers and mark the first choice | P0 (in the main flow) |
| F3.2 | Changing the portfolio recomputes the roadmap and needs explicit user confirmation | P0 |

### 6.4 Application roadmap (main screen)

| ID | Requirement | Priority |
| --- | --- | --- |
| F4.1 | Six stages in a column, each with a document list, suggested dates, official deadlines and sources | P0 (in the main flow) |
| F4.2 | Ticking documents updates the stage's state automatically | P0 (in the main flow) |
| F4.3 | Suggested dates are labelled "系统建议 · 非官方日期" (system suggestion, not an official date); an official deadline with a source is drawn solid and links to the source; an uncollected one shows "未收录" (not collected); a past one is labelled "已截止" (closed) and not placed on the timeline | P0 |
| F4.4 | Documents are filtered by degree and study area (research degrees add a research proposal, design programs a portfolio) | P0 |

### 6.5 Document library

| ID | Requirement | Priority |
| --- | --- | --- |
| F5.1 | Upload, versions, archive categories, download | P1 (back end and front end done, see `openspec/specs/document-library`) |
| F5.2 | A document review conclusion must cite a review criterion with an official source | P2 (rules settled; reviews are entered by a person) |

### 6.6 AI advisor (agent)

| ID | Requirement | Priority |
| --- | --- | --- |
| F6.1 | Chat interface with streaming output | P0 |
| F6.2 | Intent routing: planning / official requirement verification / profile update / operation / general Q&A (see 7.3) | P0 |
| F6.3 | Answers about official requirements pass the evidence gate first; otherwise refuse and record a knowledge gap; unverified data is answered with a label (see 7.4) | P0 |
| F6.4 | Writes by risk: low risk runs at once, high risk returns a proposal for the user to confirm (see 7.5) | P0 |
| F6.5 | Remember the application state across sessions | P1 |
| F6.6 | Knowledge gaps go into a human sourcing queue | P2 |

**[Open D2] How far the agent goes in the MVP.** Suggest at least F6.1–F6.4: chat, look up program requirements with sources, refuse, and change the portfolio through proposals. This is the core of an "agent developer" interview demo.

### 6.7 Lead generation and consultant back office

| ID | Requirement | Priority |
| --- | --- | --- |
| F7.1 | "Contact a consultant" panel (WeChat, lead form, booking) | P2 (in the prototype, all samples, nothing is sent) |
| F7.2 | Consultant workbench (leads, questions to answer) | P2 (in the prototype, all fictional samples) |

### 6.8 Accounts and sign-in

| ID | Requirement | Priority |
| --- | --- | --- |
| F8.1 | Sign in with email + 6-digit code; the first sign-in registers; codes expire after 10 minutes, work once, are void after 5 wrong tries, and cannot be resent within 60 seconds; daily sends per email and per IP are capped | P0 |
| F8.2 | Sessions are server-side (PostgreSQL table + httpOnly cookie); users can sign out | P0 |
| F8.3 | Without signing in: home, school list, program list, sample roadmap, advisor page. Signing in is needed to save or read your own data ("Me", portfolio, tiers, your roadmap, documents) and to send a message to the advisor. Clicking such an action opens sign-in, and afterwards returns to the same place and completes the action; users who clicked "Sign in" directly land on the tiers page | P0 |
| F8.4 | At first sign-in, the same browser's earlier anonymous profile, portfolio, roadmap tasks and documents merge into the account; existing account data is not overwritten (conflict rules in `openspec/changes/archive/2026-10-30-account-login/design.md` D7); unclaimed anonymous data is cleaned up after 90 days | P0 |
| F8.5 | Every API and advisor tool identifies the user by account and cannot read or write anyone else's data | P0 |
| F8.6 | Deleting an account deletes all its data (including uploaded files); the privacy policy page is public | P0 |
| F8.7 | Code emails go through Tencent Cloud SES (SMTP); locally and in CI codes are only written to the log, which production forbids | P0 |

## 7. Core business rules

### 7.1 Application state model

The agent maintains six objects, not one conversation:

| Object | Content | Who changes it | Reversibility |
| --- | --- | --- | --- |
| Application profile | School tier, average mark, major, language, goals, budget | The user says → the system extracts | Editable any time |
| Candidate program pool | Programs, official sources, versions | Published after operator verification | Versioned |
| Application portfolio | Which programs, which is first choice | The user decides (with confirmation) | Affects later planning |
| Roadmap | Schedule from now to intake | System generates → user adjusts | Can be recomputed |
| Tasks | Concrete to-dos | System suggests + user adds | Editable |
| Knowledge gaps | Questions the system could not answer | System records → a person finds sources → published | — |

### 7.2 Program tier rules

A tier says **how well the official requirements are met, not the chance of admission**.

| Tier | Condition |
| --- | --- |
| Safety (保底) | Every requirement met, and the average mark at least 5 points above the threshold |
| Match (稳妥) | Every requirement met, but not safety |
| Reach (冲刺) | Exactly one requirement not met, and the average mark at most 3 points short or the IELTS overall at most 0.5 short |
| Not eligible (不满足) | Everything else |

The thresholds are named constants in code (`web/lib/tiers.ts`), not any school's official statement.

**Unknowns (after removing the "not enough information" tier):**

- Unknowns on the user's side: if the four profile items (undergraduate school, average mark, study area, English score) are not all filled, there are no tiers and the tiers page shows "fill in your information first", so a tiered background has no unknowns.
- Unknowns on the program's side: programs whose requirements are not collected are not tiered and are listed separately as "requirements not collected", outside every tier.
- Unchanged floor: an unknown never counts as met and never as not met.

**School tier:** tiers other than 985 / 211 (first-tier, second-tier, junior colleges) and overseas schools always return "needs human verification" (shown as "去官网确认", check the official site), with no common baseline applied.

### 7.3 Intent routing

The criterion is not "does the message contain certain keywords" but "which state does this message want to change":

| Intent | Criterion | Handling | Writes |
| --- | --- | --- | --- |
| Planning / re-planning | Wants to change which programs to apply to | Deterministic tiers → rebuild the roadmap | Writes (with confirmation) |
| Official requirement verification | Asks about a program's official requirements | Retrieval → evidence gate | Read-only |
| Profile update | Provides new profile information | Structured extraction → update the profile | Writes (low risk) |
| Operation | Wants to change an existing decision or task state | Allow-listed executor | By risk level |
| General Q&A | None of the above | General reply | Read-only |

### 7.4 Evidence gate

An answer about official requirements needs all three of the following; if any fails, it refuses and records a knowledge gap:

1. A retrieval hit: the question names a school in the school list, and the content comes from the database, not from the model.
2. A valid citation: https link, page title and source id all present.
3. Relevance above the threshold: matching only a subject ("computing") does not count; it must match a school.

**Verification state is a label, not a refusal condition.** Requirements whose source has not been verified by a person are still answered, labelled "待核验" with the official link.
Reason: almost all data is unverified today; refusing by verification state would refuse almost every question, and applicants would not get the official pages they should see.

A refusal gives one of four reasons, worded from the catalogue's own counts (`refusal()` in `api/app/agent/evidence.py`; spec `openspec/specs/advisor-retrieval`), and is recorded in the knowledge-gap queue (spec `openspec/specs/knowledge-gaps`):

- `no_school`: no school in the question is recognised.
- `school_not_collected`: the school is known but none of its programs has a collected requirement.
- `no_program_in_field`: the school has collected requirements, but none for the asked subject.
- `no_citable_source`: a program was found but has no citable source.

### 7.5 Confirmation by write risk

| Level | Operations | Behaviour |
| --- | --- | --- |
| Run at once | Update profile fields, tick documents, record deadlines | Idempotent, written directly |
| Needs confirmation | Set the first choice, mark "not considering", recompute the plan (overwrites the portfolio) | Return a proposal → user confirms → execute |

### 7.6 Roadmap back-scheduling

The six stages count back from the intake date:

| Stage | Days before intake | Content |
| --- | --- | --- |
| Lock the portfolio | 330 | Decide where to apply and the first choice |
| Academic and identity documents | 270 | Transcripts, enrolment certificate, grading scale, passport |
| Language preparation | 240 | Overall and **sub-scores** (the most common pitfall) |
| Application-specific documents | 210 | CV, personal statement, references, portfolio, research proposal |
| Submit applications | 150 | Submit school by school, keep receipts |
| Offers and enrolment | 60 | Additional documents, compare offers, deposit, CoE, visa |

These dates are **system suggestions**, and the interface must say they are not official dates.

### 7.7 Data honesty rules

1. Every admission requirement carries a verification state: `待核验` (unverified) / `机器核对` (machine-checked) / `人工已核验` (verified by a person).
2. `verified_at` is written only by a person and never has a default.
3. Unknown is shown as unknown, never as an empty string or 0.
4. Sample data is labelled "示例" (sample) everywhere it appears.
5. Stored values and interface text are separate: the database and API keep the left column, the interface always shows the right. The one-character tier forms (冲 / 稳 / 保) are used only where space is short and mean the same as the full forms.

| Stored value / internal term | Shown in the interface | Meaning |
| --- | --- | --- |
| No such data (`null`) | 未收录 (not collected) | Not yet collected from the official site |
| `待核验` | 未核对 (not checked) | Taken from the official site, not yet checked by anyone |
| `机器核对` | 自动标注 (labelled automatically) | Labelled automatically against an official list |
| `人工已核验` | 已核对 (checked) | A person checked it against the official site |
| Needs human verification | 去官网确认 (check the official site) | The system cannot compare; the applicant should check the official site |
| Match (old term) / `稳` | 稳妥 (match) | See §7.2 |

## 8. Data sources

| Data | Source | State |
| --- | --- | --- |
| Australian master's program facts (code, name, field, duration in weeks, tuition, total cost) | CRICOS open dataset (data.gov.au, CC BY 2.5 AU) | Real data, with source and fetch time |
| Chinese institutions and tier labels | Public lists | Real data; known gaps recorded in the fixture's `known_gaps` |
| Overseas institutions and QS rank | QS World University Rankings 2027 (published 2026-06-18) | Real data. **QS terms restrict republication; licence or replace before public launch or commercial use** |
| Program data outside Australia (program name, school, official page) | Each school's official site, collected page by page from saved snapshots | Real data. Of the 287 schools, 250 have collected programs, 9,035 programs in total (114 schools and 3,560 programs added by the collection queue on 2026-10-30; 16 schools and 252 programs collected the same day in a second round by Claude subagents); the other 37 were **not collected**: the site blocks us (robots.txt or 403), the listing page yields no program links, or there is no list of taught master's programs. Only web pages are read; requirements published only in PDFs are not read yet |
| Admission requirements (marks, language, background) | Each school's official program pages | Real excerpts, every quote checked against a saved snapshot of the page, and every summary checked against its quote by a model judge; a value is imported only if its quote passed and the judge did not find its summary unfaithful (a value not yet judged is imported). In the collection files 4,162 programs are `机器核对` (every value passed) and 4,873 need a person (no value found, or some value failed a check; many program pages added by the queue put requirements on another page, which the queue does not follow yet); **0 verified by a person**, every `verified_at` empty. "States a requirement" (the catalogue's "only collected requirements", each school's count, and the advisor's evidence gate share one rule: an English requirement, a 985/211 or other-school mark threshold, a prerequisite, an academic requirement, or a deadline) totals 7,374 in production, including 2 hand-entered `待核验` placeholders; 4,115 production programs are `机器核对` and 5,939 carry an academic requirement. Australian programs import only onto CRICOS catalogue rows, so machine-checked Australian programs without a known CRICOS code are not imported (production, 2026-10-30, after the summary-faithfulness import) |
| Program study area (outside Australia) | Classified automatically from the English program name (`api/app/collect/fields.py`) | Inferred by the system, not an official classification; used only for retrieval and assessment filters. Against CRICOS's official fields for Australian programs it agrees 78.5% of the time; names that cannot be classified show as "未分类" (unclassified) |
| Application deadlines | Each school's official program pages | **Imported**: 3,555 deadlines for 1,947 programs at 111 schools (production, 2026-10-30), each with its source page. Judged by the current day in Beijing time; past ones are labelled "已截止" and not placed on the timeline (289 on 10-30); a date recorded on a portfolio row wins and the import never overwrites it |

**[Open D3] How many programs' real admission requirements to verify for the MVP.** Suggest 2–3 Group of Eight schools' popular programs (such as computing and business) verified by a person as real examples, with the rest still `待核验`.

## 9. Non-functional requirements

| Aspect | Requirement |
| --- | --- |
| Accessibility | A public link shows the home page, school list, program list, sample roadmap and advisor page without signing in; saving your own data and chatting with the advisor need an email-code sign-in (the first one registers) |
| Responsive | No horizontal scrolling at 375 px phone width or 1,280 px desktop width |
| Privacy | Data is isolated per account; deleting an account deletes all its data; privacy policy at `/privacy`; the lead form sends no real data |
| Security | Uploads are typed by content and size-limited, and downloads cannot render as web pages (implemented) |
| Observability | Every agent call records intent, tool calls and gate results, for explanation and debugging |

## 10. Milestones

| Date | Deliverable |
| --- | --- |
| 10/28 | PRD first draft |
| 10/29 | Architecture diagram; plan for merging the two front ends |
| 10/30–31 | Polish the front-end prototype (main demo path) |
| 11/01 | README; start applying for jobs |
| After applying | Deploy the MVP; connect the agent (F6.1–F6.4); verify real data |

## 11. Open decisions

| ID | Question | Suggestion |
| --- | --- | --- |
| D1 | How to merge the two front ends | **Decided:** the prototype is the "learn and assess" entry, the main-flow roadmap the main screen, lead generation in P2 |
| D2 | How far the agent goes in the MVP | At least F6.1–F6.4 |
| D3 | How many programs' real requirements to verify first | Verify a few schools' popular programs by hand, label the rest `待核验` |
| D4 | ~~Group of Eight or all of Australia~~ | Superseded by D5 |
| D5 | Coverage | **Decided:** follow the school list: the QS 2027 top 300 inside the 29 countries and regions (decided 2026-10-29), 241 schools, plus 46 regional additions, 287 in total |
