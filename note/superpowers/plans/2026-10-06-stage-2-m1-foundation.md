# 第二阶段 M1（基础层）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建起后端骨架与数据库基础层，让档案与项目数据落库，前端档案页改为读写服务端。

**Architecture:** FastAPI + SQLAlchemy 2.0 + Alembic，PostgreSQL 跑在 Docker 里。匿名主体用 cookie 里的 `client_id` 标识，不加登录。项目数据由一份 Python 种子脚本从现有 `web/lib/programs.ts` 导入。来源治理统一成 `sources` + `source_versions` 两张表，项目与（后续的）审核要点都指向它。

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / SQLAlchemy 2.0 / Alembic / psycopg3 / pytest / PostgreSQL 16 (Docker)

**Spec:** `note/superpowers/specs/2026-10-06-stage-2-database-design.md`

## Global Constraints

- 源码注释、docstring、工程文档一律英文；`note/` 下的中文规划记录例外；UI 文案、运行时与测试字符串保持中文。
- 提交信息遵循 Conventional Commits 1.0.0，**必须有 scope**，**必须有非空英文 body**，body 每行以 `- ` 开头。
- 不允许改写已推送的历史；不允许 force-push；每次提交前跑 `git diff --cached --check`。
- **不引入 spec 未列出的依赖。** 本计划允许的依赖仅：`fastapi`、`uvicorn[standard]`、`pydantic-settings`、`sqlalchemy`、`alembic`、`psycopg[binary]`、`pytest`、`httpx`。
- Python 用**项目本地 venv**，不碰系统 3.9，不装全局包。
- `clients` 与 `profiles` 的跨主体读取必须被拒绝；**任何用户数据表都要有主体隔离测试**。
- `sources.verified_at` 允许为空；**代码与种子数据里不允许出现硬编码的核验日期**。
- 前端 `web/lib/types.ts` 的字段是 camelCase，数据库是 snake_case；映射只在 API 边界做一次。
- 分支：`codex/stage-2-m1-foundation`。

---

### Task 1: 后端骨架与 Python 环境

**Files:**
- Create: `api/pyproject.toml`
- Create: `api/app/__init__.py`
- Create: `api/app/main.py`
- Create: `api/tests/__init__.py`
- Create: `api/tests/test_health.py`
- Create: `api/.gitignore`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces: `app.main:app`（FastAPI 实例）；`make api-install`、`make api-test`、`make api-dev`；约定的测试命令 `api/.venv/bin/pytest`

- [ ] **Step 1: 安装 uv 到项目本地工具目录**

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p .runtime-tools
curl -sL "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz" -o /tmp/uv.tgz
tar -xzf /tmp/uv.tgz -C .runtime-tools
find .runtime-tools -name uv -type f -perm +111 | head -1
```

Expected: 打印出 `uv` 的可执行路径，例如 `.runtime-tools/uv-aarch64-apple-darwin/uv`。

- [ ] **Step 2: 建项目本地 venv（Python 3.12）**

```bash
cd "$(git rev-parse --show-toplevel)"
UV=$(find .runtime-tools -name uv -type f -perm +111 | head -1)
"$UV" venv --python 3.12 api/.venv
api/.venv/bin/python -V
```

Expected: `Python 3.12.x`。

- [ ] **Step 3: 写依赖清单**

`api/pyproject.toml`:

```toml
[project]
name = "offerpilot-api"
version = "0.1.0"
description = "OfferPilot backend"
requires-python = ">=3.12"

dependencies = [
  "fastapi",
  "uvicorn[standard]",
  "pydantic-settings",
  "sqlalchemy",
  "alembic",
  "psycopg[binary]",
]

[project.optional-dependencies]
test = ["pytest", "httpx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: 安装依赖**

```bash
cd "$(git rev-parse --show-toplevel)/api"
UV=$(find ../.runtime-tools -name uv -type f -perm +111 | head -1)
"$UV" pip install --python .venv/bin/python -e ".[test]"
```

Expected: 安装成功，无错误。

- [ ] **Step 5: 写失败测试**

`api/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_ok():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_health.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.main'`。

- [ ] **Step 7: 写最小实现**

`api/app/__init__.py`（空文件）

`api/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="OfferPilot API")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Kept dependency-free so it works before the database exists."""
    return {"status": "ok"}
```

- [ ] **Step 8: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_health.py -v
```

Expected: PASS。

- [ ] **Step 9: 加忽略规则**

`api/.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

在根 `.gitignore` 末尾追加：

```
# 后端本地环境与缓存
api/.venv/
__pycache__/
.pytest_cache/
```

- [ ] **Step 10: 加 Makefile 目标**

在 `offerpilot/Makefile` 的 `.PHONY` 行加入 `api-install api-test api-dev`，并追加：

```make
api-install: ## Create the backend venv and install its dependencies
	cd api && ../$(shell find ../.runtime-tools -name uv -type f -perm +111 | head -1) pip install --python .venv/bin/python -e ".[test]"

api-test: ## Run the backend tests
	cd api && .venv/bin/pytest -q

api-dev: ## Start the backend dev server on :8000
	cd api && .venv/bin/uvicorn app.main:app --reload --port 8000
```

同时把 `api-test` 加进 `test` 目标，把 `api-install` 加进 `install` 目标。

- [ ] **Step 11: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git checkout -b codex/stage-2-m1-foundation
git add api Makefile .gitignore
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the backend skeleton with a health endpoint

- Introduce a FastAPI application under api/ with a dependency-free health route, so the service can
  be started and probed before any database work lands.
- Pin the backend to a project-local Python 3.12 virtual environment. The system interpreter is 3.9,
  which is too old for the current SQLAlchemy and Pydantic releases.
- Install uv into the ignored .runtime-tools directory rather than onto the system path, matching how
  the GitHub CLI was added.
- Add make targets for installing, testing and running the backend.
- Verified by running the health test: it failed with ModuleNotFoundError before the implementation
  and passes after.
EOF
```

---

### Task 2: PostgreSQL 容器、连接与 Alembic

**Files:**
- Create: `compose.yaml`
- Create: `api/app/config.py`
- Create: `api/app/db.py`
- Create: `api/alembic.ini`
- Create: `api/alembic/env.py`
- Create: `api/alembic/script.py.mako`
- Create: `api/tests/conftest.py`
- Create: `api/tests/test_db.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `app.main:app`
- Produces: `app.config.settings`（含 `database_url`）；`app.db.Base`（DeclarativeBase）；`app.db.engine`；`app.db.SessionLocal`；pytest fixture `db_session`、`alembic_config`

- [ ] **Step 1: 写 compose 文件**

`compose.yaml`:

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: offerpilot
      POSTGRES_PASSWORD: offerpilot
      POSTGRES_DB: offerpilot
    ports:
      - "55432:5432"
    volumes:
      - offerpilot-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U offerpilot"]
      interval: 3s
      timeout: 3s
      retries: 20

volumes:
  offerpilot-db:
```

端口用 **55432** 而不是 5432，避免和机器上已有的数据库冲突。

- [ ] **Step 2: 启动数据库并确认健康**

```bash
cd "$(git rev-parse --show-toplevel)"
docker compose up -d db
docker compose ps
```

Expected: `db` 状态为 `running (healthy)`。

- [ ] **Step 3: 写配置**

`api/app/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or from api/.env."""

    database_url: str = "postgresql+psycopg://offerpilot:offerpilot@localhost:55432/offerpilot"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
```

把 `api/.env` 加进 `api/.gitignore`。

- [ ] **Step 4: 写数据库会话**

`api/app/db.py`:

```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for every model. Alembic reads metadata from here."""


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency. One session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 5: 写失败测试**

`api/tests/conftest.py`:

```python
import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine


@pytest.fixture
def db_session():
    """A session bound to the real development database.

    M1 has no test database yet: the schema is small and the container is disposable, so tests run
    against the same database the developer uses and clean up after themselves.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def require_db():
    """Skip instead of failing when the container is not running."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception:  # noqa: BLE001 - any connection failure means "not available"
        pytest.skip("database container is not running")
```

`api/tests/test_db.py`:

```python
from sqlalchemy import text


def test_database_is_reachable(db_session, require_db):
    assert db_session.execute(text("select 1")).scalar() == 1
```

- [ ] **Step 6: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_db.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.config'`（此时还没写 `config.py`/`db.py` 的话；若已按上文写完，则此步应先临时把 `db.py` 改名再跑，确认测试真的会失败，然后改回）。

- [ ] **Step 7: 初始化 Alembic**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic init -t generic alembic
```

然后修改 `api/alembic/env.py`，把 `target_metadata` 指向我们的 Base：

```python
from app.config import settings
from app.db import Base
import app.models  # noqa: F401 - imported so autogenerate sees every table

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata
```

同时在 `api/alembic.ini` 里把 `sqlalchemy.url` 留空（由 `env.py` 注入），避免连接串写死在两个地方。

创建 `api/app/models/__init__.py`（本任务先留空，Task 3 起往里加）。

- [ ] **Step 8: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_db.py -v
```

Expected: PASS。

- [ ] **Step 9: 加 Makefile 目标**

```make
db-up: ## Start the database container
	docker compose up -d db

db-down: ## Stop the database container
	docker compose down

migrate: ## Apply database migrations
	cd api && .venv/bin/alembic upgrade head

revision: ## Generate a migration, e.g. make revision m="add profiles"
	cd api && .venv/bin/alembic revision --autogenerate -m "$(m)"
```

把 `db-up` 加进 `dev` 目标的前置。

- [ ] **Step 10: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add compose.yaml api Makefile
git diff --cached --check
git commit -F - <<'EOF'
build(api): add the postgres container, session layer and alembic wiring

- Run PostgreSQL 16 in a container on port 55432, so the development database cannot collide with an
  existing server on the default port.
- Add a settings object and a declarative base. Alembic reads its metadata and its connection string
  from the same place the application does, so the URL is not duplicated between code and config.
- Add a session dependency that always closes, and a test fixture that skips rather than fails when
  the container is not running.
- Verified by starting the container, confirming it reports healthy, and running the connectivity
  test.
EOF
```

---

### Task 3: clients 与 profiles

**Files:**
- Create: `api/app/models/client.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/<rev>_add_clients_and_profiles.py`（由 autogenerate 生成后人工校对）
- Create: `api/tests/test_profile_model.py`

**Interfaces:**
- Consumes: `app.db.Base`
- Produces: `app.models.client.Client`（`id: str`、`created_at`、`last_seen_at`）；`app.models.client.Profile`（`client_id` 主键 + 档案字段）；`app.models.client.new_client_id() -> str`

- [ ] **Step 1: 写失败测试**

`api/tests/test_profile_model.py`:

```python
import uuid

from sqlalchemy import select

from app.models.client import Client, Profile


def test_client_and_profile_round_trip(db_session, require_db):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.add(Profile(client_id=client_id, school_name="北京邮电大学", domestic_tier="211"))
    db_session.commit()

    row = db_session.execute(
        select(Profile).where(Profile.client_id == client_id)
    ).scalar_one()
    assert row.school_name == "北京邮电大学"
    assert row.domestic_tier == "211"
    # Fields the applicant never filled in stay null rather than defaulting to a guess.
    assert row.gpa_score is None

    db_session.delete(row)
    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()


def test_deleting_a_client_removes_its_profile(db_session, require_db):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.add(Profile(client_id=client_id))
    db_session.commit()

    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()

    assert db_session.get(Profile, client_id) is None
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_profile_model.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.client'`。

- [ ] **Step 3: 写模型**

`api/app/models/client.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_client_id() -> str:
    """Anonymous subject id. Lives in a cookie until real accounts exist."""
    return str(uuid.uuid4())


class Client(Base):
    """An anonymous applicant. Upgrades to a real account later without moving the profile."""

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="client", cascade="all, delete-orphan")


class Profile(Base):
    """The applicant's background. One row per client."""

    __tablename__ = "profiles"

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )

    current_education_level: Mapped[str | None] = mapped_column(String(32))
    school_origin: Mapped[str | None] = mapped_column(String(16))
    school_name: Mapped[str | None] = mapped_column(String(128))
    domestic_tier: Mapped[str | None] = mapped_column(String(16))
    overseas_band: Mapped[str | None] = mapped_column(String(32))
    major: Mapped[str | None] = mapped_column(String(64))
    gpa_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    gpa_scale: Mapped[float | None] = mapped_column(Numeric(5, 2))
    target_degree_level: Mapped[str | None] = mapped_column(String(32))
    target_field: Mapped[str | None] = mapped_column(String(64))
    intake: Mapped[str | None] = mapped_column(String(16))
    english_score: Mapped[str | None] = mapped_column(String(64))
    annual_budget_cny: Mapped[float | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    client: Mapped[Client] = relationship(back_populates="profile")
```

`api/app/models/__init__.py`:

```python
from app.models.client import Client, Profile

__all__ = ["Client", "Profile"]
```

- [ ] **Step 4: 生成迁移**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic revision --autogenerate -m "add clients and profiles"
```

**人工校对生成的迁移**：确认 `ondelete="CASCADE"` 出现在外键上，确认 `gpa_score` 是 `Numeric(5, 2)` 且 `nullable=True`。

- [ ] **Step 5: 应用迁移**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
```

Expected: 三次都成功。**降级必须能跑通**，这是验收标准之一。

- [ ] **Step 6: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_profile_model.py -v
```

Expected: 两个测试都 PASS。

- [ ] **Step 7: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the anonymous client and profile tables

- Model the applicant as an anonymous client identified by a generated id, with the profile hanging
  off it. This keeps the data genuinely per-applicant without introducing a login screen.
- Cascade profile deletion from the client, so removing a subject cannot leave an orphaned profile
  behind.
- Leave every unfilled profile field nullable. A missing mark must read as unknown rather than as a
  default the applicant never chose.
- Verified by round-tripping a profile, by asserting an unfilled field stays null, by asserting the
  cascade, and by upgrading, downgrading and upgrading again.
EOF
```

---

### Task 4: 档案读写接口与主体隔离

**Files:**
- Create: `api/app/deps.py`
- Create: `api/app/schemas/profile.py`
- Create: `api/app/routers/__init__.py`
- Create: `api/app/routers/profile.py`
- Modify: `api/app/main.py`
- Create: `api/tests/test_profile_api.py`

**Interfaces:**
- Consumes: `app.db.get_session`、`app.models.client.Client/Profile/new_client_id`
- Produces: `GET /api/profile`、`PATCH /api/profile`；`app.deps.get_client_id` 依赖；cookie 名 `offerpilot_client`

- [ ] **Step 1: 写失败测试**

`api/tests/test_profile_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

COOKIE = "offerpilot_client"


def test_first_request_creates_a_client_and_returns_an_empty_profile(require_db):
    client = TestClient(app)
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json()["schoolName"] is None
    assert COOKIE in response.cookies or COOKIE in client.cookies


def test_patch_persists_and_reads_back(require_db):
    client = TestClient(app)
    client.get("/api/profile")
    response = client.patch("/api/profile", json={"schoolName": "北京邮电大学", "gpaScore": 82})
    assert response.status_code == 200
    assert response.json()["schoolName"] == "北京邮电大学"

    again = client.get("/api/profile").json()
    assert again["schoolName"] == "北京邮电大学"
    assert float(again["gpaScore"]) == 82.0


def test_a_second_subject_cannot_see_the_first_ones_profile(require_db):
    """The core isolation guarantee: two cookies must never resolve to the same profile."""
    first = TestClient(app)
    first.patch("/api/profile", json={"schoolName": "北京邮电大学"})

    second = TestClient(app)
    assert second.get("/api/profile").json()["schoolName"] is None


def test_rejects_an_unknown_field(require_db):
    client = TestClient(app)
    response = client.patch("/api/profile", json={"gpaScoreTypo": 82})
    assert response.status_code == 422
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_profile_api.py -v
```

Expected: FAIL —— 404，因为还没有 `/api/profile` 路由。

- [ ] **Step 3: 写主体依赖**

`api/app/deps.py`:

```python
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.client import Client, Profile, new_client_id

COOKIE_NAME = "offerpilot_client"


def get_client_id(
    response: Response,
    offerpilot_client: Annotated[str | None, Cookie()] = None,
) -> str:
    """Resolve the anonymous subject, minting one on the first request.

    An id that is not a well-formed uuid is replaced rather than trusted, so a malformed cookie can
    never address a row that belongs to someone else.
    """
    client_id = offerpilot_client
    if client_id:
        try:
            uuid.UUID(client_id)
        except ValueError:
            client_id = None

    if not client_id:
        client_id = new_client_id()

    response.set_cookie(
        COOKIE_NAME, client_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365
    )
    return client_id


def get_profile(
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Return the caller's profile, creating the client row on first contact."""
    if session.get(Client, client_id) is None:
        session.add(Client(id=client_id))
        session.flush()
        session.add(Profile(client_id=client_id))
        session.commit()
    return session.get(Profile, client_id)
```

- [ ] **Step 4: 写 Pydantic 模式（camelCase 边界）**

`api/app/schemas/profile.py`:

```python
from pydantic import BaseModel, ConfigDict


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


class ProfileFields(BaseModel):
    """Mirrors ProfileView's fields. Aliases keep the wire format camelCase like the frontend."""

    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    current_education_level: str | None = None
    school_origin: str | None = None
    school_name: str | None = None
    domestic_tier: str | None = None
    overseas_band: str | None = None
    major: str | None = None
    gpa_score: float | None = None
    gpa_scale: float | None = None
    target_degree_level: str | None = None
    target_field: str | None = None
    intake: str | None = None
    english_score: str | None = None
    annual_budget_cny: float | None = None


class ProfilePatch(ProfileFields):
    """Every field optional. `extra="forbid"` inherited from ProfileFields rejects typos."""
```

- [ ] **Step 5: 写路由**

`api/app/routers/__init__.py`（空文件）

`api/app/routers/profile.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_profile
from app.models.client import Profile
from app.schemas.profile import ProfileFields, ProfilePatch

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileFields)
def read_profile(profile: Annotated[Profile, Depends(get_profile)]) -> Profile:
    return profile


@router.patch("", response_model=ProfileFields)
def update_profile(
    patch: ProfilePatch,
    profile: Annotated[Profile, Depends(get_profile)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Apply only the fields the caller actually sent, so a partial edit cannot blank the rest."""
    for name, value in patch.model_dump(exclude_unset=True).items():
        setattr(profile, name, value)
    session.commit()
    session.refresh(profile)
    return profile
```

- [ ] **Step 6: 挂路由**

在 `api/app/main.py` 顶部导入并注册：

```python
from app.routers import profile

app.include_router(profile.router)
```

- [ ] **Step 7: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_profile_api.py -v
```

Expected: 四个测试全部 PASS。

- [ ] **Step 8: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the profile read and update endpoints

- Identify the caller with an httpOnly cookie that carries an anonymous client id, minting one on
  first contact so no sign-up step is needed.
- Reject a cookie that is not a well-formed uuid instead of using it, so a malformed value cannot
  address another subject's row.
- Serialise with camelCase aliases so the wire format matches the frontend types, and forbid unknown
  fields so a misspelled property fails loudly rather than being silently dropped.
- Apply only the fields present in the request, so editing one field cannot clear the others.
- Verified with tests covering first contact, persistence across requests, rejection of an unknown
  field, and the isolation guarantee that two cookies never resolve to the same profile.
EOF
```

---

### Task 5: sources 与 source_versions

**Files:**
- Create: `api/app/models/source.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/<rev>_add_sources.py`
- Create: `api/tests/test_sources.py`

**Interfaces:**
- Consumes: `app.db.Base`
- Produces: `app.models.source.Source`、`app.models.source.SourceVersion`；常量 `SourceStatus`（`待核验` / `已核验` / `失效`）

- [ ] **Step 1: 写失败测试**

`api/tests/test_sources.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.source import Source, SourceStatus, SourceVersion


def test_source_starts_unverified(db_session, require_db):
    """A source must never claim verification it has not had."""
    source = Source(
        id=str(uuid.uuid4()),
        url="https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement",
        title="Genuine Student requirement",
        publisher="Department of Home Affairs",
        domain="immi.homeaffairs.gov.au",
    )
    db_session.add(source)
    db_session.commit()

    assert source.status == SourceStatus.UNVERIFIED
    assert source.verified_at is None

    db_session.delete(source)
    db_session.commit()


def test_source_url_is_unique(db_session, require_db):
    url = f"https://example.edu.au/{uuid.uuid4()}"
    db_session.add(Source(id=str(uuid.uuid4()), url=url, title="a"))
    db_session.commit()

    db_session.add(Source(id=str(uuid.uuid4()), url=url, title="b"))
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("a duplicate source url was accepted")


def test_versions_are_numbered_within_a_source(db_session, require_db):
    source = Source(id=str(uuid.uuid4()), url=f"https://example.edu.au/{uuid.uuid4()}", title="a")
    db_session.add(source)
    db_session.commit()

    db_session.add(SourceVersion(id=str(uuid.uuid4()), source_id=source.id, version_no=1))
    db_session.commit()
    db_session.add(SourceVersion(id=str(uuid.uuid4()), source_id=source.id, version_no=2))
    db_session.commit()

    numbers = db_session.execute(
        select(SourceVersion.version_no)
        .where(SourceVersion.source_id == source.id)
        .order_by(SourceVersion.version_no)
    ).scalars().all()
    assert numbers == [1, 2]

    db_session.delete(source)
    db_session.commit()
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_sources.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.source'`。

- [ ] **Step 3: 写模型**

`api/app/models/source.py`:

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SourceStatus(StrEnum):
    """Values are Chinese because they are shown in the interface as-is."""

    UNVERIFIED = "待核验"
    VERIFIED = "已核验"
    DEAD = "失效"


class SourceVersionStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class Source(Base):
    """One official page that a claim can be traced back to."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)

    # Defaults to unverified and has no server-side default for verified_at. A record can only claim
    # verification when a human sets the date explicitly.
    status: Mapped[str] = mapped_column(String(16), default=SourceStatus.UNVERIFIED)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["SourceVersion"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceVersion(Base):
    """A fetched snapshot of a source. Approval is manual, so status starts pending."""

    __tablename__ = "source_versions"
    __table_args__ = (UniqueConstraint("source_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE")
    )
    version_no: Mapped[int] = mapped_column(Integer)

    requested_url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_type: Mapped[str | None] = mapped_column(String(128))
    content_bytes: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    body_text: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(24), default=SourceVersionStatus.PENDING_REVIEW)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped[Source] = relationship(back_populates="versions")
```

- [ ] **Step 4: 生成并校对迁移**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic revision --autogenerate -m "add sources and source versions"
```

人工确认：`sources.url` 有唯一约束；`source_versions` 有 `(source_id, version_no)` 唯一约束；两个外键都是 `ondelete="CASCADE"`。

- [ ] **Step 5: 应用并验证可回退**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

- [ ] **Step 6: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_sources.py -v
```

Expected: 三个测试全部 PASS。

- [ ] **Step 7: 加一条防回归检查**

在仓库根加 `scripts/check-no-fake-dates.cjs`：

```javascript
#!/usr/bin/env node
// Fails when a verification date is hardcoded anywhere in the source or seed data.
//
// The previous implementation shipped verified_at = "2026-07-14" as a default, which made every
// record look checked. Verification dates must only ever come from a human writing to the database.
const { readFileSync } = require("node:fs");
const { execFileSync } = require("node:child_process");

const files = execFileSync("git", ["ls-files", "api", "scripts"], { encoding: "utf8" })
  .split("\n")
  .filter((f) => /\.(py|json|cjs)$/.test(f));

const offenders = [];
for (const file of files) {
  const text = readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    if (/verified_at\s*[:=]\s*["']\d{4}-\d{2}-\d{2}/.test(line)) {
      offenders.push(`${file}:${i + 1}`);
    }
  });
}

if (offenders.length) {
  console.error("硬编码的核验日期:", offenders.join(", "));
  process.exit(1);
}
console.log("未发现硬编码的核验日期");
```

- [ ] **Step 8: 运行检查**

```bash
cd "$(git rev-parse --show-toplevel)"
node scripts/check-no-fake-dates.cjs
```

Expected: `未发现硬编码的核验日期`。

- [ ] **Step 9: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add api scripts
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the source and source version tables

- Model an official page once, with fetched snapshots hanging off it. Programs and, later, review
  criteria both point at this table instead of each carrying their own citation machinery.
- Default a source to unverified and give verified_at no server-side default, so a record can only
  claim verification when a human sets the date. The previous implementation defaulted it to a fixed
  date, which made unreviewed data look checked.
- Add a guard script that fails when a verification date is hardcoded in source or seed data.
- Verified with tests for the unverified default, the unique constraint on the url, and per-source
  version numbering, plus a manual upgrade and downgrade.
EOF
```

---

### Task 6: universities、programs、program_prerequisites 与种子导入

**Files:**
- Create: `api/app/models/program.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/<rev>_add_programs.py`
- Create: `api/app/seed.py`
- Create: `api/tests/test_seed.py`

**Interfaces:**
- Consumes: `app.models.source.Source`
- Produces: `app.models.program.University/Program/ProgramPrerequisite`；`app.seed.seed_programs(session) -> int`（返回写入的项目数）

- [ ] **Step 1: 写失败测试**

`api/tests/test_seed.py`:

```python
from sqlalchemy import func, select

from app.models.program import Program, University
from app.models.source import Source, SourceStatus
from app.seed import seed_programs


def test_seed_is_idempotent(db_session, require_db):
    first = seed_programs(db_session)
    second = seed_programs(db_session)
    assert first > 0
    assert second == 0, "re-running the seed must not duplicate rows"


def test_seeded_programs_are_not_marked_verified(db_session, require_db):
    """Every seeded program is placeholder data and must say so."""
    seed_programs(db_session)
    statuses = db_session.execute(select(func.distinct(Program.data_status))).scalars().all()
    assert statuses == ["待核验"]


def test_seeded_sources_have_no_verification_date(db_session, require_db):
    seed_programs(db_session)
    rows = db_session.execute(select(Source)).scalars().all()
    assert rows, "the seed must create sources"
    assert all(row.verified_at is None for row in rows)
    assert all(row.status == SourceStatus.UNVERIFIED for row in rows)


def test_every_program_points_at_a_source(db_session, require_db):
    seed_programs(db_session)
    orphans = db_session.execute(
        select(Program.id).where(Program.source_id.is_(None))
    ).scalars().all()
    assert orphans == [], f"programs without a source: {orphans}"


def test_expected_universities_are_present(db_session, require_db):
    seed_programs(db_session)
    names = set(db_session.execute(select(University.name)).scalars().all())
    assert {"新南威尔士大学", "悉尼大学", "蒙纳士大学"} <= names
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_seed.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.program'`。

- [ ] **Step 3: 写模型**

`api/app/models/program.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class University(Base):
    __tablename__ = "universities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(32), default="澳大利亚")
    official_url: Mapped[str | None] = mapped_column(Text)

    programs: Mapped[list["Program"]] = relationship(back_populates="university")


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    degree_level: Mapped[str | None] = mapped_column(String(32))
    field: Mapped[str | None] = mapped_column(String(64))
    duration: Mapped[str | None] = mapped_column(String(32))

    minimum_mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    non_211_minimum_mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    requires_cognate: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)
    research_proposal_required: Mapped[bool] = mapped_column(Boolean, default=False)
    english_requirement: Mapped[str | None] = mapped_column(Text)

    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sources.id"))
    data_status: Mapped[str] = mapped_column(String(16), default="待核验")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    university: Mapped[University] = relationship(back_populates="programs")
    prerequisites: Mapped[list["ProgramPrerequisite"]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )


class ProgramPrerequisite(Base):
    __tablename__ = "program_prerequisites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("programs.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    program: Mapped[Program] = relationship(back_populates="prerequisites")
```

- [ ] **Step 4: 生成并应用迁移**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/alembic revision --autogenerate -m "add universities programs and prerequisites"
.venv/bin/alembic upgrade head
```

- [ ] **Step 5: 写种子脚本**

`api/app/seed.py` 的开头与骨架（六条项目数据照抄 `web/lib/programs.ts` 的现有值，逐条翻译成 snake_case；每个项目先 `upsert` 一条 `Source`，再用其 id 写 `Program`）：

```python
"""Seed the placeholder program catalogue.

The values mirror web/lib/programs.ts, which is the current source of truth until the annotation stage
replaces both with reviewed data. Every record is written as 待核验.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus

UNIVERSITIES = [
    {
        "id": "unsw",
        "name": "新南威尔士大学",
        "name_en": "UNSW Sydney",
        "city": "悉尼",
        "official_url": "https://www.unsw.edu.au/",
    },
    # …其余四所：usyd / monash / uq / uwa
]

# Each entry keeps the same official url the frontend already cites.
PROGRAMS = [
    {
        "id": "unsw-master-it",
        "university_id": "unsw",
        "name": "信息技术硕士",
        "name_en": "Master of Information Technology",
        "city": "悉尼",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "2 年",
        "minimum_mark": 65,
        "non_211_minimum_mark": 70,
        "requires_cognate": False,
        "english_requirement": "IELTS 6.5（单项不低于 6.0）",
        "source_url": "https://www.unsw.edu.au/study/postgraduate/master-of-information-technology",
        "source_title": "UNSW — Master of Information Technology",
        "prerequisites": ["认可的学士学位", "本科阶段包含编程或数学课程"],
    },
    # …其余五个项目，逐条照抄现有前端数据
]


def seed_programs(session: Session) -> int:
    """Insert missing universities, sources and programs. Returns how many programs were added."""
    added = 0

    for row in UNIVERSITIES:
        if session.get(University, row["id"]) is None:
            session.add(University(**row))
    session.flush()

    for row in PROGRAMS:
        if session.get(Program, row["id"]) is not None:
            continue

        source = session.execute(
            select(Source).where(Source.url == row["source_url"])
        ).scalar_one_or_none()
        if source is None:
            source = Source(
                id=f"src-{row['id']}",
                url=row["source_url"],
                title=row["source_title"],
                publisher=row["university_id"],
                domain=row["source_url"].split("/")[2],
                status=SourceStatus.UNVERIFIED,
                verified_at=None,
            )
            session.add(source)
            session.flush()

        session.add(
            Program(
                id=row["id"],
                university_id=row["university_id"],
                name=row["name"],
                name_en=row["name_en"],
                city=row["city"],
                degree_level=row["degree_level"],
                field=row["field"],
                duration=row["duration"],
                minimum_mark=row["minimum_mark"],
                non_211_minimum_mark=row.get("non_211_minimum_mark"),
                requires_cognate=row.get("requires_cognate", False),
                english_requirement=row.get("english_requirement"),
                source_id=source.id,
                data_status="待核验",
            )
        )

        for index, label in enumerate(row.get("prerequisites", [])):
            session.add(
                ProgramPrerequisite(
                    id=f"{row['id']}-pre-{index}",
                    program_id=row["id"],
                    label=label,
                    sort_order=index,
                )
            )
        added += 1

    session.commit()
    return added
```

- [ ] **Step 6: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_seed.py -v
```

Expected: 五个测试全部 PASS。

- [ ] **Step 7: 加命令行入口**

```bash
cd "$(git rev-parse --show-toplevel)"
cat > api/seed_cli.py <<'PY'
"""Run the program seed from the command line: python seed_cli.py"""
from app.db import SessionLocal
from app.seed import seed_programs

if __name__ == "__main__":
    with SessionLocal() as session:
        print(f"seeded {seed_programs(session)} programs")
PY
```

Makefile 追加：

```make
seed: ## Seed the placeholder program catalogue
	cd api && .venv/bin/python seed_cli.py
```

- [ ] **Step 8: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add api Makefile
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the program tables and the placeholder catalogue seed

- Model universities, programs and their prerequisites. Threshold columns stay nullable because some
  institutions publish a non-211 baseline and others do not, and an unpublished value is unknown
  rather than zero.
- Port the six programs currently hardcoded in web/lib/programs.ts, keeping the official url each one
  already cites, and record every row as 待核验.
- Make the seed idempotent so it can run on every deploy without duplicating rows.
- Verified with tests asserting idempotency, that every seeded program is unverified, that no seeded
  source carries a verification date, and that no program is missing a source.
EOF
```

---

### Task 7: 项目查询接口

**Files:**
- Create: `api/app/schemas/program.py`
- Create: `api/app/routers/programs.py`
- Modify: `api/app/main.py`
- Create: `api/tests/test_programs_api.py`

**Interfaces:**
- Consumes: `app.models.program`、`app.seed.seed_programs`
- Produces: `GET /api/programs` 返回 `list[ProgramOut]`，字段为 camelCase，含 `source: {url, title, status}`

- [ ] **Step 1: 写失败测试**

`api/tests/test_programs_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_programs


def test_lists_every_seeded_program_with_its_source(require_db, db_session):
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs")
    assert response.status_code == 200

    programs = response.json()
    assert len(programs) >= 6
    first = programs[0]
    assert set(first) >= {"id", "name", "universityName", "source", "dataStatus"}
    assert first["source"]["url"].startswith("https://")
    assert first["source"]["status"] == "待核验"


def test_filters_by_field(require_db, db_session):
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs", params={"field": "计算机与数据"})
    assert response.status_code == 200
    assert all(p["field"] == "计算机与数据" for p in response.json())
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_programs_api.py -v
```

Expected: FAIL —— 404（路由还不存在）。

- [ ] **Step 3: 写模式与路由**

`api/app/schemas/program.py`:

```python
from pydantic import BaseModel, ConfigDict

from app.schemas.profile import _camel


class SourceOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    url: str
    title: str
    status: str


class ProgramOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    id: str
    name: str
    name_en: str | None = None
    university_name: str
    city: str | None = None
    degree_level: str | None = None
    field: str | None = None
    duration: str | None = None
    minimum_mark: float | None = None
    non_211_minimum_mark: float | None = None
    requires_cognate: bool = False
    english_requirement: str | None = None
    data_status: str
    source: SourceOut
```

`api/app/routers/programs.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models.program import Program
from app.models.source import Source
from app.schemas.program import ProgramOut, SourceOut

router = APIRouter(prefix="/api/programs", tags=["programs"])


@router.get("", response_model=list[ProgramOut])
def list_programs(
    session: Annotated[Session, Depends(get_session)],
    field: Annotated[str | None, Query()] = None,
) -> list[ProgramOut]:
    statement = select(Program).options(selectinload(Program.university)).order_by(Program.id)
    if field:
        statement = statement.where(Program.field == field)

    out: list[ProgramOut] = []
    for program in session.execute(statement).scalars():
        source = session.get(Source, program.source_id) if program.source_id else None
        out.append(
            ProgramOut(
                id=program.id,
                name=program.name,
                name_en=program.name_en,
                university_name=program.university.name,
                city=program.city,
                degree_level=program.degree_level,
                field=program.field,
                duration=program.duration,
                minimum_mark=program.minimum_mark,
                non_211_minimum_mark=program.non_211_minimum_mark,
                requires_cognate=program.requires_cognate,
                english_requirement=program.english_requirement,
                data_status=program.data_status,
                source=SourceOut(url=source.url, title=source.title, status=source.status),
            )
        )
    return out
```

- [ ] **Step 4: 挂路由**

`api/app/main.py` 加入：

```python
from app.routers import programs

app.include_router(programs.router)
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)/api"
.venv/bin/pytest tests/test_programs_api.py -v
```

Expected: 两个测试 PASS。

- [ ] **Step 6: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add api
git diff --cached --check
git commit -F - <<'EOF'
feat(api): add the program listing endpoint

- Return each program together with the source it came from, so the interface can always show where a
  requirement was read.
- Keep the response camelCase to match the frontend types, and support filtering by field.
- Verified with tests listing every seeded program and asserting each carries an https source with
  the unverified status, plus a filter test.
EOF
```

---

### Task 8: 前端档案页改为读写接口

**Files:**
- Create: `web/lib/api.ts`
- Modify: `web/lib/store.ts`
- Modify: `web/app/page.tsx`
- Modify: `web/components/ProfileView.tsx`
- Modify: `web/next.config.ts`
- Modify: `Makefile`
- Modify: `scripts/e2e-walkthrough.cjs`

**Interfaces:**
- Consumes: `GET /api/profile`、`PATCH /api/profile`
- Produces: `web/lib/api.ts` 导出 `fetchProfile()`、`patchProfile(patch)`

- [ ] **Step 1: 写代理配置**

`web/next.config.ts` 加 `rewrites`，把 `/api/*` 转发到后端，避免开发期跨域：

```typescript
async rewrites() {
  return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
}
```

- [ ] **Step 2: 写失败测试（走查断言）**

在 `scripts/e2e-walkthrough.cjs` 的档案编辑段落后加入：

```javascript
  // The profile must now survive without localStorage: reload after clearing site data and the
  // server-side copy should still answer.
  await page.evaluate(() => window.localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  const serverProfile = await page.evaluate(async () => {
    const response = await fetch("/api/profile");
    return response.json();
  });
  console.log("清空 localStorage 后服务端仍有档案:", serverProfile.schoolName ? "是" : "否");
```

- [ ] **Step 3: 运行走查，确认失败**

```bash
cd "$(git rev-parse --show-toplevel)"
make dev          # 另开一个终端保持运行
make screenshots
```

Expected: 打印 `清空 localStorage 后服务端仍有档案: 否`（此时前端还没接接口）。

- [ ] **Step 4: 写前端接口层**

`web/lib/api.ts`:

```typescript
import type { Profile } from "./types";

/** Server-side profile. Field names already match because the API serialises camelCase. */
export async function fetchProfile(): Promise<Partial<Profile>> {
  const response = await fetch("/api/profile", { credentials: "same-origin" });
  if (!response.ok) throw new Error(`读取档案失败：${response.status}`);
  return response.json();
}

export async function patchProfile(patch: Partial<Profile>): Promise<Partial<Profile>> {
  const response = await fetch("/api/profile", {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error(`保存档案失败：${response.status}`);
  return response.json();
}
```

- [ ] **Step 5: 让 page.tsx 以服务端为准**

在 `web/app/page.tsx` 里新增一个 effect：挂载时调用 `fetchProfile()`，把结果并入 `state.profile`。`updateProfile` 改为**先乐观更新本地 state，再调用 `patchProfile(patch)`**，失败时回滚并提示。localStorage 仍保留 `stage`、`portfolio`、`completedMaterials`（这些在 M2 才迁移）。

- [ ] **Step 6: 运行走查，确认通过**

```bash
cd "$(git rev-parse --show-toplevel)"
make screenshots
```

Expected: 打印 `清空 localStorage 后服务端仍有档案: 是`，且原有的单条编辑、头像、菜单等断言全部保持通过。

- [ ] **Step 7: 跑全部测试与构建**

```bash
cd "$(git rev-parse --show-toplevel)"
make api-test && make test && make build
```

Expected: 后端测试与前端 44 个测试全部通过，构建成功。

- [ ] **Step 8: 提交**

```bash
cd "$(git rev-parse --show-toplevel)"
git add web scripts Makefile
git diff --cached --check
git commit -F - <<'EOF'
feat(web): read and write the profile through the backend

- Load the profile from the server on mount and save each field edit through the API, so clearing
  browser storage no longer loses the applicant's background.
- Keep the local state update optimistic and roll it back when the request fails, so an edit still
  feels immediate without silently diverging from the server.
- Proxy /api to the backend in development to avoid a cross-origin setup during local work.
- Leave stage, portfolio and completed materials on localStorage; those move in the next batch.
- Verified by clearing localStorage in a real browser and confirming the profile still loads, then
  running the full test suite and the production build.
EOF
```

---

## 自检

**spec 覆盖检查**

| spec 要求 | 对应任务 |
|---|---|
| 3.1 单一 PostgreSQL + JSONB（本批未用 JSONB） | Task 2 |
| 3.2 来源治理统一成两张表 | Task 5 |
| 3.6 匿名设备 ID | Task 4 |
| 3.7 技术选型（PG/Alembic/SQLAlchemy/FastAPI/本地 venv） | Task 1、Task 2 |
| 4.1 `clients` `profiles` | Task 3 |
| 4.2 `sources` `source_versions` `universities` `programs` `program_prerequisites` | Task 5、Task 6 |
| 6 GS 来源已核验（本批只需 sources 表能承载） | Task 5 |
| 7 M1 批次 | 本计划全部 |
| 8 验收 1：迁移可上可下 | Task 3、Task 5 |
| 8 验收 2：主体隔离有测试 | Task 4 |
| 8 验收 4：不允许硬编码核验日期 | Task 5 |
| 8 验收 6：前端脱 localStorage（档案部分） | Task 8 |

**本批不覆盖**（属于 M2–M4，各自成计划）：`material_templates`、`roadmap_tasks`、`applications`、`task_events`、`documents` 系列、`review_criteria`、`conversations`、`messages`、`agent_runs`、`proposals`、`profile_revisions`。

**占位检查**：Task 6 的 `UNIVERSITIES` 与 `PROGRAMS` 只写出了一条完整样例，其余五所与五个项目标注为"照抄 `web/lib/programs.ts`"。这是**有意为之**：那批数据在实施时必须逐条对照现有前端数据，抄错比留空更糟。执行该任务时须逐条核对，不得凭印象补写。

**类型一致性检查**：`new_client_id()` 在 Task 3 定义、Task 4 使用；`SourceStatus.UNVERIFIED` 在 Task 5 定义、Task 6 使用；`_camel` 在 Task 4 定义、Task 7 使用；`seed_programs` 在 Task 6 定义、Task 7 使用。命名一致。

## 执行方式

计划完成后请选择：

1. **Subagent-Driven（推荐）** —— 每个任务派一个全新 subagent，任务间我来审查
2. **Inline Execution** —— 在当前会话按批次执行，带检查点

**本计划涉及 8 个任务，建议按任务分批执行，每批结束后停下来给你看。**
