# LeapAshore 鱼跃彼岸

**An application-planning agent for master's degrees at the world's top universities.**
留学申请 agent：覆盖 QS 2027 前 300 的大学，把申请拆成一张能点开的路线图，每条要求都能追溯到官方页面。

**Live demo:** <http://43.161.224.82>

| Entry | What to try |
| --- | --- |
| [`/`](http://43.161.224.82/) | Ten-step onboarding; finishing it opens the assessment result |
| [`/prototype/schools`](http://43.161.224.82/prototype/schools) | 346 schools, filterable by region, QS band and alliance |
| [`/prototype/assess`](http://43.161.224.82/prototype/assess) | Enter a background, get every program tiered 冲刺 / 匹配 / 保底 / 不满足 with rule-by-rule evidence |
| [`/prototype/advisor`](http://43.161.224.82/prototype/advisor) | Chat with the LangGraph advisor agent |

Things to ask the advisor:

- `悉尼大学计算机硕士要什么均分和雅思？` — retrieval, evidence gate, numbered citations to the official page
- `MIT 的计算机硕士要什么条件？` — the gate refuses: the school has no sourced data yet
- `我是武汉大学计算机专业，均分 85，雅思 7.0` — the agent writes the profile (low-risk write, runs at once)
- `把蒙纳士人工智能硕士加进我的选校组合，作为冲刺` — the agent proposes the change and waits for a confirm click

## Why this exists

Applicants plan a master's application over 6–12 months from facts scattered across dozens of
university pages. Agencies are opaque, spreadsheets go stale, and general chatbots invent admission
requirements that an applicant will then act on.

LeapAshore's position: **every factual claim traces to an official page, and when the system cannot
source an answer it says so instead of guessing.** The full product requirements are in
[docs/product/PRD.md](docs/product/PRD.md) (Chinese).

## Architecture

```mermaid
flowchart LR
    B[Browser] --> C[Caddy :80]
    C -->|/api/*| A[FastAPI]
    C -->|everything else| W[Next.js 16<br/>standalone server]
    A --> G[LangGraph advisor]
    G -->|OpenAI protocol| L[(Chat model)]
    G --> T[Tools]
    T --> P[(PostgreSQL 16)]
    A --> P
    W -.->|fixtures: CRICOS, school lists| W
```

- One origin: Caddy routes `/api/*` to FastAPI and the rest to Next.js, so the anonymous
  `leapashore_client` cookie is same-origin and needs no CORS plumbing.
- The advisor streams over server-sent events; Caddy flushes immediately so tokens arrive as they are
  produced.
- Everything runs from one `docker compose` file on a 2-core, 4 GB server
  ([deploy/compose.prod.yaml](deploy/compose.prod.yaml)).

## The advisor agent

```mermaid
flowchart TD
    S([user message]) --> I[classify_intent]
    I -->|官方要求核验| R[retrieve_requirements]
    I -->|规划 / 资料补充 / 业务操作 / 通用问答| M
    R --> E{evidence gate}
    E -->|strong| M[main_agent<br/>ReAct]
    E -->|weak| X[refuse +<br/>log knowledge gap]
    M -->|tool calls, step < cap| T[tools]
    T --> M
    T -.->|portfolio change| H{{interrupt:<br/>applicant confirms}}
    M -->|no tool call or cap reached| D([end])
    X --> D
```

Code: [api/app/agent/](api/app/agent/). The design is ported from my earlier LangGraph
customer-service agent and re-pointed at application state.

| Decision | Why |
| --- | --- |
| **Intent = which state the message wants to change**, not keywords | An application only changes in five ways (plan, verify a requirement, add background, operate on tasks, general Q&A), so routing on the state touched is exhaustive and explainable |
| **Evidence gate before generation** | A requirement answer needs a catalogue hit, an https source with a title and id, and a relevance score above the threshold. Otherwise the agent refuses and logs a knowledge gap. Unverified sources are shown but labelled 待核验 with the link |
| **Two write levels** | Profile updates are idempotent and run at once. Portfolio changes can overwrite the applicant's choices, so the tool calls `interrupt()` and writes only after a confirm click resumes the graph |
| **Step cap, not token cap** | One step is one model call: countable and explainable. A token cap that misfires cuts the chain after the model has already decided to call a tool |
| **Identity from config, never from the model** | Tools read the client id from the run config, so no prompt can make the agent read or write another applicant's rows |
| **Router failure degrades to general Q&A** | The one exit that writes nothing |

## Data and honesty rules

| Data | Source | State |
| --- | --- | --- |
| Australian master's programs (2,920) | CRICOS, data.gov.au, CC BY 2.5 AU | Real, attributed, dated |
| Chinese institutions (3,167) and tier tags | Public lists | Real; known gaps recorded in the fixture |
| Overseas schools (346) | QS World University Rankings 2027 top 300 + 46 for regional coverage | Real |
| Admission requirements | Official course pages | **Pending verification (待核验)** |
| Deadlines | Official pages | **Not collected** |

These rules exist because an earlier version of this product generated a plausible verification
date and an official-looking threshold with no source. Do not undo them.

1. Every requirement carries a verification state: 待核验 / 机器核对 / 人工已核验.
2. `verified_at` is written by a human, never defaulted.
3. Unknown stays unknown — never an empty string, never a zero.
4. Suggested dates are labelled as system suggestions; empty official deadlines render as 待核验.
5. Tiers describe how far a background meets the published requirements, not admission odds.

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| Backend | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 |
| Agent | LangGraph 1.2, LangChain OpenAI adapter, any OpenAI-compatible model |
| Deploy | Docker Compose, Caddy |

## Run it

Locally:

```bash
make install     # frontend and backend dependencies
make dev         # database, API on :8000, frontend on :3000
make test        # type-check, frontend unit tests, backend tests
```

Set `CHAT_API_KEY` (and optionally `CHAT_BASE_URL`, `CHAT_MODEL`) in `api/.env` to enable the advisor.
Without a key the rest of the app works and the advisor says it is not configured.

On a server:

```bash
cp deploy/.env.example deploy/.env   # set POSTGRES_PASSWORD and CHAT_API_KEY
docker compose -f deploy/compose.prod.yaml up -d --build
```

The API container applies migrations and runs the idempotent seeds on start.

## Status

Done:

- Onboarding, portfolio picker, six-phase roadmap with material checklists
- School and program libraries, background assessment with rule-by-rule tiers
- Material library: upload, versions, archive, download (size limit, type sniffed from bytes)
- Advisor agent: intent routing, evidence gate, ReAct tools, confirm-before-write, streamed replies
- Production deployment

Not yet:

- Admission requirements are unverified placeholders for six Australian programs; every other school
  shows its program data as 待采集 (to be collected)
- Conversations live in an in-memory checkpointer and are lost on restart (a Postgres checkpointer is
  a schema change and needs its own migration)
- Knowledge gaps go to the log, not to a review queue
- No evaluation set for the router or the gate yet
- HTTP only until the site has a domain; no accounts, the profile is tied to an anonymous cookie

## Project records

- [Product requirements (Chinese)](docs/product/PRD.md)
- [Contribution and commit rules](CONTRIBUTING.md)
- [Repository instructions for agents](AGENTS.md)
- [Cross-change decisions (Chinese)](note/decisions.md)
- [Backend design (Chinese)](note/design/)
