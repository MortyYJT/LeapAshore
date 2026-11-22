# LeapAshore

**A personal workspace for tracking master's applications from shortlist to submission.**


[![CI](https://github.com/MortyYJT/LeapAshore/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MortyYJT/LeapAshore/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Live site](https://img.shields.io/badge/live-leapashore.mortyyjt.site-2f6f4f.svg)](https://leapashore.mortyyjt.site)

![Deadline overview: each application is a coloured line from today to its deadline, with a dashed line for a date still to confirm (signed-out demo)](docs/images/home.png)

**Live site:** <https://leapashore.mortyyjt.site> (the interface is in Chinese; it is built for applicants from mainland China).

Sign in with a code sent to your email, then add an application or save a program from the school library. Without signing in you can browse the school library and see a read-only demo of the overview, roadmap and materials pages. Record the round and deadline, check the source, and use the roadmap to track preparation. The AI advisor links to official sources when it answers questions about admission requirements.


## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Engineering highlights](#engineering-highlights)
- [Data and coverage](#data-and-coverage)
- [Tech stack](#tech-stack)
- [Running locally](#running-locally)
- [Evaluation](#evaluation)
- [Status and limitations](#status-and-limitations)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [License](#license)

## What it does

- **Deadline overview.** Each application is a coloured line from today to its deadline, with its status and whether its materials are ready; a date still to confirm is a dashed line, and deadlines coming up soon are marked. Below, a short list says what each application is waiting for. New users can add an application directly from the overview.
- **My applications.** Saved school selections appear automatically. Add projects outside the library manually; edit the chosen round, deadline, source link, application status, a material checklist ticked item by item, and preparation notes. Human date confirmation is explicit and becomes stale when the date, source or round changes.
- **Materials line map.** For each application whose program page has been read, the materials it asks for are stations on its line; a material every program asks for is an interchange, and a line that asks for it differently is marked there. Each requirement links to the sentence and page it was taken from, and the checklist below is ticked by the applicant: a self-check, not an automated review. A program whose page lists no materials is drawn dashed and labelled so, which the page says is not the same as asking for none. The document library with versions stays at the bottom of the page.
- **School library.** 287 universities in 29 countries and regions, ordered by QS 2027 rank. Each school page lists its collected taught master's programs, filterable by name and study area; each program page shows only the requirements that were found (mark thresholds, English, academic background, deadlines), each linked to the official page it came from.
- **Requirement tiers.** An applicant enters four facts (undergraduate school, average mark, English score, target field). Every program with a stated requirement in that field is placed in a tier by how many published requirements the background meets, with the items still to confirm on the official page. Tiers describe requirements met, not admission odds.
- **Portfolio.** The chosen programs with a tier, an application status, the official deadline and one first choice.
- **Application roadmap.** Preparation is one line stepping through phases toward the intake, with a station per task, filled when done; each application's line runs from today to its deadline. Phase dates are labelled as system suggestions; deadlines come from the application records (collected from an official page or entered by the applicant), and a past one is listed as closed instead of being drawn as a future date.
- **Cited advisor agent.** A LangGraph agent that answers requirement questions from the catalogue, and questions about tuition, references and interviews from saved page snapshots, citing the official page. It refuses when the evidence is weak, can update the applicant's profile, and proposes changes to applications and the portfolio on a card the applicant confirms before anything is written. It sits in a dock beside every page, shows its steps as it works, and can be stopped. An applicant can use their own DeepSeek or SiliconFlow key instead of the site's; the key is kept in the browser, sent with each advisor request, and not stored on the server.
- **Deadline reminders by email.** A signed-in account gets an email 14, 7, 3 and 1 days before the deadline of an application that is still being considered or prepared. The lead times can be changed or the reminders turned off in settings. Each reminder is sent once, an account gets at most one email a day, and every email has an unsubscribe link that works without signing in.
- **Accounts and devices.** Sign-in is by a code sent to the applicant's email, and the data belongs to the account. When two devices edit the same record from the same version, the server accepts one edit and answers the other with the stored record; the form then offers to keep the applicant's changes or take the server's. The site can be installed as an app. It keeps no offline copy and shows an explanation page when the server cannot be reached.

### See the workspace

Taken on 2026-11-21 from the live site while signed out. A signed-out visitor sees a labelled demo: the programs, deadlines and material requirements come from the school library as served; the statuses and ticks are examples.

| Advisor dock | Application roadmap |
| --- | --- |
| ![The advisor dock beside the overview, with a question about a deadline placed in its input; asking needs sign-in](docs/images/advisor.png) | ![Application roadmap: preparation phases as one stepped line with a station per task, and each application's line to its deadline](docs/images/roadmap.png) |

![Materials line map: four programs share the transcript and the language score as interchanges; each line's other materials are its own stations](docs/images/materials.png)

<details>
<summary>On a phone</summary>

<img src="docs/images/home-mobile.png" width="390" alt="The deadline overview on a phone, one application per row with its line to the deadline">

</details>

The other pages (my applications, requirement tiers, portfolio, school library, school and program pages, profile) still use the earlier design and have no screenshot here until they are rebuilt ([#109](https://github.com/MortyYJT/LeapAshore/issues/109)).

### Interaction details

- A click on any in-app link answers in the same frame: the sidebar marks the destination and the content area shows that page's title (a bar in its place on a school's or a program's page, whose title is its name). The page's shape (its labels, panels and grey bars at the size of the values) follows 60 ms later unless the page itself is already there, and the page replaces it when its data arrives. Reduced Motion shows the shape at once.
- Task checkboxes update progress and counts immediately. Changes to the same task save in order, and a failed save restores the last confirmed state.
- School filters keep existing results visible while the search runs. The portfolio stays visible while a save is reconciled with the server.

## How it works

```mermaid
flowchart LR
    B[Browser] --> C[Caddy<br/>automatic HTTPS]
    C -->|/api/*| A[FastAPI]
    C -->|everything else| W[Next.js 16]
    A --> G[LangGraph advisor]
    G -->|OpenAI-compatible API| L[(Chat model)]
    A --> P[(PostgreSQL 16<br/>+ pgvector)]
    G --> P
    A -->|rate limits, token quotas| R[(Redis)]
    BT[Celery beat] -->|daily re-collection, daily reminder run| R
    R -->|broker| WK[Celery worker]
    WK -->|robots.txt, per-host rate limit| U[Official university pages]
    WK --> S[(Page snapshots)]
    WK -->|queue state, snapshot chunks| P
    A -->|sign-in codes| ML[SMTP mailbox]
    WK -->|deadline reminders| ML
```

- **One origin.** Caddy sends `/api/*` to FastAPI and everything else to Next.js, so the session cookie is same-origin and needs no CORS. Advisor replies stream over server-sent events and Caddy flushes them immediately.
- **One compose file.** Production runs PostgreSQL, Redis, the API, the Celery worker and beat, Next.js and Caddy from [deploy/compose.prod.yaml](deploy/compose.prod.yaml).
- **The catalogue is written only by the importer.** Collection writes JSON files per school ([api/data/requirements/](api/data/requirements/)); the importer loads a value only if its quote passed the snapshot check and the model judge did not find its summary unfaithful.

### The advisor agent

```mermaid
flowchart TD
    S([user message]) --> I[classify_intent]
    I -->|requirement question| R[retrieve_requirements]
    I -->|tuition, references, interviews| RP[retrieve_passages]
    I -->|planning, profile, application records, general| M
    R --> E{evidence gate}
    E -->|strong| M[main_agent<br/>ReAct]
    E -->|weak| X[refuse with counts,<br/>log a knowledge gap]
    RP --> E2{evidence gate}
    E2 -->|strong| AP[answer from snapshots,<br/>check every quote]
    E2 -->|weak| X
    M -->|tool call, under the step cap| T[tools]
    T --> M
    T -.->|portfolio or application change| H{{interrupt:<br/>applicant confirms}}
    M -->|no tool call or cap reached| D([end])
    AP --> D
    X --> D
```

Code: [api/app/agent/](api/app/agent/). Design choices:

| Decision | Why |
| --- | --- |
| **Route on the state a message wants to change**, not on keywords | An application changes in five ways (plan which programs to apply to, verify a requirement, add background, operate on application records, general questions), so routing on the state touched is exhaustive and explainable |
| **Evidence gate before generation** | A requirement answer needs a recognised school, a program that states a requirement, an https source with a title, and a matching subject when one is named. Otherwise the agent refuses, says what the library does hold, and records a knowledge gap. Every cited source is linked so the applicant can check the official page |
| **Two write levels** | Profile updates are idempotent and run at once. Changes to the portfolio or to an application record (adding one by hand, its round and deadline, its status, a material tick or note) can overwrite the applicant's choices, so those tools call `interrupt()` and write only after a confirm click resumes the graph |
| **Deadlines the model cannot supply** | For a deadline the model passes either the id of a catalogue row, from which the server reads the date, round and source, or a date that the server accepts only if it finds the same date in the applicant's own messages. A date the advisor writes is stored as not yet checked, and the advisor cannot mark it checked |
| **Step cap, not a token cap** | One step is one model call: countable and explainable. A token cap that misfires cuts the chain after the model has already decided to call a tool |
| **Identity from the run config, never from the model** | Tools read the applicant's id from the config, so no prompt can make the agent read or write another applicant's rows |
| **Model failures end the turn cleanly** | When the provider refuses a call (out of credit, rate-limited, unreachable), the advisor says it is temporarily unavailable, keeps any change already confirmed, and records nothing as a knowledge gap |

## Engineering highlights

Every number below is copied from [docs/measurements.md](docs/measurements.md), which also has the commands, dates and caveats.

- **Advisor retrieval, measured before it was changed.** On a 30-question held-out set, Recall@4 went from **0.10 to 0.889** (Precision@4 0.933, false pass 0/6, false block 0/15, down from 0.60), run once on the final code and not tuned on afterwards. On the tuning split each question now reads about 173 rows in 5 ms instead of about 11,100 rows in 144 ms. Full-text ranking later raised held-out Recall@4 from 0.8958 to 0.9583 on the grown catalogue; the gain is a single question, and the record explains why it should be discounted. The evaluation labels were written by an AI against the local database, not reviewed by a person. ([retrieval](docs/measurements.md#fix-advisor-retrieval-baseline-first-then-change-pr-38), [full-text ranking](docs/measurements.md#hybrid-retrieval-pr-58-vector-part-waiting-for-the-owners-siliconflow-key))
- **Answers from page snapshots, checked sentence by sentence.** Each sentence must carry a verbatim quote of 12 or more characters found in a stored chunk, and every number in the sentence must appear in its quotes; otherwise the sentence is removed before anything is sent. In one live run over 38 questions, **82/82 quotes passed the check and 6/6 unanswerable questions were refused**. ([snapshot RAG](docs/measurements.md#snapshot-rag-pr-60))
- **A model judge for summaries.** Every extracted value's summary is judged against its quote before import. On 490 sampled fields (100 random, 390 stratified by field) labelled blind to the judge, it caught **70.1%** of unfaithful summaries (103/147) and wrongly blocked **7.9%** of faithful ones (27/343), precision 79.2% (103/130); weighted to the whole collection, 69.3% caught and 5.7% wrongly blocked. It misses most deadline labels that add an intake. Labels are an AI's, not reviewed by a person. ([faithfulness](docs/measurements.md#summary-faithfulness-evaluation-second-set-pr-83))
- **Conversations survive a crash, and confirmed writes happen once.** Conversations are LangGraph checkpoints in PostgreSQL. A process killed with `SIGKILL` while waiting for a confirmation is resumed by a second process that writes exactly once; a third sees nothing pending and writes nothing, and two simultaneous confirmations also write once. ([persistence](docs/measurements.md#conversation-persistence-pr-56))
- **Rate limits and token quotas in Redis.** Sliding windows per applicant and per IP plus daily token quotas, checked atomically in one Lua script; each turn reserves tokens up front and settles them against the usage the model reports. The limit check measured **p99 5.61 ms** at concurrency 50 over 20,000 checks; a forged `X-Forwarded-For` header had no effect behind Caddy; if Redis is unreachable the advisor fails closed with 503. A request on the applicant's own model key does not count against the daily token quota and stays under the rate windows. ([limits](docs/measurements.md#advisor-rate-limits-and-quotas-pr-40-follow-up-pr-44))
- **A polite collection queue.** One Celery task per page with a per-host token bucket (2 s, or the site's robots.txt `Crawl-delay`); robots.txt refusals, 403s and 429s are recorded and never bypassed or retried; an unchanged page costs no model call. The first large run collected 3,628 of 3,833 pages for at most 36.37 yuan of model cost. ([collection queue](docs/measurements.md#collection-queue-and-change-detection-pr-50-queue-code-pr-51-data-pr-52-review-pr-54-second-round))
- **Only a person can mark a source verified.** A database trigger refuses any non-empty `verified_at` unless an admin's confirmation row is written in the same transaction, and a static scan of the code fails the tests when a new writer of that column appears. ([manual verification](docs/measurements.md#manual-verification-entry-pr-69))

## Data and coverage

| Data | Source | Coverage |
| --- | --- | --- |
| Universities | QS World University Rankings 2027 | 287 schools in 29 countries and regions: the 241 schools of the top 300 inside the covered regions, plus 46 added for regional coverage ([PRD](docs/product/PRD.md#1-positioning)) |
| Australian programs | [CRICOS](https://data.gov.au/data/dataset/cricos), Australian Government Department of Education, [CC BY 2.5 AU](https://creativecommons.org/licenses/by/2.5/au/) | 2,920 master's programs ([measurements](docs/measurements.md#unify-the-requirement-count-and-check-production-pr-46)) |
| Programs and admission requirements elsewhere | Each school's official program pages, collected from saved snapshots | 9,035 programs at 250 schools in the collection files ([PRD](docs/product/PRD.md#8-data-sources)); 9,748 programs in the production catalogue ([measurements](docs/measurements.md#collection-queue-and-change-detection-pr-50-queue-code-pr-51-data-pr-52-review-pr-54-second-round)), of which 7,374 state a requirement and 4,115 passed every machine check ([measurements](docs/measurements.md#summary-faithfulness-check-pr-62)) |
| Application deadlines | Official program pages, checked the same way | 3,555 deadlines for 1,947 programs at 111 schools ([PRD](docs/product/PRD.md#8-data-sources)) |
| Page snapshots for the advisor | The same official pages | 9,344 pages split into 132,204 chunks in production ([measurements](docs/measurements.md#snapshot-rag-pr-60)) |
| Chinese undergraduate institutions | Ministry of Education list of higher-education institutions (as of 2025-06-20) | 3,167 institutions, used to decide which mark threshold applies |

Honesty rules the code enforces:

1. Every requirement carries a verification state: unverified, machine-checked, or verified by a person.
2. `verified_at` is written only by a person's confirmation, never by a default, an importer or a job.
3. Unknown stays unknown: never an empty string, never a zero.
4. Suggested dates are labelled as suggestions; an official deadline without a source is shown as not collected, and a past one as closed.
5. Tiers describe how far a background meets the published requirements, not admission odds.

Licences and attribution: CRICOS data is used under CC BY 2.5 AU. QS rankings belong to QS Quacquarelli Symonds, and QS's terms restrict republication. Requirement quotes belong to the schools that published them; the site shows them as excerpts with links and asks applicants to check the official page. School logos belong to their schools and are shown for identification only; the logos taken from Wikimedia Commons under CC BY-SA (Oxford, Queen's University Belfast, UNIST) are credited in the site footer.

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | FastAPI, SQLAlchemy 2, Alembic, Python 3.12 |
| Database | PostgreSQL 16 with pgvector (`pgvector/pgvector:pg16`), PostgreSQL full-text search |
| Agent | LangGraph 1.2 with `langgraph-checkpoint-postgres`, `langchain-openai`, any OpenAI-compatible chat model |
| Embeddings (optional) | `BAAI/bge-m3` through SiliconFlow, fused with full text by Reciprocal Rank Fusion; off until a key is configured |
| Queue and limits | Celery and Redis 7 (worker, beat, Lua rate-limit scripts) |
| Testing | pytest against real PostgreSQL and Redis, Node's test runner, a Playwright browser walkthrough |
| Deploy | Docker Compose, Caddy 2 |

## Running locally

Prerequisites: Docker, Python 3.12, Node.js 24.

```bash
make db-up                                   # PostgreSQL (pgvector) on :55432, Redis on :56379
python3.12 -m venv api/.venv && api/.venv/bin/pip install -e "api[test]"
(cd web && npm install)
make migrate                                 # Alembic migrations
make seed                                    # seed the catalogue
(cd api && .venv/bin/python -m app.collect.importer)   # import the committed requirement files
make dev                                     # API on :8000, web on :3000
```

`make dev` starts the API in sign-in mode; sign-in codes are written to `api/var/mail.log` instead of being mailed. Run `AUTH_ENABLED=false make dev` for anonymous mode, which ties the profile to a browser cookie; production runs in sign-in mode. To enable the advisor, set `CHAT_API_KEY` (and optionally `CHAT_BASE_URL`, `CHAT_MODEL`) in `api/.env`; without a key the rest of the app works and the advisor says it is not configured. `make help` lists the other targets, including `make worker` and `make beat` for the collection queue.

Checks:

```bash
make test      # date guard, roadmap mirror, backend tests, frontend type-check and unit tests
make verify    # build + make test + the browser walkthrough (needs the API running)
```

Deploying to a server, importing data and operating production are covered in [docs/deploy.md](docs/deploy.md).

## Evaluation

Evaluation sets, runners and recorded results live in [api/evals/](api/evals/). Run them from `api/`:

| Command | What it measures | Calls a model |
| --- | --- | --- |
| `python -m evals.run_advisor --split tune --check` | Retrieval and evidence gate on graded labels: nDCG@4, MRR, Recall@4, Precision@4, false pass and false block rates, latency, rows read, per question type | No |
| `python -m evals.run_advisor --split heldout --retrieval fts --details --out …` | The same on the held-out split (run once per ranking, never tuned on); `--compare A B` counts per-question wins between two runs | No |
| `python -m evals.run_advisor --split tune --intent` | Adds intent-router accuracy | Yes |
| `python -m evals.run_passages --replay evals/results/passages-2026-10-30.json` | Snapshot answers: quote check, refusals, gold page and sentence retrieval, from a recorded run (`--live` reruns it) | No |
| `python -m evals.faithfulness --replay evals/results/faithfulness-2026-10-31.json` | The summary judge against labelled fields and sentences (`--live` reruns it) | No |
| `python -m evals.run_tools --replay evals/results/tools-2026-11-21-after-prompt-fix.json` | Whether the advisor picks the right tool and raises a confirm card only when it should, from a recorded run (`--live` reruns it and requires `--budget-cny`) | No |
| `python -m evals.materials --replay evals/results/materials-sample-2026-11-21.json` | Extracted material requirements against labels for a random sample of program pages, from a recorded score | No |
| `python -m evals.load_advisor_limits --mode check` | Rate-limit check latency and admission under concurrency (needs Redis) | No |

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs three jobs on every pull request: `web` (type-check, unit tests, build), `backend` (pytest against PostgreSQL with pgvector and Redis), and `advisor-eval`, which builds a fresh database, imports every committed requirement file and fails if the tune split falls below [api/evals/advisor_thresholds.json](api/evals/advisor_thresholds.json). The held-out split and anything that calls a model never run in CI. The recorded replays run inside the backend tests.

## Status and limitations

- Each application record tracks one chosen round. Additional rounds can be represented by separate manual records; automatic multi-round scheduling and submission automation are not implemented.
- User-entered dates without a source remain unconfirmed. “Checked by me” records an applicant's explicit check and never changes the catalogue's official verification status. Collected dates still need review for the intended intake and round.
- The committed requirement files hold a material reading for 41 programs: the demo programs and a random sample of 30. Of the 41, 20 have at least one entry. On the 30 sampled program pages the extraction found a document on 12; most of the others name none or send the reader to another page, and linked pages are mostly not read yet. An application whose program has not been read has only the applicant's own checklist.
- Material ticks and preparation notes are the applicant's own record, kept per application. Uploaded documents, their versions and reviews stay in the document library, and nothing checks an uploaded document against a requirement.
- Production runs in sign-in mode. Sign-in codes and reminder emails go out through one QQ Mail account over SMTP. A signed-out visitor sees a labelled read-only demo on the overview, roadmap and materials pages: its programs, deadlines and material requirements are read from the public catalogue, its application statuses and task ticks are examples, and no material is ticked. A page that cannot build the demo from the catalogue shows the sign-in prompt instead.
- A reminder that was not sent on its day is caught up for two days and then dropped, so an application added later than that inside a lead time's window gets its first reminder at the next shorter lead time. No reminder email has been confirmed as delivered through the production mailbox yet.
- The overview, advisor dock, materials and roadmap pages use the line-map design. My applications, requirement tiers, portfolio, profile, the school library with its school and program pages, the privacy and unsubscribe pages and the admin pages still have the earlier layout with the new colours ([#109](https://github.com/MortyYJT/LeapAshore/issues/109)).
- Retrieval supports hybrid full-text/vector ranking. Deployment settings and historical measurements are recorded in [the handoff](note/handoff.md) and [measurements](docs/measurements.md).
- The advisor depends on a paid model account, the site's or the applicant's own, and can be unavailable; it then says so instead of answering.
- Requirements are collected for 250 of the 287 schools. The other 37 refused the crawler (robots.txt or HTTP 403), had no listing the queue could read, or publish no list of taught master's programs. Many program pages put their requirements on a separate page the queue does not follow yet, and requirements published only in PDFs are not read.
- No requirement has been verified by a person yet; every source is unverified or machine-checked.
- Evaluation labels for retrieval and for the summary judge were written by AI labellers, not by a person. So were the tool-choice cases and the material labels, and the recorded tool-choice run above was made on the same cases the prompt had just been changed against, so it is not a held-out result.

## Repository layout

```text
api/                     FastAPI service, Alembic migrations, tests
  app/agent/             LangGraph advisor: intent, evidence gate, tools, snapshot answers
  app/collect/           collection: snapshots, extraction, summary judge, Celery queue, importer
  data/requirements/     collected requirements, one JSON file per school
  evals/                 evaluation sets, runners and recorded results
web/                     Next.js app
  app/                   pages: home, applications, materials, roadmap, schools, programs, tiers, portfolio, advisor, me, privacy, reminders, admin
  prototype-fixtures/    school list, CRICOS courses, Chinese institutions
deploy/                  production compose file, Caddyfile, environment template
docs/                    deploy guide, measurements, product requirements, images
openspec/specs/          behaviour specifications
scripts/                 browser walkthrough and repository guards
```

## Documentation

- [Product requirements](docs/product/PRD.md)
- [Measurements per task](docs/measurements.md): every number in this README, with commands and caveats
- [Deploy and operations guide](docs/deploy.md)
- [Behaviour specifications](openspec/specs/) (OpenSpec)
- [Backend design notes](note/design/) (in Chinese)

## License

The code is released under the [MIT License](LICENSE), © 2026 MortyYJT. Collected data keeps its sources' terms; see [Data and coverage](#data-and-coverage).
