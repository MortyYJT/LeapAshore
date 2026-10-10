# 第二阶段 M2a（路线图定义入库）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把写死在 `web/lib/roadmap.ts` 的阶段与材料清单搬进数据库，新增签证阶段，并让服务端把它们发给前端。

**Architecture:** 新增两张配置表 `roadmap_phases` 与 `material_templates`，由一份种子脚本从现有 TypeScript 逐条转写。新增 `GET /api/roadmap` 返回定义；任务行在 M2b 加进同一个响应。种子转写的保真度沿用 M1 的做法：提交一份快照 + 一个 Node 对账脚本，防止有人改了前端却忘了改种子。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16 / pytest；Node 24 仅用于对账脚本（只用内置模块）。

**Spec:** `note/superpowers/specs/2026-10-06-stage-2-m2-design.md`
**上位 spec:** `note/superpowers/specs/2026-10-06-stage-2-database-design.md`

## Global Constraints

- 源码注释、docstring、工程文档一律英文；`note/` 下中文规划例外；UI 文案、运行时与测试字符串保持中文 —— 阶段名、材料名都是中文数据，必须原样保留。
- 提交信息遵循 Conventional Commits 1.0.0，**必须有 scope**，**必须有非空英文 body**，body 每条以 `- ` 开头。
- 不允许改写已推送历史，不允许 force-push。每次提交前跑 `git diff --cached --check`。
- **不引入 spec 未列出的依赖**；允许的 Python 依赖仍只有 `fastapi`、`uvicorn[standard]`、`pydantic-settings`、`sqlalchemy`、`alembic`、`psycopg[binary]`、`pytest`、`httpx`；Node 脚本只用内置模块。
- 不提交 `api/.env`、`api/.venv`、`web/.next*`、`.runtime-tools/`。
- 分支：`codex/stage-2-m2a-roadmap-definition`。
- `Numeric` 列一律标注为 `Decimal`（M1 最终修复波已确立），本批没有 Numeric 列但保持同一习惯。
- 每张配置表都要有唯一键，种子必须**幂等**（重跑不产生重复行）。
- **不得凭印象编造材料项或阶段。** 6 个阶段与 **31 个材料项**必须逐条对照 `web/lib/roadmap.ts` 转写；签证阶段是新增内容，必须挂官方来源并且初始状态为 `待核验`。

---

### Task 1: `roadmap_phases` 与 `material_templates` 两张表

**Files:**
- Create: `api/app/models/roadmap.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/<rev>_add_roadmap_definition.py`（autogenerate 后人工校对）
- Create: `api/tests/test_roadmap_model.py`

**Interfaces:**
- Consumes: `app.db.Base`；`app.models.source.Source`（`material_templates.source_id` 指向它）
- Produces: `app.models.roadmap.RoadmapPhase`、`app.models.roadmap.MaterialTemplate`；两者都从 `app.models` 再导出

- [ ] **Step 1: 写失败测试**

`api/tests/test_roadmap_model.py`:

```python
from sqlalchemy import select

from app.models.roadmap import MaterialTemplate, RoadmapPhase


def test_phase_and_material_round_trip(db_session, require_db):
    db_session.add(
        RoadmapPhase(key="selection", title="锁定申请组合", offset_days=330, sort_order=0)
    )
    db_session.flush()
    db_session.add(
        MaterialTemplate(
            key="aca-transcript",
            phase="selection",
            title="本科成绩单",
            detail="中英文对照，需教务处盖章",
            applies_to="all",
            sort_order=0,
        )
    )
    db_session.commit()

    material = db_session.execute(
        select(MaterialTemplate).where(MaterialTemplate.key == "aca-transcript")
    ).scalar_one()
    assert material.phase == "selection"
    # A material with no official basis yet must read as unattributed, not as attributed to nothing.
    assert material.source_id is None

    db_session.delete(material)
    db_session.delete(db_session.get(RoadmapPhase, "selection"))
    db_session.commit()


def test_phase_key_is_unique(db_session, require_db):
    db_session.add(RoadmapPhase(key="dup-check", title="a", offset_days=1, sort_order=0))
    db_session.commit()
    db_session.add(RoadmapPhase(key="dup-check", title="b", offset_days=2, sort_order=1))
    try:
        db_session.commit()
    except Exception:
        db_session.rollback()
    else:
        raise AssertionError("a duplicate phase key was accepted")
    finally:
        db_session.execute(
            select(RoadmapPhase).where(RoadmapPhase.key == "dup-check")
        )
        for row in db_session.execute(
            select(RoadmapPhase).where(RoadmapPhase.key == "dup-check")
        ).scalars():
            db_session.delete(row)
        db_session.commit()


def test_deleting_a_phase_is_refused_while_materials_reference_it(db_session, require_db):
    """A phase with materials must not vanish underneath them."""
    db_session.add(RoadmapPhase(key="fk-check", title="a", offset_days=1, sort_order=0))
    db_session.flush()
    db_session.add(
        MaterialTemplate(key="fk-check-mat", phase="fk-check", title="t", applies_to="all")
    )
    db_session.commit()

    db_session.delete(db_session.get(RoadmapPhase, "fk-check"))
    try:
        db_session.commit()
    except Exception:
        db_session.rollback()
    else:
        raise AssertionError("a phase was deleted while materials still referenced it")
    finally:
        db_session.delete(db_session.get(MaterialTemplate, "fk-check-mat"))
        db_session.delete(db_session.get(RoadmapPhase, "fk-check"))
        db_session.commit()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_roadmap_model.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.roadmap'`。

- [ ] **Step 3: 写模型**

`api/app/models/roadmap.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RoadmapPhase(Base):
    """One stage of the application timeline. Configuration, not applicant data."""

    __tablename__ = "roadmap_phases"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    # Days before the intake date. The interface derives every suggested date from this.
    offset_days: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    materials: Mapped[list["MaterialTemplate"]] = relationship(back_populates="phase_ref")


class MaterialTemplate(Base):
    """One thing to prepare. The applicant's copy of it lives in roadmap_tasks."""

    __tablename__ = "material_templates"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # RESTRICT rather than CASCADE: deleting a phase while materials still point at it would silently
    # drop requirements the applicant is working through.
    phase: Mapped[str] = mapped_column(
        String(32), ForeignKey("roadmap_phases.key", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[str] = mapped_column(String(16), default="all")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Nullable: most materials have no official page yet, and a manufactured one is worse than none.
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sources.id"))

    phase_ref: Mapped[RoadmapPhase] = relationship(back_populates="materials")
```

`api/app/models/__init__.py` 追加导出（保留已有全部名字）：

```python
from app.models.roadmap import MaterialTemplate, RoadmapPhase
```

并把 `"MaterialTemplate"`、`"RoadmapPhase"` 加进 `__all__`。

- [ ] **Step 4: 生成并人工校对迁移**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic revision --autogenerate -m "add roadmap phases and material templates"
```

逐个确认：`material_templates.phase` 的外键是 `ondelete='RESTRICT'`；`source_id` 可空且指向 `sources.id`；两张表的主键正确。**autogenerate 若产出计划没要求的东西，删掉并在报告里说明。**

- [ ] **Step 5: 升降级验证**

```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

- [ ] **Step 6: 跑测试确认通过**

```bash
.venv/bin/pytest tests/test_roadmap_model.py -v
```

Expected: 三个测试全部 PASS。

- [ ] **Step 7: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git checkout -b codex/stage-2-m2a-roadmap-definition
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the roadmap phase and material template tables

- Model the application timeline as configuration rather than applicant data: the phases and the
  materials to prepare become rows the server can serve and the advisor can reference, instead of
  constants compiled into the frontend.
- Make the phase foreign key RESTRICT rather than CASCADE. Deleting a phase while materials still
  point at it would silently drop requirements the applicant is working through.
- Leave the material's source nullable, because most materials have no official page yet and an
  invented citation is worse than a missing one.
- Verified by round-tripping a phase and a material, by asserting a duplicate phase key is refused,
  by asserting a referenced phase cannot be deleted, and by upgrading, downgrading and upgrading again.
EOF
```

---

### Task 2: 把 6 个阶段与 31 个材料从 TypeScript 转写进种子

**Files:**
- Create: `api/app/seed_roadmap.py`
- Create: `api/tests/test_seed_roadmap.py`
- Create: `scripts/roadmap-definition.snapshot.json`
- Create: `scripts/verify-roadmap-mirror.cjs`
- Modify: `api/seed_cli.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `app.models.roadmap.RoadmapPhase`、`MaterialTemplate`；`app.models.source.Source`、`SourceStatus`
- Produces: `app.seed_roadmap.seed_roadmap(session) -> tuple[int, int]`（返回新增的阶段数与材料数，**幂等**）；`scripts/verify-roadmap-mirror.cjs`

- [ ] **Step 1: 先读源文件，不要凭印象**

打开 `web/lib/roadmap.ts`，逐条抄出 `PHASE_DEFS`（6 个阶段，含 `offsetDays`）与 `MATERIALS`（31 个材料项，含 `phase`、`title`、`detail`、`appliesTo` 与顺序）。**计划里不重复这些值**，因为它们必须以源文件为准；转写时逐条核对，并写一张映射表放进报告。

- [ ] **Step 2: 写失败测试**

`api/tests/test_seed_roadmap.py`:

```python
from sqlalchemy import func, select

from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.seed_roadmap import seed_roadmap

PHASE_KEYS = [
    "selection", "academic", "language", "specialized", "submission", "decision", "visa",
]


def _clear(session):
    for row in session.execute(select(MaterialTemplate)).scalars():
        session.delete(row)
    for row in session.execute(select(RoadmapPhase)).scalars():
        session.delete(row)
    session.commit()


def test_seed_is_idempotent(db_session, require_db):
    _clear(db_session)
    first = seed_roadmap(db_session)
    second = seed_roadmap(db_session)
    assert first[0] == 7 and first[1] > 0
    assert second == (0, 0), "re-running the seed must not duplicate rows"


def test_every_phase_is_present(db_session, require_db):
    _clear(db_session)
    seed_roadmap(db_session)
    keys = set(db_session.execute(select(RoadmapPhase.key)).scalars())
    assert set(PHASE_KEYS) <= keys


def test_visa_phase_exists_with_materials(db_session, require_db):
    """The seventh phase is the one the Genuine Student work hangs off."""
    _clear(db_session)
    seed_roadmap(db_session)
    assert db_session.get(RoadmapPhase, "visa") is not None
    count = db_session.execute(
        select(func.count()).select_from(MaterialTemplate).where(MaterialTemplate.phase == "visa")
    ).scalar()
    assert count > 0


def test_every_material_points_at_a_real_phase(db_session, require_db):
    _clear(db_session)
    seed_roadmap(db_session)
    phase_keys = set(db_session.execute(select(RoadmapPhase.key)).scalars())
    orphans = [
        m.key
        for m in db_session.execute(select(MaterialTemplate)).scalars()
        if m.phase not in phase_keys
    ]
    assert orphans == [], f"materials with an unknown phase: {orphans}"


def test_offsets_are_positive_and_descending(db_session, require_db):
    """Later phases must suggest later dates; a sign error would silently invert the timeline."""
    _clear(db_session)
    seed_roadmap(db_session)
    offsets = [
        p.offset_days
        for p in db_session.execute(
            select(RoadmapPhase).order_by(RoadmapPhase.sort_order)
        ).scalars()
    ]
    assert all(o > 0 for o in offsets)
    assert offsets == sorted(offsets, reverse=True)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_seed_roadmap.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.seed_roadmap'`。

- [ ] **Step 4: 写种子**

`api/app/seed_roadmap.py` 的结构（数据照 Step 1 的转写填入）：

```python
"""Seed the roadmap definition.

The six existing phases and their materials mirror web/lib/roadmap.ts, which stays the source of truth
until the annotation stage. The visa phase is new: it is authored here and every material under it
cites the Department of Home Affairs page.
"""

from sqlalchemy.orm import Session

from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source, SourceStatus

GS_SOURCE_URL = (
    "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/"
    "genuine-student-requirement"
)

PHASES = [
    {"key": "selection", "title": "锁定申请组合", "offset_days": 330, "sort_order": 0},
    # …其余五个：academic / language / specialized / submission / decision
    #   —— offset_days 与 title 逐条对照 web/lib/roadmap.ts 的 PHASE_DEFS
    {"key": "visa", "title": "签证与行前", "offset_days": 30, "sort_order": 6},
]

MATERIALS = [
    # 31 条现有材料，逐条对照 web/lib/roadmap.ts 的 MATERIALS 填入：
    # {"key": …, "phase": …, "title": …, "detail": …, "applies_to": …, "sort_order": …}
]

# Authored for the visa phase. Each cites the official page; nothing here is invented from memory.
VISA_MATERIALS = [
    {
        "key": "visa-gs-responses",
        "phase": "visa",
        "title": "GS 问卷逐题作答",
        "detail": "申请表中逐题作答，每题不超过 150 词，且必须使用英文。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "visa-gs-evidence",
        "phase": "visa",
        "title": "GS 支持材料",
        "detail": "成绩单、雇主信息、税单或银行流水等，用于支撑陈述。",
        "applies_to": "all",
        "sort_order": 1,
    },
]


def seed_roadmap(session: Session) -> tuple[int, int]:
    """Insert missing phases and materials. Returns (phases added, materials added)."""
    phases_added = 0
    for row in PHASES:
        if session.get(RoadmapPhase, row["key"]) is None:
            session.add(RoadmapPhase(**row))
            phases_added += 1
    session.flush()

    source = session.query(Source).filter(Source.url == GS_SOURCE_URL).one_or_none()
    if source is None:
        source = Source(
            id="src-gs-requirement",
            url=GS_SOURCE_URL,
            title="Genuine Student requirement",
            publisher="Department of Home Affairs",
            domain="immi.homeaffairs.gov.au",
            status=SourceStatus.UNVERIFIED,
            verified_at=None,
        )
        session.add(source)
        session.flush()

    materials_added = 0
    for row in MATERIALS + VISA_MATERIALS:
        if session.get(MaterialTemplate, row["key"]) is not None:
            continue
        payload = dict(row)
        if payload["phase"] == "visa":
            payload["source_id"] = source.id
        session.add(MaterialTemplate(**payload))
        materials_added += 1

    session.commit()
    return phases_added, materials_added
```

**注意**：那条 GS 来源的 `verified_at` 必须是 `None` —— `scripts/check-no-fake-dates.cjs` 会在 `make test` 里拦下任何硬编码日期。

- [ ] **Step 5: 跑测试确认通过**

```bash
.venv/bin/pytest tests/test_seed_roadmap.py -v
```

Expected: 五个测试全部 PASS。

- [ ] **Step 6: 写对账脚本并对账**

先把 `api/app/seed_roadmap.py` 里的数据导出成 `scripts/roadmap-definition.snapshot.json`，再写 `scripts/verify-roadmap-mirror.cjs`：用 Node 内置模块直接 `import` `web/lib/roadmap.ts`（Node 24 原生支持类型剥离），逐项比对 `PHASES`（key、title、offset_days）与 `MATERIALS`（key、phase、title、detail、applies_to、顺序）。要点：

- 比对**值**，不只比对形状
- 发现零个阶段或零个材料时**必须报失败**，不能报"全部正常"（本仓库已被这种静默通过坑过两次）
- 只比较与 TypeScript 有对应关系的 6 个阶段和 31 个材料；`visa` 阶段是新增的，排除在外并在脚本注释里写明原因

```bash
cd "$(git rev-parse --show-toplevel)"
node scripts/verify-roadmap-mirror.cjs
```

Expected: `OK — 6 phases and 31 materials match web/lib/roadmap.ts`。

**双向验证**：故意把某个 `offset_days` 改错一位，跑脚本，确认它以程序名和字段名报错；然后还原。

- [ ] **Step 7: 接入 `make test` 与命令行**

`Makefile`：新增 `check-roadmap-mirror` 目标，并让 `test` 依赖它（照 `check-programs-mirror` 的写法）。`api/seed_cli.py` 追加调用 `seed_roadmap`，并打印两边的计数。

- [ ] **Step 8: 提交**

```bash
git add api scripts Makefile
git diff --cached --check
git commit -F - <<'EOF'
feat(api): seed the roadmap definition and add the visa phase

- Transcribe the six existing phases and their materials from web/lib/roadmap.ts, keeping every title,
  detail and offset byte-for-byte so the timeline the applicant sees does not move.
- Add the seventh phase for the visa and its two materials, each citing the Department of Home Affairs
  Genuine Student page, because the advisor's review work hangs off this stage and it had no home.
- Leave every sourced material recorded as unverified, so nothing claims a check that has not happened.
- Make the seed idempotent, since it runs on every deployment.
- Add a mirror guard that loads the TypeScript through Node's own type stripping and fails on a
  divergence in any value, and that fails loudly rather than reporting success when it compares nothing.
- Verified by tests covering idempotency, phase presence, the visa phase, orphaned materials and offset
  ordering, plus a deliberate mutation proving the mirror guard reddens.
EOF
```

---

### Task 3: `GET /api/roadmap` 返回定义

**Files:**
- Create: `api/app/schemas/roadmap.py`
- Create: `api/app/routers/roadmap.py`
- Modify: `api/app/main.py`
- Create: `api/tests/test_roadmap_api.py`

**Interfaces:**
- Consumes: `app.models.roadmap`；`app.seed_roadmap.seed_roadmap`；`app.schemas.common._camel`；`app.db.get_session`
- Produces: `GET /api/roadmap` 返回 `{"phases": [...], "materials": [...]}`，camelCase，阶段按 `sort_order`，材料按 `(phase 顺序, sort_order)`

- [ ] **Step 1: 写失败测试**

`api/tests/test_roadmap_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.seed_roadmap import seed_roadmap


def test_returns_every_phase_and_material(require_db, db_session):
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()

    assert len(body["phases"]) == 7
    assert len(body["materials"]) == 33
    assert body["phases"][0]["key"] == "selection"
    assert body["phases"][-1]["key"] == "visa"
    assert set(body["phases"][0]) == {"key", "title", "subtitle", "offsetDays", "sortOrder"}
    assert set(body["materials"][0]) >= {"key", "phase", "title", "detail", "appliesTo"}


def test_visa_materials_carry_their_source(require_db, db_session):
    """An authored requirement must show where it came from; the six transcribed phases need not."""
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()
    visa = [m for m in body["materials"] if m["phase"] == "visa"]
    assert visa, "the visa phase must expose materials"
    assert all(m.get("source") and m["source"]["url"].startswith("https://") for m in visa)
    assert all(m["source"]["status"] == "待核验" for m in visa)


def test_phases_come_back_in_timeline_order(require_db, db_session):
    seed_roadmap(db_session)
    body = TestClient(app).get("/api/roadmap").json()
    offsets = [p["offsetDays"] for p in body["phases"]]
    assert offsets == sorted(offsets, reverse=True), "phases must be ordered by offset, not by key"


def test_does_not_require_a_cookie(require_db, db_session):
    """The definition is shared configuration, not applicant data."""
    seed_roadmap(db_session)
    response = TestClient(app).get("/api/roadmap")
    assert response.status_code == 200
    assert "set-cookie" not in {k.lower() for k in response.headers}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_roadmap_api.py -v
```

Expected: FAIL —— 404。

- [ ] **Step 3: 写模式与路由**

`api/app/schemas/roadmap.py`:

```python
from pydantic import BaseModel, ConfigDict

from app.schemas.common import _camel


class SourceRef(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    url: str
    title: str
    status: str


class PhaseOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    key: str
    title: str
    subtitle: str | None = None
    offset_days: int
    sort_order: int


class MaterialOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    key: str
    phase: str
    title: str
    detail: str | None = None
    applies_to: str
    sort_order: int
    source: SourceRef | None = None


class RoadmapDefinition(BaseModel):
    phases: list[PhaseOut]
    materials: list[MaterialOut]
```

`api/app/routers/roadmap.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source
from app.schemas.roadmap import MaterialOut, PhaseOut, RoadmapDefinition, SourceRef

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])


@router.get("", response_model=RoadmapDefinition)
def read_roadmap(session: Annotated[Session, Depends(get_session)]) -> RoadmapDefinition:
    """Serve the timeline definition.

    Tasks land in the same response in the next batch. The definition is shared configuration, so this
    route deliberately does not read or mint a subject cookie.
    """
    phases = list(
        session.execute(
            select(RoadmapPhase).order_by(RoadmapPhase.sort_order)
        ).scalars()
    )
    materials = list(
        session.execute(
            select(MaterialTemplate).order_by(MaterialTemplate.sort_order)
        ).scalars()
    )
    order = {phase.key: phase.sort_order for phase in phases}
    materials.sort(key=lambda m: (order.get(m.phase, 0), m.sort_order))

    out: list[MaterialOut] = []
    for material in materials:
        source = session.get(Source, material.source_id) if material.source_id else None
        out.append(
            MaterialOut(
                key=material.key,
                phase=material.phase,
                title=material.title,
                detail=material.detail,
                applies_to=material.applies_to,
                sort_order=material.sort_order,
                source=(
                    SourceRef(url=source.url, title=source.title, status=source.status)
                    if source
                    else None
                ),
            )
        )

    return RoadmapDefinition(phases=[PhaseOut.model_validate(p) for p in phases], materials=out)
```

`api/app/main.py` 追加注册 `roadmap.router`（保留已有的 health、profile、programs）。

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/pytest tests/test_roadmap_api.py -v
```

Expected: 四个测试全部 PASS。

- [ ] **Step 5: 跑全量并在浏览器里看一眼**

```bash
cd "$(git rev-parse --show-toplevel)"
make test
cd api && (.venv/bin/uvicorn app.main:app --port 8000 > /tmp/api-m2a.log 2>&1 &) ; sleep 4
curl -s http://127.0.0.1:8000/api/roadmap | python3 -m json.tool | head -30
pkill -f "uvicorn app.main:app"
```

把真实响应体贴一份进报告。

- [ ] **Step 6: 提交**

```bash
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): serve the roadmap definition

- Expose the phases and materials the applicant works through, ordered by the timeline rather than by
  key so a consumer cannot accidentally render the stages out of sequence.
- Carry each material's official source when it has one, so an authored requirement shows where it came
  from while a transcribed one honestly reports none.
- Serve the route without reading or minting a subject cookie: this is shared configuration, and the
  tasks that belong to one applicant arrive in the next batch.
- Verified by tests covering the full definition, the visa materials' sources, timeline ordering, and
  the absence of a cookie, plus a full suite run and a live response body.
EOF
```

---

### Task 4: 前端路由到接口定义（仍在前端计算日期）

**Files:**
- Modify: `web/lib/api.ts`
- Create: `web/lib/roadmap-source.ts`
- Modify: `web/lib/roadmap.ts`
- Modify: `web/app/page.tsx`
- Create: `web/lib/roadmap-source.test.ts`
- Modify: `scripts/e2e-walkthrough.cjs`

**Interfaces:**
- Consumes: `GET /api/roadmap`
- Produces: `web/lib/api.ts` 的 `fetchRoadmapDefinition()`；`web/lib/roadmap.ts` 的 `buildRoadmap` 接受定义参数而不是读模块常量

- [ ] **Step 1: 写失败测试**

`web/lib/roadmap-source.test.ts`:

```typescript
import assert from "node:assert/strict";
import test from "node:test";

import { toPhaseDefs } from "./roadmap-source.ts";

test("maps the served definition onto the shape buildRoadmap already takes", () => {
  const phases = toPhaseDefs({
    phases: [
      { key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 330, sortOrder: 0 },
      { key: "visa", title: "签证与行前", subtitle: null, offsetDays: 30, sortOrder: 6 },
    ],
    materials: [],
  });
  assert.equal(phases.length, 2);
  assert.equal(phases[0].key, "selection");
  assert.equal(phases[0].offsetDays, 330);
});

test("keeps the served order rather than sorting again", () => {
  const phases = toPhaseDefs({
    phases: [
      { key: "b", title: "b", subtitle: null, offsetDays: 10, sortOrder: 1 },
      { key: "a", title: "a", subtitle: null, offsetDays: 20, sortOrder: 0 },
    ],
    materials: [],
  });
  assert.deepEqual(
    phases.map((p) => p.key),
    ["b", "a"],
  );
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/web"
npm test 2>&1 | tail -12
```

Expected: FAIL —— 找不到 `./roadmap-source.ts`。

- [ ] **Step 3: 写适配层**

`web/lib/roadmap-source.ts` 导出 `fetchRoadmapDefinition()` 与纯函数 `toPhaseDefs` / `toMaterialDefs`，把接口的 camelCase 定义映射成 `roadmap.ts` 现有函数接受的形状。**不在这里重新排序** —— 服务端已经按时间线排序，前端再排一次就是第二个真相。

- [ ] **Step 4: 让 `buildRoadmap` 接受定义**

把 `web/lib/roadmap.ts` 的 `PHASE_DEFS` 与 `MATERIALS` 常量改为**默认参数**，`buildRoadmap(profile, completedMaterialIds, now, definition?)`。省略定义时用默认值，这样现有测试与调用点不用改，也保留了离线可用性。

- [ ] **Step 5: 页面接线**

`web/app/page.tsx` 挂载时取一次定义；取到就用它算，取不到就用内置默认值。**接口失败不能让路线图白屏** —— 降级到内置定义并在界面上说明用了本地副本。

- [ ] **Step 6: 加走查断言**

`scripts/e2e-walkthrough.cjs` 增加一句：清空 localStorage 后重载，路线图仍渲染，且阶段数与接口返回的一致。

- [ ] **Step 7: 跑全量**

```bash
cd "$(git rev-parse --show-toplevel)"
make test && make build && make screenshots
```

Expected: 全绿；走查零 JS 错误。

- [ ] **Step 8: 提交**

```bash
git add web scripts
git diff --cached --check
git commit -F - <<'EOF'
feat(web): take the roadmap definition from the server

- Fetch the phases and materials instead of reading them from constants, so the server owns the
  timeline and the advisor can reference the same list.
- Keep the constants as the fallback rather than deleting them: a definition the page cannot fetch must
  not turn the roadmap into a blank screen, and the date arithmetic still runs on the client by design.
- Map the served shape onto what the existing builder already takes, without sorting again, because a
  second ordering rule is a second source of truth.
- Verified with unit tests for the mapping, the full suite, the production build, and a walkthrough
  assertion that the roadmap still renders after browser storage is cleared.
EOF
```

---

## 自检

**spec 覆盖**

| spec 要求 | 任务 |
|---|---|
| §3.4 定义入库、浏览器取 | Task 1、2、4 |
| §3.5 新增签证阶段 | Task 2 |
| §4.1 `roadmap_phases`、`material_templates` | Task 1 |
| §5 `GET /api/roadmap` | Task 3 |
| §7 M2a 批次 | 本计划全部 |
| §8 验收 1（迁移可上可下） | Task 1 |
| §8 验收 8（改动历史） | 属 M2b，不在本批 |

**本批不覆盖**：`roadmap_tasks`、`applications`、`task_events`、`origin` 规则、重算逻辑（M2b/M2c）。

**占位检查**：Task 2 的阶段与材料数据**有意留空**，指令是逐条对照 `web/lib/roadmap.ts` 转写。这是刻意的：那批数据必须与前端逐字一致，凭印象补写会把日期算错，比留空更糟。执行时须逐条核对并把映射表写进报告。

**类型一致性**：`seed_roadmap(session) -> tuple[int, int]` 在 Task 2 定义、Task 3 的测试使用；`_camel` 从 `app.schemas.common` 导入；`PhaseOut` / `MaterialOut` / `RoadmapDefinition` 在 Task 3 内部一致。

## 执行方式

计划完成后请选择：

1. **Subagent-Driven（推荐）** —— 每个任务派一个全新 subagent，任务间审查
2. **Inline Execution** —— 当前会话按批次执行，带检查点

**本计划 4 个任务，建议按任务分批，每批结束停下给你看。**
