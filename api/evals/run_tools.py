"""Measure whether the advisor picks the right tool and arguments (PRD-multi-device 3.6).

    python -m evals.run_tools --check                         # the set is well-formed; no database
    python -m evals.run_tools --check --fixture               # ...and its account resolves in this database
    python -m evals.run_tools --estimate                      # token counts and cost of a live run; no model
    python -m evals.run_tools --live --budget-cny N [--out FILE] [--only KIND_OR_ID,...]
    python -m evals.run_tools --replay FILE                   # no database, no model

Cases and labels: ``evals/tool_choice_cases.json`` (written by Claude, no human review). Each case is a
message, sometimes with earlier turns, and what a correct turn does: the tools it calls with their key
arguments, the tools it must not call, and whether a confirm card may appear at all.

``--live`` creates an account from the set's ``fixture`` in this database (catalogue applications,
manual ones, a profile), runs the production graph on every case with the chat model in ``CHAT_*``
(the intent router, the evidence gate, the agent and the real tools), and deletes the account. A turn
runs until it ends or stops on its first confirm card; no card is ever answered, so nothing a card
proposes is written. It records, per case, the tool calls with their arguments and how each ended, the
cards, the reply, the route and the tokens, and writes them with the metrics to ``--out``
(``evals/results/tools-<date>.json`` by default).

``--budget-cny`` is a hard cap, checked before every model call: the call is not started unless its
worst case (two tokens per character of the prompt and the tool schemas at the uncached input price,
plus the output cap at the output price) fits in what is left. A call that reports no usage is charged
its worst case. Prices are ``COLLECT_PRICE_*`` in ``app/config.py`` (DeepSeek's own peak prices, as in
the other evals). The cap is in those prices: if the provider behind ``CHAT_BASE_URL`` charges more for
the configured model, set them to its prices before a live run. Query embeddings on the requirement
path are not counted (``EMBED_PRICE_CNY_PER_MTOK``, 0 in the configuration).

``--replay`` recomputes every metric from a recorded file and exits 1 if they differ from what the file
says; CI does this through ``tests/test_tool_eval.py`` with a stubbed model, and with a recorded live
run once one exists.

Metrics (counts; nothing is a threshold until a live run has been looked at):

- tool choice: the expected tools were called in order (other reads may come between), no tool the
  case forbids was called, and no write tool the case does not expect. A case that expects no tool
  passes when nothing is written; ``extra: none`` cases pass only with no tool at all.
- arguments: over the cases whose tools were right and that label arguments, every labelled argument
  of the first matching call is right. ``arguments_any`` counts a later call of the same tool too (the
  model corrected itself after a refusal).
- exact: tool choice and arguments together.
- no card: cases that must never show a confirm card (a date nobody stated, an id that is not the
  applicant's). ``deadline_cards_raised`` is the server's failure and must be 0: these cases are
  written so that no date or round in them is one the tool may accept. ``cards_raised`` counts any
  card, including one for a change the case did not ask for; ``write_attempts`` is how often the model
  tried a change anyway.
- asked back: for the ambiguous cases, whether the reply contains a question mark. A heuristic, not a
  judgement of the reply.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

HERE = Path(__file__).resolve().parent
CASES_FILE = HERE / "tool_choice_cases.json"

READ_TOOLS = ("search_programs", "get_my_profile", "get_my_portfolio", "get_my_applications")
WRITE_TOOLS = (
    "update_my_profile", "propose_portfolio_change", "propose_manual_application",
    "propose_application_deadline", "propose_application_status", "propose_material_tick",
)
KINDS = (
    "search", "profile_read", "profile_update", "portfolio_read", "applications_read",  # one tool each
    "portfolio_change", "manual_add", "deadline_catalog", "deadline_stated", "status", "material",
    "no_tool",  # answered without a tool
    "refuse",  # must be refused: nothing is written
    "ask_back",  # ambiguous: ask which application, date or status
    "multi_step",  # several tools in one turn
    "made_up_date",  # a date nobody stated and the catalogue does not hold
)
MATCHERS = ("absent", "regex", "contains", "in", "json")


def load_set(path: Path = CASES_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- labels -------------------------------------------------------------------------------------------


def _alternatives(element: dict) -> list[dict]:
    """An expected call is one call, or `{"one_of": [...]}` when either of several is right."""
    return element["one_of"] if "one_of" in element else [element]


def _expected_tools(expect: dict) -> set[str]:
    return {alt["tool"] for element in expect.get("calls", []) for alt in _alternatives(element)}


def _refs(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("@") else []
    if isinstance(value, dict):
        return [ref for item in value.values() for ref in _refs(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in _refs(item)]
    return []


def fixture_refs(fixture: dict) -> set[str]:
    """Every `@name` the cases may use, from the fixture's definition alone."""
    names: set[str] = set()
    for row in fixture.get("catalog", []):
        names |= {f"@{row['ref']}", f"@{row['ref']}.program"} | {f"@{row['ref']}.{key}" for key in row.get("deadlines", {})}
    names |= {f"@{row['ref']}" for row in fixture.get("manual", [])}
    return names


def check_set(doc: dict, coverage: bool = True) -> list[str]:
    """What is wrong with the set as written. Needs no database. `coverage` also asks that every kind
    and every tool has a case, which is a property of the whole set and not of a part of it."""
    from app.agent.tools import TOOLS

    arguments = {t.name: set(t.tool_call_schema.model_json_schema().get("properties", {})) for t in TOOLS}
    known = fixture_refs(doc.get("fixture", {}))
    problems, seen = [], set()
    for case in doc.get("cases", []):
        name = case.get("id", "?")
        if name in seen:
            problems.append(f"{name}: id used twice")
        seen.add(name)
        if case.get("kind") not in KINDS:
            problems.append(f"{name}: unknown kind {case.get('kind')!r}")
        if not str(case.get("message", "")).strip():
            problems.append(f"{name}: no message")
        for turn in case.get("history", []):
            if turn.get("role") not in ("user", "assistant") or not turn.get("content"):
                problems.append(f"{name}: a history turn needs a role (user, assistant) and content")
        expect = case.get("expect")
        if not isinstance(expect, dict) or not isinstance(expect.get("calls"), list):
            problems.append(f"{name}: expect.calls must be a list")
            continue
        if expect.get("extra", "reads") not in ("reads", "none"):
            problems.append(f"{name}: extra must be reads or none")
        tools = [alt["tool"] for element in expect["calls"] for alt in _alternatives(element) if "tool" in alt]
        if expect.get("ordered") is False and len(tools) != len(set(tools)):
            # Unordered calls are matched tool by tool; two of one tool need the order to tell them apart.
            problems.append(f"{name}: calls of the same tool need ordered matching")
        labelled = [alt for element in expect["calls"] for alt in _alternatives(element)] + expect.get("if_called", [])
        for alt in labelled:
            if alt.get("tool") not in arguments:
                problems.append(f"{name}: unknown tool {alt.get('tool')!r}")
                continue
            for key, matcher in (alt.get("args") or {}).items():
                if key not in arguments[alt["tool"]]:
                    problems.append(f"{name}: {alt['tool']} has no argument {key!r}")
                if isinstance(matcher, dict) and not any(m in matcher for m in MATCHERS):
                    problems.append(f"{name}: unknown matcher {sorted(matcher)}")
        for tool in [*expect.get("forbid", []), *expect.get("allow", [])]:
            if tool not in arguments:
                problems.append(f"{name}: unknown tool {tool!r}")
        for ref in _refs(expect):
            if ref not in known:
                problems.append(f"{name}: {ref} is not in the fixture")
    if not coverage:
        return problems
    missing = [kind for kind in KINDS if not any(c.get("kind") == kind for c in doc.get("cases", []))]
    if missing:
        problems.append(f"no case of kind: {', '.join(missing)}")
    untested = sorted(set(arguments) - {tool for c in doc.get("cases", []) for tool in _expected_tools(c.get("expect", {}))})
    if untested:
        problems.append(f"no case expects: {', '.join(untested)}")
    return problems


def resolve(value, refs: dict[str, str]):
    """`value` with every `@name` replaced by the id it stands for in this run's account."""
    if isinstance(value, str):
        return refs[value] if value.startswith("@") else value
    if isinstance(value, dict):
        return {key: resolve(item, refs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, refs) for item in value]
    return value


# ---- scoring (pure: a recorded item in, a verdict out) ----------------------------------------------


def _fold(text: str) -> str:
    return "".join(str(text).casefold().split())


def matches(matcher, value) -> bool:
    """Whether an argument the model sent satisfies its label."""
    if isinstance(matcher, dict):
        if matcher.get("absent"):
            return value in (None, "", [], {})
        if "regex" in matcher:
            return isinstance(value, str) and re.search(matcher["regex"], value) is not None
        if "contains" in matcher:
            return isinstance(value, str) and _fold(matcher["contains"]) in _fold(value)
        if "in" in matcher:
            return value in matcher["in"]
        if "json" in matcher:
            try:
                parsed = json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                return False
            return isinstance(parsed, dict) and all(matches(m, parsed.get(k)) for k, m in matcher["json"].items())
        return False
    if isinstance(matcher, bool) or isinstance(value, bool):
        return value is matcher
    if isinstance(matcher, (int, float)):
        try:
            return float(value) == float(matcher)
        except (TypeError, ValueError):
            return False
    return isinstance(value, str) and value.strip() == matcher


def _args_match(labelled: dict, call: dict) -> bool:
    return all(matches(matcher, (call.get("args") or {}).get(key)) for key, matcher in (labelled.get("args") or {}).items())


def _locate(expected: list[dict], calls: list[dict], ordered: bool) -> list[list[int]] | None:
    """For each expected element, the positions of the calls that could be it (same tool, after the
    element before it when the order matters); None when one has no call at all."""
    found, start, used = [], 0, set()
    for element in expected:
        tools = {alt["tool"] for alt in _alternatives(element)}
        positions = [i for i, call in enumerate(calls) if call["tool"] in tools and i >= start and i not in used]
        if not positions:
            return None
        found.append(positions)
        if ordered:
            start = positions[0] + 1
        else:
            used.add(positions[0])
    return found


def score(item: dict) -> dict:
    """The verdict on one recorded case. `item["expected"]` is the label with its `@names` resolved."""
    expect, calls = item["expected"], item.get("calls") or []
    expected = expect.get("calls", [])
    wanted = _expected_tools(expect)
    forbidden = set(expect.get("forbid", [])) | (set(WRITE_TOOLS) - wanted - set(expect.get("allow", [])))
    called = [call["tool"] for call in calls]
    located = _locate(expected, calls, expect.get("ordered", True))
    tool_ok = located is not None and not (set(called) & forbidden)
    if expect.get("extra", "reads") == "none" and set(called) - wanted - set(expect.get("allow", [])):
        tool_ok = False

    labelled = any(alt.get("args") for element in expected for alt in _alternatives(element)) or bool(expect.get("if_called"))
    args_first = args_any = None
    if tool_ok and labelled:
        args_first = args_any = True
        for element, positions in zip(expected, located or []):
            def fits(position: int) -> bool:
                return any(alt["tool"] == calls[position]["tool"] and _args_match(alt, calls[position]) for alt in _alternatives(element))

            args_first = args_first and fits(positions[0])
            args_any = args_any and any(fits(p) for p in positions)
        for rule in expect.get("if_called", []):
            held = all(_args_match(rule, call) for call in calls if call["tool"] == rule["tool"])
            args_first, args_any = args_first and held, args_any and held

    verdict = {"tool_ok": tool_ok, "args_ok": args_first, "args_ok_any": args_any,
               "exact": tool_ok and args_first is not False}
    if expect.get("no_card"):
        verdict["card_raised"] = bool(item.get("cards"))
        verdict["deadline_card_raised"] = any(card.get("tool") == "propose_application_deadline" for card in item.get("cards") or [])
        verdict["write_attempted"] = any(call["tool"] in WRITE_TOOLS and call["tool"] != "update_my_profile" for call in calls)
    if expect.get("reply") == "ask":
        verdict["question_mark"] = any(mark in (item.get("reply") or "") for mark in ("？", "?"))
    return verdict


def metrics(items: list[dict]) -> dict:
    """Counts over the cases that ran. A case the budget stopped, or that broke, is counted apart."""
    ran = [item for item in items if item.get("ran")]
    verdicts = {item["id"]: score(item) for item in ran}

    def count(key: str, pool=None) -> int:
        return sum(1 for item in (ran if pool is None else pool) if verdicts[item["id"]].get(key) is True)

    with_args = [item for item in ran if verdicts[item["id"]]["args_ok"] is not None]
    no_card = [item for item in ran if "card_raised" in verdicts[item["id"]]]
    asked = [item for item in ran if "question_mark" in verdicts[item["id"]]]
    by_kind = {}
    for kind in KINDS:
        pool = [item for item in ran if item["kind"] == kind]
        if pool:
            by_kind[kind] = {"cases": len(pool), "tool_choice_ok": count("tool_ok", pool), "exact_ok": count("exact", pool)}
    return {
        "cases": len(items), "ran": len(ran),
        "not_run": sum(1 for item in items if not item.get("ran") and not item.get("error")),
        "errors": sum(1 for item in items if item.get("error")),
        "tool_choice": {"ok": count("tool_ok"), "of": len(ran)},
        "arguments": {"ok": count("args_ok", with_args), "of": len(with_args)},
        "arguments_any": {"ok": count("args_ok_any", with_args), "of": len(with_args)},
        "exact": {"ok": count("exact"), "of": len(ran)},
        "by_kind": by_kind,
        "no_card": {"cases": len(no_card), "cards_raised": count("card_raised", no_card),
                    "deadline_cards_raised": count("deadline_card_raised", no_card),
                    "write_attempts": count("write_attempted", no_card)},
        "asked_back": {"cases": len(asked), "question_mark": count("question_mark", asked)},
        "gate_refused": sum(1 for item in ran if item.get("gate_refused")),
        "per_case": {name: verdict for name, verdict in sorted(verdicts.items())},
    }


def replay(path: Path) -> tuple[dict, bool]:
    recorded = json.loads(path.read_text(encoding="utf-8"))
    again = metrics(recorded["items"])
    return again, again == recorded["metrics"]


# ---- the account the cases run against --------------------------------------------------------------


class Fixture:
    """One account built from the set's `fixture`, and the ids its `@names` stand for."""

    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.subject = str(uuid.uuid4())
        self.refs: dict[str, str] = {}

    def problems(self) -> list[str]:
        """What this database lacks: a fixture program, or one of its labelled deadlines."""
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models.program import Program, ProgramDeadline

        problems = []
        with SessionLocal() as session:
            for row in self.spec.get("catalog", []):
                if session.get(Program, row["program_id"]) is None:
                    problems.append(f"@{row['ref']}: no program {row['program_id']} in the catalogue")
                    continue
                for key, label in row.get("deadlines", {}).items():
                    found = session.scalars(select(ProgramDeadline.id).where(
                        ProgramDeadline.program_id == row["program_id"], ProgramDeadline.label == label)).all()
                    if len(found) != 1:
                        problems.append(f"@{row['ref']}.{key}: {len(found)} collected deadlines labelled {label!r}")
        return problems

    def build(self) -> None:
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.deps import load_or_create_profile
        from app.models.program import ProgramDeadline
        from app.services import application_records as records
        from app.services.applications import replace_applications

        with SessionLocal() as session:
            load_or_create_profile(session, self.subject)
            session.commit()
            catalog = self.spec.get("catalog", [])
            replace_applications(session, self.subject, [
                {"program_id": row["program_id"], "tier": row["tier"], "status": row.get("status", "considering"),
                 "is_primary": bool(row.get("primary"))}
                for row in catalog
            ])
            for row in catalog:
                key = f"catalog:{row['program_id']}"
                self.refs[f"@{row['ref']}"] = key
                self.refs[f"@{row['ref']}.program"] = row["program_id"]
                for name, label in row.get("deadlines", {}).items():
                    self.refs[f"@{row['ref']}.{name}"] = session.scalars(select(ProgramDeadline.id).where(
                        ProgramDeadline.program_id == row["program_id"], ProgramDeadline.label == label)).one()
                self._patch(session, key, row.get("record"))
            for row in self.spec.get("manual", []):
                made, _ = records.create_record(
                    session, self.subject, records.RecordCreate(school=row["school"], name=row["name"]), f"eval-{uuid.uuid4().hex}")
                self.refs[f"@{row['ref']}"] = made["id"]
                self._patch(session, made["id"], row.get("record"))
        self.reset_profile()

    def _patch(self, session, key: str, fields: dict | None) -> None:
        from app.services import application_records as records

        if fields:
            base = records.read_record(session, self.subject, key)["version"]
            records.update_record(session, self.subject, key, records.RecordPatch(**fields, base_version=base))

    def reset_profile(self) -> None:
        """Put the profile back: `update_my_profile` writes at once, and the next case must not see it."""
        from app.db import SessionLocal
        from app.deps import load_or_create_profile
        from app.schemas.profile import ProfilePatch

        with SessionLocal() as session:
            profile = load_or_create_profile(session, self.subject)
            for name in ProfilePatch.model_fields:
                setattr(profile, name, self.spec.get("profile", {}).get(name))
            session.commit()

    def snapshot(self) -> list[dict]:
        from app.db import SessionLocal
        from app.services import application_records as records

        with SessionLocal() as session:
            return records.read_records(self.subject, session)

    def remove(self) -> None:
        from app.db import SessionLocal
        from app.services.accounts import delete_subject

        with SessionLocal() as session:
            delete_subject(session, self.subject)
            session.commit()


# ---- the budget ---------------------------------------------------------------------------------------


class BudgetReached(BaseException):
    """The next model call's worst case does not fit in the budget. Not an `Exception`, so the intent
    router's fallback (which catches those) cannot turn it into a routing decision."""


def _price(usage: dict) -> float:
    from app.collect.faithful import cost_cny

    return cost_cny(usage)


class Spend(BaseCallbackHandler):
    """Counts what the run's model calls cost, and refuses a call that might not fit."""

    raise_error = True
    # Checked on the caller's thread, so the refusal stops the call rather than a worker.
    run_inline = True

    def __init__(self, budget_cny: float) -> None:
        self.budget = budget_cny
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
        self.cost = 0.0
        self.calls = 0
        self.unreported = 0
        self._open: dict = {}

    @staticmethod
    def worst_case(messages, invocation_params: dict | None) -> float:
        """An upper bound on one call: two tokens per character of everything sent, at the uncached
        input price, and the whole output cap."""
        from app.config import settings

        params = invocation_params or {}
        def size(value) -> int:
            return len(json.dumps(value, ensure_ascii=False)) if value else 0

        sent = sum(len(str(m.content)) + size(getattr(m, "tool_calls", None)) for batch in messages for m in batch)
        sent += size(params.get("tools"))
        count = sum(len(batch) for batch in messages)
        output_cap = params.get("max_tokens") or (params.get("extra_body") or {}).get("max_tokens") or settings.chat_max_tokens
        return _price({"input_tokens": 2 * sent + 16 * count + 64, "output_tokens": output_cap})

    def on_chat_model_start(self, serialized, messages, *, run_id, invocation_params=None, **kwargs) -> None:
        worst = self.worst_case(messages, invocation_params)
        if self.cost + sum(self._open.values()) + worst > self.budget:
            raise BudgetReached(f"spent {self.cost:.4f} CNY of {self.budget}; the next call could cost {worst:.4f}")
        self._open[run_id] = worst
        self.calls += 1

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        worst = self._open.pop(run_id, 0.0)
        try:
            meta = response.generations[0][0].message.usage_metadata or {}
        except (AttributeError, IndexError):
            meta = {}
        if not meta.get("input_tokens") and not meta.get("output_tokens"):
            self.unreported += 1
            self.cost += worst
            return
        used = {"input_tokens": meta.get("input_tokens", 0), "output_tokens": meta.get("output_tokens", 0),
                "cache_read_tokens": (meta.get("input_token_details") or {}).get("cache_read", 0) or 0}
        for key, value in used.items():
            self.usage[key] += value
        self.cost += _price(used)

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        # A call that failed may still have been billed; it is charged its worst case.
        self.cost += self._open.pop(run_id, 0.0)


# ---- live ---------------------------------------------------------------------------------------------


def _outcome(content: str | None) -> str:
    from app.agent import confirm
    from app.agent.tools import PROFILE_UPDATED

    if content is None:
        return "not_run"
    if content.startswith((confirm.CHANGED, PROFILE_UPDATED)):
        return "wrote"
    if content.startswith(confirm.ALREADY):
        return "already"
    if content.startswith(confirm.DECLINED):
        return "declined"
    if content.startswith((confirm.REFUSED, "未更新：")):
        return "refused"
    return "ok"


def read_turn(values: dict, interrupts, skip: int) -> dict:
    """What a finished or paused turn did, from the thread's state: the calls in order, how each ended,
    the cards, the reply and the route. `skip` is how many messages the turn started with."""
    from langchain_core.messages import AIMessage, ToolMessage

    messages = (values.get("messages") or [])[skip:]
    answers = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    cards = [i.value for i in interrupts if isinstance(i.value, dict)]
    asking = {card.get("tool") for card in cards}
    calls = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for made in message.tool_calls:
            answer = answers.get(made["id"])
            content = answer.content if answer is not None and isinstance(answer.content, str) else None
            outcome = "error" if answer is not None and getattr(answer, "status", None) == "error" else _outcome(content)
            if answer is None and made["name"] in asking:
                outcome = "confirm"
            calls.append({"tool": made["name"], "args": made.get("args") or {}, "outcome": outcome,
                          **({"refusal": content.split("\n", 1)[0]} if outcome == "refused" else {})})
    reply = next((m.content for m in reversed(messages)
                  if isinstance(m, AIMessage) and not m.tool_calls and isinstance(m.content, str)), "")
    trace = values.get("trace") or {}
    return {
        "calls": calls,
        "cards": [{"tool": card.get("tool"), "changes": card.get("changes")} for card in cards],
        "reply": reply,
        "intent": values.get("intent"), "route": trace.get("route"),
        "gate_refused": bool(trace.get("route") in ("requirements", "passages") and not calls and values.get("refusal")
                             and not values.get("evidence_strong")),
    }


async def run_case(graph, fixture: Fixture, case: dict, spend: Spend) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    from app.agent import stated

    # The applicant's turns carry the day they were sent, as the stream stores them.
    history = [HumanMessage(content=turn["content"], additional_kwargs=stated.stamp()) if turn["role"] == "user"
               else AIMessage(content=turn["content"]) for turn in case.get("history", [])]
    config = {"configurable": {"thread_id": f"{fixture.subject}:eval-{case['id']}", "client_id": fixture.subject},
              "callbacks": [spend]}
    item = {"id": case["id"], "kind": case["kind"], "message": case["message"],
            "expected": resolve(case["expect"], fixture.refs), "ran": False}
    before = dict(spend.usage)
    try:
        said = HumanMessage(content=case["message"], additional_kwargs=stated.stamp())
        await graph.ainvoke({"messages": [*history, said], "trace": None}, config)
    except BudgetReached:
        raise
    except Exception as error:  # noqa: BLE001 - one broken case must not end the run
        item["error"] = f"{type(error).__name__}: {str(error)[:200]}"
        return item
    state = await graph.aget_state(config)
    item.update(read_turn(state.values, state.interrupts, skip=len(history) + 1))
    item["ran"] = True
    item["usage"] = {key: spend.usage[key] - before[key] for key in before}
    return item


async def run_live(doc: dict, budget_cny: float, only: set[str] | None = None, progress=sys.stderr) -> dict:
    from langgraph.checkpoint.memory import MemorySaver

    from app.agent.graph import build_graph
    from app.agent.llm import model_configured
    from app.config import settings

    if not model_configured():
        raise SystemExit("CHAT_API_KEY is not set; a live run needs the chat model")
    problems = check_set(doc, coverage=False)
    fixture = Fixture(doc["fixture"])
    problems += fixture.problems()
    if problems:
        raise SystemExit("not running: " + "; ".join(problems))
    cases = [c for c in doc["cases"] if not only or c["id"] in only or c["kind"] in only]
    # A refusal is not a knowledge gap of the catalogue while the eval is asking.
    recording, settings.knowledge_gaps_record = settings.knowledge_gaps_record, False
    spend, items, started, stopped = Spend(budget_cny), [], time.monotonic(), None
    try:
        fixture.build()
        expected_state = fixture.snapshot()
        graph = build_graph(checkpointer=MemorySaver())
        for case in cases:
            try:
                item = await run_case(graph, fixture, case, spend)
            except BudgetReached as reached:
                stopped = str(reached)
                break
            # No card is answered, so the applications must be as they were built.
            item["applications_changed"] = fixture.snapshot() != expected_state
            fixture.reset_profile()
            items.append(item)
            print(json.dumps({"id": case["id"], "calls": [c["tool"] for c in item.get("calls", [])],
                              "cost_so_far": round(spend.cost, 4)}, ensure_ascii=False), file=progress)
            if item["applications_changed"]:
                stopped = f"{case['id']} changed the account's applications; the run cannot go on"
                break
    finally:
        settings.knowledge_gaps_record = recording
        fixture.remove()
    done = {item["id"] for item in items}
    items += [{"id": c["id"], "kind": c["kind"], "message": c["message"], "expected": resolve(c["expect"], fixture.refs),
               "ran": False} for c in cases if c["id"] not in done]
    return {
        "date": date.today().isoformat(), "set": CASES_FILE.name, "chat_model_setting": settings.chat_model,
        "base_url": settings.chat_base_url, "max_agent_steps": settings.max_agent_steps,
        "budget_cny": budget_cny, "stopped": stopped, "model_calls": spend.calls, "calls_without_usage": spend.unreported,
        "tokens": spend.usage, "cost_cny_upper_bound": round(spend.cost, 4),
        "seconds": round(time.monotonic() - started, 1), "items": items, "metrics": metrics(items),
    }


# ---- estimate ------------------------------------------------------------------------------------------


def _tokens(text: str) -> int:
    """A token count for the estimate. `cl100k_base` is not the chat model's tokenizer; it is the one
    this environment has, and the estimate says so."""
    import tiktoken

    return len(tiktoken.get_encoding("cl100k_base").encode(text))


# Output per call, assumed for the estimate: a tool call is a name and a few arguments, a reply a
# short paragraph, the router one function call.
ASSUMED_OUTPUT = {"tool_call": 120, "reply": 300, "intent": 40}
ASSUMED_ARGUMENTS = 60


def estimate(doc: dict) -> dict:
    """Tokens and cost of a live run, computed from the prompts, the tool schemas, the cases and the
    size of what the read tools return for the fixture. Nothing is sent to a model."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from app.agent import evidence, intent
    from app.agent import graph as graph_module
    from app.agent.tools import TOOLS, get_my_applications, get_my_portfolio, get_my_profile, search_programs
    from app.config import settings
    from app.db import SessionLocal

    # The gate logs every refusal as a knowledge gap; here it is only asked how long its evidence is.
    logging.getLogger("leapashore.knowledge_gap").setLevel(logging.ERROR)
    fixture = Fixture(doc["fixture"])
    problems = fixture.problems()
    if problems:
        raise SystemExit("not estimating: " + "; ".join(problems))
    try:
        fixture.build()
        config = {"configurable": {"client_id": fixture.subject}}
        results = {
            "get_my_applications": _tokens(get_my_applications.invoke({}, config=config)),
            "get_my_profile": _tokens(get_my_profile.invoke({}, config=config)),
            "get_my_portfolio": _tokens(get_my_portfolio.invoke({}, config=config)),
            "search_programs": _tokens(search_programs.invoke({"keyword": "帝国理工 Computing"})),
            "update_my_profile": 40,
        }
    finally:
        fixture.remove()
    system = _tokens(graph_module.SYSTEM_PROMPT)
    schemas = _tokens(json.dumps([convert_to_openai_tool(t) for t in TOOLS], ensure_ascii=False))
    router = _tokens(intent._PROMPT.format(history="（无）", query="")) + _tokens(json.dumps(intent.IntentResult.model_json_schema()))
    confirmed = set(graph_module.CONFIRMED_TOOLS)

    low = {"input": 0, "output": 0, "calls": 0}
    evidence_tokens = 0
    with SessionLocal() as session:
        for case in doc["cases"]:
            said = "".join(turn["content"] for turn in case.get("history", [])) + case["message"]
            said_tokens = _tokens(said)
            low["input"] += router + said_tokens
            low["output"] += ASSUMED_OUTPUT["intent"]
            low["calls"] += 1
            # The agent's calls: one per expected tool, each seeing the results before it, and a reply
            # unless the turn stops on a card.
            tools = [_alternatives(element)[0]["tool"] for element in case["expect"]["calls"]]
            seen = 0
            agent_calls = 0
            for tool in tools:
                low["input"] += system + schemas + said_tokens + seen
                low["output"] += ASSUMED_OUTPUT["tool_call"]
                agent_calls += 1
                seen += ASSUMED_ARGUMENTS + results.get(tool, 0)
                if tool in confirmed:
                    break
            else:
                low["input"] += system + schemas + said_tokens + seen
                low["output"] += ASSUMED_OUTPUT["reply"]
                agent_calls += 1
            low["calls"] += agent_calls
            # If the router sends the case to the requirement path, the evidence rides on every agent call.
            gated = evidence.gate(session, case["message"], ranking="fts")
            if gated.get("evidence_strong"):
                evidence_tokens += _tokens(gated.get("evidence") or "") * agent_calls

    miss, out = settings.collect_price_cache_miss, settings.collect_price_output

    def cny(tokens_in: int, tokens_out: int) -> float:
        return round((tokens_in * miss + tokens_out * out) / 1e6, 4)

    worst_calls = len(doc["cases"]) * (1 + settings.max_agent_steps)
    return {
        "cases": len(doc["cases"]),
        "tokenizer": "tiktoken cl100k_base (an approximation: not the chat model's own tokenizer)",
        "prices_cny_per_million": {"input_cache_miss": miss, "output": out, "from": "app/config.py COLLECT_PRICE_*"},
        "measured_tokens": {"system_prompt": system, "tool_schemas": schemas, "intent_prompt_and_schema": router,
                            "tool_results_for_the_fixture": results},
        "assumed_tokens": {"output_per_call": ASSUMED_OUTPUT, "arguments_echoed_per_call": ASSUMED_ARGUMENTS},
        "expected": {
            "model_calls": low["calls"], "input_tokens": low["input"], "output_tokens": low["output"],
            "cost_cny": cny(low["input"], low["output"]),
            "arithmetic": f"({low['input']} x {miss} + {low['output']} x {out}) / 1e6",
        },
        "if_every_gate_passing_case_takes_the_requirement_path": {
            "extra_input_tokens": evidence_tokens,
            "cost_cny": cny(low["input"] + evidence_tokens, low["output"]),
            "arithmetic": f"(({low['input']} + {evidence_tokens}) x {miss} + {low['output']} x {out}) / 1e6",
        },
        "ceiling_before_the_budget": {
            "model_calls": worst_calls,
            "note": f"{len(doc['cases'])} cases x (1 router call + {settings.max_agent_steps} agent calls); "
                    "--budget-cny stops the run before any call that might pass it",
        },
    }


# ---- command line --------------------------------------------------------------------------------------


def _summary(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "per_case"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="the set is well-formed")
    mode.add_argument("--estimate", action="store_true", help="token counts and cost of a live run; calls no model")
    mode.add_argument("--live", action="store_true", help="run every case with the chat model in CHAT_*")
    mode.add_argument("--replay", type=Path, help="recompute the metrics of a recorded run")
    parser.add_argument("--fixture", action="store_true", help="with --check: also resolve the fixture in this database")
    parser.add_argument("--budget-cny", type=float, help="hard cap on a live run's spend; required with --live")
    parser.add_argument("--only", help="with --live: comma-separated kinds or case ids")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    doc = load_set()
    if args.check:
        problems = check_set(doc)
        if args.fixture:
            problems += Fixture(doc["fixture"]).problems()
        kinds = {kind: sum(1 for c in doc["cases"] if c["kind"] == kind) for kind in KINDS}
        print(json.dumps({"cases": len(doc["cases"]), "kinds": kinds, "problems": problems}, ensure_ascii=False))
        return 1 if problems else 0
    if args.replay:
        again, same = replay(args.replay)
        print(json.dumps(_summary(again) | {"matches_recorded": same}, ensure_ascii=False))
        return 0 if same else 1
    if args.estimate:
        print(json.dumps(estimate(doc), ensure_ascii=False, indent=1))
        return 0
    if args.budget_cny is None or args.budget_cny <= 0:
        parser.error("--live needs --budget-cny N (a hard cap on the run's spend)")
    result = asyncio.run(run_live(doc, args.budget_cny, set(args.only.split(",")) if args.only else None))
    out = args.out or HERE / "results" / f"tools-{result['date']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(_summary(result["metrics"]) | {"tokens": result["tokens"], "cost_cny": result["cost_cny_upper_bound"],
                                                    "stopped": result["stopped"], "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
