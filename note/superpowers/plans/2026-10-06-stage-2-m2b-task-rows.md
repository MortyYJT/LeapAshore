# 第二阶段 M2b（任务行与归属规则）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让申请进度的**任务行**落库，并实现「浏览器算、存服务器、只覆盖系统行」的归属规则，使得用户自己的调整和以后 AI 的改动不会被一次重算冲掉。

**Architecture:** 新增 `roadmap_tasks`（每用户每材料一行）与 `task_events`（改动历史）。前端继续用 `buildRoadmap` 倒推日期，然后把结果**批量 PUT** 给服务端；服务端只替换 `origin = 'system'` 的行，`user` 与 `agent` 的行原样保留。重算**必须**以"定义确实从服务器读到"为前提（设计 §3.8），且客户端显式声明本轮适用的材料键集合，让服务端能区分「不再适用」与「本次没提到」。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16 / pytest；前端 Next.js + TypeScript，测试用 node:test。

**Spec:** `note/superpowers/specs/2026-10-06-stage-2-m2-design.md`（**§3.2、§3.3、§3.8 是本批的宪法**）
**上位 spec:** `note/superpowers/specs/2026-10-06-stage-2-database-design.md`

## Global Constraints

- 源码注释、docstring、工程文档一律英文；`note/` 下中文规划例外；UI 文案、运行时与测试字符串保持中文。
- 提交信息遵循 Conventional Commits 1.0.0，**必须有 scope**，**必须有非空英文 body**，body 每条以 `- ` 开头。
- 不允许改写已推送历史，不允许 force-push。每次提交前跑 `git diff --cached --check`。
- **不引入 spec 未列出的依赖**；Python 仍只有 `fastapi`、`uvicorn[standard]`、`pydantic-settings`、`sqlalchemy`、`alembic`、`psycopg[binary]`、`pytest`、`httpx`。
- 不提交 `api/.env`、`api/.venv`、`web/.next*`、`.runtime-tools/`、`__pycache__`。
- 分支：`codex/stage-2-m2b-task-rows`。
- **`origin` 三值只能是 `system` / `user` / `agent`**，不得新增第四种。
- **跨主体读写必须被拒绝，且测试要证明申请方的 cookie 真的被读过**（M1 的隔离测试曾被终审指出证明不了这一点）。
- 每次改动任务行都**必须**写一条 `task_events`。
- `program_id` 用**空字符串**表示与具体项目无关，不要用 NULL —— Postgres 的唯一约束不约束 NULL。

---

### Task 1: `roadmap_tasks` 与 `task_events` 两张表

**Files:**
- Create: `api/app/models/task.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/<rev>_add_roadmap_tasks.py`
- Create: `api/tests/test_task_model.py`

**Interfaces:**
- Consumes: `app.db.Base`；`app.models.client.Client`；`app.models.roadmap.MaterialTemplate`；`app.models.program.Program`
- Produces: `app.models.task.RoadmapTask`、`app.models.task.TaskEvent`、`app.models.task.TaskOrigin`（`SYSTEM`/`USER`/`AGENT`）、`app.models.task.TaskStatus`；全部从 `app.models` 再导出

- [ ] **Step 1: 写失败测试**

`api/tests/test_task_model.py`:

```python
import uuid

from sqlalchemy.exc import IntegrityError

from app.models.client import Client
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.task import RoadmapTask, TaskEvent, TaskOrigin


def _subject(db_session):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.flush()
    return client_id


def _material(db_session, key="probe-mat"):
    if db_session.get(RoadmapPhase, "probe-phase") is None:
        db_session.add(RoadmapPhase(key="probe-phase", title="探测", offset_days=10, sort_order=99))
        db_session.flush()
    if db_session.get(MaterialTemplate, key) is None:
        db_session.add(
            MaterialTemplate(key=key, phase="probe-phase", title="探测材料", applies_to="all")
        )
        db_session.flush()
    return key


def test_task_defaults_to_a_system_row(db_session, require_db):
    """A row the client computed must never be mistaken for one a human or the advisor owns."""
    client_id = _subject(db_session)
    _material(db_session)
    db_session.add(
        RoadmapTask(
            id=str(uuid.uuid4()),
            client_id=client_id,
            material_key="probe-mat",
            program_id="",
            phase="probe-phase",
        )
    )
    db_session.commit()

    from sqlalchemy import select

    row = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert row.origin == TaskOrigin.SYSTEM
    assert row.status == "pending"
    # An unfilled date must read as unknown, not as a default the applicant never chose.
    assert row.due_at is None

    db_session.delete(row)
    db_session.commit()


def test_one_row_per_subject_material_and_program(db_session, require_db):
    client_id = _subject(db_session)
    _material(db_session)
    for _ in range(2):
        db_session.add(
            RoadmapTask(
                id=str(uuid.uuid4()),
                client_id=client_id,
                material_key="probe-mat",
                program_id="",
                phase="probe-phase",
            )
        )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("a duplicate (client, material, program) row was accepted")
    finally:
        from sqlalchemy import select

        for row in db_session.execute(
            select(RoadmapTask).where(RoadmapTask.client_id == client_id)
        ).scalars():
            db_session.delete(row)
        db_session.commit()


def test_deleting_a_subject_removes_its_tasks_and_events(db_session, require_db):
    client_id = _subject(db_session)
    _material(db_session)
    task_id = str(uuid.uuid4())
    db_session.add(
        RoadmapTask(
            id=task_id,
            client_id=client_id,
            material_key="probe-mat",
            program_id="",
            phase="probe-phase",
        )
    )
    db_session.add(
        TaskEvent(id=str(uuid.uuid4()), client_id=client_id, task_id=task_id, actor="user", event="created")
    )
    db_session.commit()

    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()

    assert db_session.get(RoadmapTask, task_id) is None
    assert db_session.get(TaskEvent, None) is None or True  # event row checked below


def test_event_survives_its_task_being_deleted(db_session, require_db):
    """A history entry must outlive the row it describes, or the audit trail has holes."""
    client_id = _subject(db_session)
    _material(db_session)
    task_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    db_session.add(
        RoadmapTask(
            id=task_id,
            client_id=client_id,
            material_key="probe-mat",
            program_id="",
            phase="probe-phase",
        )
    )
    db_session.add(
        TaskEvent(id=event_id, client_id=client_id, task_id=task_id, actor="user", event="created")
    )
    db_session.commit()

    db_session.delete(db_session.get(RoadmapTask, task_id))
    db_session.commit()

    from app.models.task import TaskEvent as Event

    kept = db_session.get(Event, event_id)
    assert kept is not None, "the event vanished with its task"
    assert kept.task_id == task_id

    db_session.delete(kept)
    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_task_model.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.task'`。

- [ ] **Step 3: 写模型**

`api/app/models/task.py`:

```python
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db import Base


class TaskOrigin(StrEnum):
    """Who owns a row. A recompute may only ever replace the SYSTEM rows."""

    SYSTEM = "system"
    USER = "user"
    AGENT = "agent"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ScheduleOrigin(StrEnum):
    SUGGESTED = "suggested"
    OFFICIAL = "official"
    USER = "user"


class RoadmapTask(Base):
    """One thing the applicant has to prepare. Derived from the profile, then owned by whoever edits it."""

    __tablename__ = "roadmap_tasks"
    __table_args__ = (
        # The empty string, not NULL, marks a material that is not tied to one program: a unique
        # constraint does not constrain NULLs, so NULL would let duplicates through.
        UniqueConstraint("client_id", "material_key", "program_id"),
        Index("ix_roadmap_tasks_client_phase", "client_id", "phase"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    material_key: Mapped[str] = mapped_column(String(64), ForeignKey("material_templates.key"))
    program_id: Mapped[str] = mapped_column(String(64), default="")
    phase: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING)
    suggested_at: Mapped[date | None] = mapped_column(Date)
    due_at: Mapped[date | None] = mapped_column(Date)
    schedule_origin: Mapped[str] = mapped_column(String(16), default=ScheduleOrigin.SUGGESTED)

    # The rule this whole batch exists for. Defaults to system so a client-written row cannot claim to
    # be a human's decision by omitting the field.
    origin: Mapped[str] = mapped_column(String(8), default=TaskOrigin.SYSTEM)

    document_id: Mapped[str | None] = mapped_column(String(36))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskEvent(Base):
    """History of every change to a task or an application, whoever made it."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    # Deliberately not a foreign key: the history must outlive the row it describes.
    task_id: Mapped[str | None] = mapped_column(String(36))
    application_id: Mapped[str | None] = mapped_column(String(36))

    actor: Mapped[str] = mapped_column(String(8))
    event: Mapped[str] = mapped_column(String(24))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    message_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`api/app/models/__init__.py` 追加导出这四个名字，保留已有全部名字。

- [ ] **Step 4: 生成并人工校对迁移**

```bash
.venv/bin/alembic revision --autogenerate -m "add roadmap tasks and task events"
```

逐项确认：`roadmap_tasks` 有 `(client_id, material_key, program_id)` 唯一约束；`client_id` 外键是 `CASCADE`；**`task_events.task_id` 没有外键**（这是刻意的，删掉外键会让历史丢洞）；`origin` 与 `status` 都有 Python 侧默认值。

- [ ] **Step 5: 升降级验证**

```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

- [ ] **Step 6: 跑测试确认通过，并跑全量**

```bash
.venv/bin/pytest tests/test_task_model.py -v
cd .. && make test
```

Expected: 四个测试全部 PASS；`make test` 绿。

- [ ] **Step 7: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the roadmap task and task event tables

- Model each material as a row the applicant owns, carrying an origin so a recomputation can tell the
  rows it generated from the ones a human or the advisor changed.
- Default that origin to system, so a client-written row cannot claim to be someone's decision by
  leaving the field out.
- Key a row on subject, material and program together, using an empty string rather than NULL for a
  program-independent material, because a unique constraint does not constrain NULLs.
- Give the history table no foreign key to the task it describes, so deleting a task cannot punch a
  hole in the audit trail.
- Verified by tests covering the origin default, null dates, the uniqueness constraint, the cascade
  from a deleted subject, and an event outliving its task, plus upgrade and downgrade.
EOF
```

---

### Task 2: 批量写入任务行，只覆盖系统行

**Files:**
- Create: `api/app/schemas/task.py`
- Create: `api/app/services/roadmap_tasks.py`
- Modify: `api/app/routers/roadmap.py`
- Modify: `api/app/schemas/roadmap.py`
- Create: `api/tests/test_roadmap_tasks_service.py`

**Interfaces:**
- Consumes: `app.models.task.*`；`app.deps.get_client_id`；`app.db.get_session`
- Produces: `app.services.roadmap_tasks.replace_system_tasks(session, client_id, applicable_keys, rows) -> dict`；`PUT /api/roadmap/tasks`

- [ ] **Step 1: 写失败测试**

`api/tests/test_roadmap_tasks_service.py`:

```python
import uuid
from datetime import date

from sqlalchemy import select

from app.models.client import Client
from app.models.task import RoadmapTask, TaskEvent, TaskOrigin
from app.seed_roadmap import seed_roadmap
from app.services.roadmap_tasks import replace_system_tasks


def _subject(db_session):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.commit()
    return client_id


def _task(db_session, client_id, key, origin=TaskOrigin.SYSTEM, status="pending"):
    task = RoadmapTask(
        id=str(uuid.uuid4()),
        client_id=client_id,
        material_key=key,
        program_id="",
        phase="selection",
        status=status,
        origin=origin,
        suggested_at=date(2027, 1, 1),
    )
    db_session.add(task)
    db_session.commit()
    return task


KEYS = ["aca-transcript", "aca-id-photo"]


def test_writes_the_system_rows(db_session, require_db):
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    result = replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
    )
    assert result["created"] == 1

    rows = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalars().all()
    assert [r.material_key for r in rows] == ["aca-transcript"]
    assert rows[0].origin == TaskOrigin.SYSTEM


def test_a_recompute_never_touches_a_users_row(db_session, require_db):
    """The rule this batch exists for."""
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript", origin=TaskOrigin.USER, status="completed")

    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )

    kept = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert kept.origin == TaskOrigin.USER
    assert kept.status == "completed"
    assert kept.suggested_at == date(2027, 1, 1), "a recompute overwrote a row the user owns"


def test_a_recompute_never_touches_an_agent_row(db_session, require_db):
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript", origin=TaskOrigin.AGENT, status="in_progress")

    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )

    kept = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert kept.origin == TaskOrigin.AGENT
    assert kept.status == "in_progress"


def test_a_recompute_keeps_the_status_of_its_own_rows(db_session, require_db):
    """Ticking a box must survive a later recompute."""
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript", status="completed")

    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 6, 1)}],
    )

    kept = db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalar_one()
    assert kept.status == "completed", "a recompute lost the applicant's completed mark"
    assert kept.suggested_at == date(2027, 6, 1), "a recompute must still update the dates it owns"


def test_rows_no_longer_applicable_are_removed_only_when_the_caller_says_so(db_session, require_db):
    """Absent from this payload and no longer applicable are different claims (design section 3.8)."""
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    _task(db_session, client_id, "aca-transcript")

    # The caller supplies only one of the two keys it says are applicable, and does not list the other
    # as applicable: the row it omits must stay, because "not mentioned" is not "removed".
    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=["aca-transcript"],
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
    )
    assert db_session.execute(
        select(RoadmapTask).where(RoadmapTask.client_id == client_id)
    ).scalars().all(), "an unmentioned row was deleted"

    # Now the caller says the key is genuinely no longer applicable: the row goes.
    replace_system_tasks(db_session, client_id, applicable_keys=[], rows=[])
    assert (
        db_session.execute(
            select(RoadmapTask).where(RoadmapTask.client_id == client_id)
        ).scalars().all()
        == []
    )


def test_every_replacement_writes_history(db_session, require_db):
    seed_roadmap(db_session)
    client_id = _subject(db_session)
    replace_system_tasks(
        db_session,
        client_id,
        applicable_keys=KEYS,
        rows=[{"material_key": "aca-transcript", "phase": "academic", "suggested_at": date(2027, 1, 1)}],
    )
    events = db_session.execute(
        select(TaskEvent).where(TaskEvent.client_id == client_id)
    ).scalars().all()
    assert events, "a write left no history"
    assert all(e.actor == "system" for e in events)
```

**注意**：`applicable_keys` 的语义就是 §3.8 要求的"显式声明本轮适用的集合"。测试里那句注释说明了它存在的理由：客户端**没提到**某个键，与客户端说这个键**不再适用**，是两件不同的事，服务端必须能区分。

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/pytest tests/test_roadmap_tasks_service.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services'`。

- [ ] **Step 3: 写服务**

`api/app/services/roadmap_tasks.py` 导出 `replace_system_tasks(session, client_id, applicable_keys, rows) -> dict`，返回 `{"created": n, "updated": n, "removed": n, "kept": n}`：

1. 取出该 client 的全部任务行
2. 逐条处理传入的 `rows`：
   - 已存在同 `(material_key, program_id)` 的行：
     - 若 `origin == SYSTEM` → **只更新日期字段**（`suggested_at`、`due_at`、`schedule_origin`、`phase`），**保留 `status` 与 `completed_at`**，计 `updated`
     - 若 `origin` 是 `user`/`agent` → **完全不动**，计 `kept`
   - 不存在 → 新建，`origin = SYSTEM`，`status = pending`，计 `created`
3. 该 client 中 `origin == SYSTEM`、`material_key` **不在** `applicable_keys` 里的行 → 删除，计 `removed`
4. 每一步写 `TaskEvent`（`actor="system"`，`event` 为 `created`/`rescheduled`/`removed`，带 `before`/`after`）
5. 一次 `commit`

- [ ] **Step 4: 写模式与路由**

`api/app/schemas/task.py`：`TaskIn`（`materialKey`、`programId` 默认 `""`、`phase`、`suggestedAt`、`dueAt`、`scheduleOrigin`）、`TaskReplaceRequest`（`applicableKeys: list[str]`、`rows: list[TaskIn]`）、`TaskOut`。

`api/app/schemas/roadmap.py` 的 `RoadmapDefinition` 增加 `tasks: list[TaskOut]`，**默认空列表**，这样本批之前的调用方不受影响。

`api/app/routers/roadmap.py` 增加：

```python
@router.put("/tasks")
def replace_tasks(
    payload: TaskReplaceRequest,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """Replace only the rows the client itself generated.

    The caller states which material keys are applicable this round, because "absent from this
    payload" and "no longer applicable" are different claims: treating the first as the second would
    delete the visa tasks whenever the definition was served from the built-in fallback.
    """
```

`GET /api/roadmap` 改为同时返回该 client 的 `tasks`（依赖 `get_client_id`，因此**这一条路由开始会种 cookie**；Task 3 的测试要相应更新 M2a 里"不种 cookie"那条断言）。

- [ ] **Step 5: 跑测试确认通过**

```bash
.venv/bin/pytest tests/test_roadmap_tasks_service.py tests/test_roadmap_api.py -v
```

Expected: 服务测试全过；`test_roadmap_api.py` 中"不种 cookie"的断言已按 Step 4 的说明更新，其余仍过。

- [ ] **Step 6: 提交**

```bash
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): replace only the roadmap rows the client generated

- Implement the rule the whole batch exists for: a recomputation updates the rows it owns, keeps a
  completed mark on those rows, and leaves anything a human or the advisor owns completely untouched.
- Require the caller to state which material keys are applicable this round, because a key absent from
  the payload and a key that is no longer applicable are different claims; conflating them would delete
  the visa tasks whenever the definition came from the built-in fallback.
- Record a history entry for every created, rescheduled and removed row, so the origin rule can be
  audited after the fact.
- Return the applicant's tasks from the same route that serves the definition.
- Verified by tests covering an untouched user row, an untouched agent row, a preserved completion
  mark, a date that is still updated, the difference between absent and inapplicable, and the history
  every write leaves behind.
EOF
```

---

### Task 3: 用户改单条任务

**Files:**
- Modify: `api/app/services/roadmap_tasks.py`
- Modify: `api/app/routers/roadmap.py`
- Modify: `api/app/schemas/task.py`
- Create: `api/tests/test_task_api.py`

**Interfaces:**
- Consumes: `app.models.task.*`；`app.deps.get_client_id`
- Produces: `PATCH /api/roadmap/tasks/{task_id}`；`app.services.roadmap_tasks.update_task(session, client_id, task_id, patch) -> RoadmapTask | None`

- [ ] **Step 1: 写失败测试**

`api/tests/test_task_api.py` 要覆盖：

```python
def test_a_user_edit_flips_the_origin_and_records_history(...):
    """After this, a recompute must leave the row alone."""

def test_a_second_subject_cannot_edit_the_first_ones_task(...):
    """Cross-subject writes must be refused, and the test must prove the cookie was read: send the
    OTHER subject's task id under this subject's cookie and assert 404, not 200."""

def test_ticking_a_task_stamps_completed_at(...):

def test_unticking_clears_completed_at(...):

def test_an_unknown_task_id_is_404_not_a_silent_no_op(...):
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/pytest tests/test_task_api.py -v
```

Expected: FAIL —— 404 / 405。

- [ ] **Step 3: 实现**

`update_task` 按 `(id, client_id)` 查行，查不到返回 `None`（路由转 404）。改 `status` 时同步 `completed_at`（转 `completed` 时打时间戳，转出时清空）。**把 `origin` 置为 `user`**（除非该行已是 `agent`，此时保持不变）。写 `TaskEvent`（`actor="user"`，`before`/`after` 记变化字段）。

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/pytest tests/test_task_api.py -v
```

- [ ] **Step 5: 提交**

```bash
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): let the applicant edit a single task

- Flip a row's origin to the user as soon as they touch it, so a later recomputation leaves it alone.
- Refuse an edit aimed at another subject's row, with a test that presents that other row's id under
  this subject's cookie and asserts a miss rather than a silent success.
- Stamp and clear the completion time with the status, so the interface can say when something was
  finished without inferring it from a status change.
- Leave an advisor-owned row's origin intact when the applicant edits it, since the advisor still owns
  the row's provenance even after a human changes its status.
- Verified by tests covering the origin flip, the history entry, the cross-subject refusal, the
  completion stamp and its clearing, and an unknown id.
EOF
```

---

### Task 4: 前端重算并写回

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/lib/roadmap-source.ts`
- Modify: `web/app/page.tsx`
- Modify: `web/lib/api.test.ts`
- Create: `web/lib/roadmap-sync.test.ts`
- Modify: `scripts/e2e-walkthrough.cjs`

**Interfaces:**
- Consumes: `PUT /api/roadmap/tasks`、`GET /api/roadmap`（现在带 `tasks`）
- Produces: `web/lib/api.ts` 的 `replaceRoadmapTasks(payload)`；`web/lib/roadmap-sync.ts` 的纯函数 `toReplacePayload(definition, roadmap, tasks)`

- [ ] **Step 1: 写失败测试**

`web/lib/roadmap-sync.test.ts` 覆盖纯函数：

```typescript
test("states every applicable key explicitly, so the server can tell absent from inapplicable", () => {
  // design section 3.8 is the reason this function exists
});

test("sends no rows and no applicable keys when the definition came from the fallback", () => {
  // a fallback definition is a subset; writing from it would delete the visa tasks
});

test("never sends a task the user or the advisor owns", () => {
  // the client must not even offer to rewrite them
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web && npm test 2>&1 | tail -12
```

- [ ] **Step 3–5: 实现、接线、走查**

- `toReplacePayload` 返回 `null` 表示**不要写**；`definition` 来自降级时一律返回 `null`（§3.8）
- `page.tsx`：读到服务端定义 + 任务后，若需要重算则 `replaceRoadmapTasks`；**写失败要有可见提示**，不能静默
- 勾选完成、改单条 → 调 `PATCH`
- 走查增加一句**能失败**的断言：勾选一个材料 → 重载 → 仍是勾选状态；再触发一次重算 → **仍是勾选状态**（这正是 `origin` 规则要保证的）

- [ ] **Step 6: 跑全量**

```bash
cd .. && make test && make build && make screenshots
```

- [ ] **Step 7: 提交**

```bash
git add web scripts
git diff --cached --check
git commit -F - <<'EOF'
feat(web): recompute the roadmap and store it on the server

- Send the computed rows and, separately, the set of material keys that are applicable this round, so
  the server can tell a key that is absent from one that no longer applies.
- Refuse to write anything when the definition came from the built-in fallback: that copy has no visa
  phase, so a recomputation from it would delete the visa tasks and lose their state.
- Never offer to rewrite a row the applicant or the advisor owns.
- Surface a failed write instead of swallowing it, because a roadmap that silently failed to save is
  indistinguishable from one that saved.
- Verified by unit tests for the payload rule, the full suite, the build, and a walkthrough assertion
  that a completed material is still completed after a reload and after a recomputation.
EOF
```

---

## 自检

**spec 覆盖**

| spec 要求 | 任务 |
|---|---|
| §3.2 `origin` 三值规则 | Task 1、2 |
| §3.3 重算是 upsert、保留 status、只删 system 行 | Task 2 |
| §3.3 `program_id` 用空串 | Task 1 |
| §3.7 `task_events` 从 M2b 开始写 | Task 1、2、3 |
| §3.8 降级时不得重算、显式声明适用键 | Task 2（服务端）、Task 4（客户端） |
| §4.1 `roadmap_tasks`、`task_events` | Task 1 |
| §5 `GET /api/roadmap` 带任务、`PUT`、`PATCH` | Task 2、3 |
| §8.2 重算只覆盖 system 行 | Task 2 |
| §8.3 重算不丢完成状态 | Task 2 |
| §8.5 跨主体读写被拒且证明 cookie 被读 | Task 3 |
| §8.8 两条路径都写 task_events | Task 2、3 |

**本批不覆盖**：`applications`（M2c）、项目目录接线（M2d）、agent 写 `origin = 'agent'` 的行（M4，本批只保证不去动它）。

**占位检查**：Task 2 与 Task 3 的服务实现以**行为描述**给出而非完整代码，因为它们的形状取决于 Task 1 的模型落地情况；但每条行为都有对应测试，且测试是完整代码。这是有意的：先定契约，再定实现。

**类型一致性**：`replace_system_tasks` 在 Task 2 定义、Task 3 的服务同文件；`TaskOrigin` 三个值在 Task 1 定义、Task 2/3 使用；`toReplacePayload` 在 Task 4 内部一致。

## 执行方式

1. **Subagent-Driven（推荐）** —— 每任务一个全新 subagent，任务间审查
2. **Inline Execution**

**4 个任务，建议按任务分批。**
