# 第二阶段 M3a（材料库与审核依据：后端）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让材料有地方存（上传 / 版本 / 归档 / 下载），让审核要点与人工审核结论能带着官方来源落库，HTTP 对审核依据只读、人工写入走 CLI。

**Architecture:** 五张新表（`documents`、`document_versions`、`review_criteria`、`document_reviews`、`document_review_findings`）+ 一个内容寻址的本地文件目录。材料按匿名 cookie 主体隔离，文件本体不进库。审核要点由种子写入（全部 `待核验`），核验与审核结论由 `api/review_cli.py` 写入。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL 16；新增依赖 `python-multipart`。

**Spec:** `openspec/changes/stage-2-m3-document-library/`（proposal.md、design.md D1–D16、`specs/document-library`、`specs/review-criteria`、`specs/document-review`、tasks.md 第 1–6 组）

## Global Constraints

- 源码注释、docstring、工程文档英文；`note/` 与界面文案中文。
- Conventional Commits 1.0.0，**必须有 scope**、**必须有非空英文 body**，body 每条 `- ` 开头。提交前跑 `git diff --cached --check`。
- 不提交 `api/.env`、`api/.venv/`、`api/var/`、`__pycache__/`、`.runtime-tools/`。
- 分支：`dsh/stage-2-m3-document-library-backend`。不合并自己的 PR，不推 `main`。
- **`verified_at` 只能由 `review_cli.py` 写，写的是 `now()`。** 任何字面日期都会被 `scripts/check-no-fake-dates.cjs` 抓住。
- **没有官方来源的审核要点不允许入库**（`review_criteria.source_id` NOT NULL）。
- **没有要点可引用的建议不允许入库**（`document_review_findings.criterion_id` NOT NULL）。
- 未知一律 `null`：不得把未知写成空串、0 或 `other`。
- `storage_path` 只存相对路径；库里、响应里都不出现绝对路径。
- 上传上限 20 MiB；只接受 PDF / PNG / JPEG / DOCX；**入库的 MIME 以魔数为准**，不信客户端声明。
- 存储根每次从 `settings` 读，测试 monkeypatch 到 `tmp_path`。
- 主观判断一律不写进代码：要点文本只能从 `note/superpowers/specs/2026-10-06-stage-2-database-design.md` §6 已记录的骨架转录。

---

### Task 1: 依赖与存储配置

**Files:**
- Modify: `api/pyproject.toml`
- Modify: `api/app/config.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `app.config.settings.document_storage_root: Path`（默认 `<repo>/api/var/documents`）

- [ ] **Step 1: 加依赖**

`api/pyproject.toml` 的 `dependencies` 末尾加一行（保持字母序不必强求，与既有风格一致即可）：

```toml
  "python-multipart",
```

- [ ] **Step 2: 安装并确认可导入**

Run: `make api-install && api/.venv/bin/python -c "import multipart; print(multipart.__version__)"`
Expected: 打印一个版本号，没有 `ModuleNotFoundError`

- [ ] **Step 3: 加配置**

`api/app/config.py` 改成：

```python
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or from api/.env."""

    database_url: str = "postgresql+psycopg://offerpilot:offerpilot@localhost:55432/offerpilot"

    # Where uploaded files live. Derived from this file's own location rather than the process cwd,
    # because `make api-test`, `make api-dev` and a script run from the repository root have three
    # different working directories and a cwd-relative default would scatter the files across them.
    # The database only ever stores a path relative to this root; see `app.services.documents`.
    document_storage_root: Path = Path(__file__).resolve().parent.parent / "var" / "documents"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
```

- [ ] **Step 4: 忽略上传目录**

`.gitignore` 后端段落追加：

```
# 上传的材料本体，只存在本机
api/var/
```

- [ ] **Step 5: 验证配置可读**

Run: `cd api && .venv/bin/python -c "from app.config import settings; print(settings.document_storage_root)"`
Expected: 打印 `.../offerpilot/api/var/documents`

- [ ] **Step 6: Commit**

```bash
git add api/pyproject.toml api/app/config.py .gitignore
git commit -m "chore(api): add the upload dependency and the document storage root

- add python-multipart, which FastAPI needs to parse a multipart upload
- derive document_storage_root from the package location rather than the cwd
- ignore api/var/, where uploaded files land"
```

---

### Task 2: 五张表、迁移与测试清扫

**Files:**
- Create: `api/app/models/document.py`
- Create: `api/app/models/review.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/<rev>_add_document_library_and_review_criteria.py`
- Create: `api/tests/test_document_model.py`
- Modify: `api/tests/conftest.py`

**Interfaces:**
- Produces: `Document`、`DocumentKind`、`DocumentStatus`、`UploadedBy`、`DocumentVersion`；`ReviewCriterion`、`CriterionScope`、`CheckType`、`CriterionStatus`、`DocumentReview`、`ReviewOverall`、`FindingSeverity`
- Consumes: 既有的 `Source`、`Client`、`RoadmapTask`、`Program`

**关于关系（重要）**：本任务**不声明任何 ORM relationship**。`documents.current_version_id` 与 `document_versions.document_id` 互相引用，声明关系要么需要 `foreign_keys`/`post_update` 的额外机器，要么让 SQLAlchemy 在删父行前把子行的 NOT NULL 外键置空（`api/app/models/roadmap.py:23-25` 记过这个坑）。不声明关系时 SQLAlchemy 只发一条 `DELETE`，由数据库的 `ON DELETE CASCADE` / `SET NULL` 完成级联——这正是我们要的，也不需要 `passive_deletes`。查询一律用显式 `select()`，与 `app/services/applications.py` 的写法一致。

- [ ] **Step 1: 写失败测试**

`api/tests/test_document_model.py`。**覆盖**（每个规则一个用例，插入被禁止的行并断言数据库拒绝，`require_db` + `IntegrationError`）：无 `source_id` 的要点被拒；`scope` 越界被拒；`check_type` 越界被拒；`severity` 越界被拒；无 `criterion_id` 的建议被拒；重复 `(document_id, version_no)` 被拒；未知 `kind` 被拒；被引用的 `sources` 行删不掉；被引用的 `review_criteria` 行删不掉；删 `clients` 带走 documents / versions / reviews / findings；删被引用的任务行后 `documents.task_id` 变 NULL 而材料还在。

覆盖清单写明到"用哪个断言、撞哪条约束"为止；测试正文在实现时写，不抄进计划（`note/superpowers/plans/` 里既有的批次计划就是这个形式）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd api && .venv/bin/pytest tests/test_document_model.py -q`
Expected: `ModuleNotFoundError: No module named 'app.models.document'`

- [ ] **Step 3: 写模型**

`api/app/models/document.py`：

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The five kinds a material can be classified as. Chinese labels are not stored: `kind` is a value
# the code branches on, and the interface owns the wording it shows for each one.
KIND_VALUES = ("transcript", "cv", "ps", "recommendation", "language", "passport", "gs", "other")


class DocumentKind(StrEnum):
    TRANSCRIPT = "transcript"
    CV = "cv"
    PS = "ps"
    RECOMMENDATION = "recommendation"
    LANGUAGE = "language"
    PASSPORT = "passport"
    GS = "gs"
    OTHER = "other"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    ARCHIVED = "archived"
    UNDER_REVIEW = "under_review"
    NEEDS_REVISION = "needs_revision"
    ACCEPTED = "accepted"


class UploadedBy(StrEnum):
    """Who put this version there. Only `user` is reachable until the agent lands in M4."""

    USER = "user"
    AGENT = "agent"


class Document(Base):
    """One material the applicant owns: an identity plus a lifecycle, not one file.

    `kind` stays null until the applicant archives the material, because classifying it is a decision
    only they can make; `status` is the review lifecycle and is independent of it. No ORM
    relationship is declared to `DocumentVersion`: the two tables reference each other, and the
    database's own ON DELETE rules are what should decide what happens when a row goes. See the
    module docstring of `app.services.documents` for the half that reads and writes these rows.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "kind IS NULL OR kind IN (" + ", ".join(f"'{k}'" for k in KIND_VALUES) + ")",
            name="ck_documents_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default=DocumentStatus.UPLOADED)

    # SET NULL rather than RESTRICT on both: a recomputation deletes the applicant's system task rows
    # (`app/services/roadmap_tasks.py`), and `api/tests/test_seed.py` deletes every program. A
    # material outlives the requirement it was prepared for.
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("roadmap_tasks.id", ondelete="SET NULL")
    )
    program_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("programs.id", ondelete="SET NULL")
    )
    current_version_id: Mapped[str | None] = mapped_column(String(36))

    archived_by: Mapped[str | None] = mapped_column(String(8))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    """One uploaded file. Immutable: a revision is a new row, never an edit of this one."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_no: Mapped[int] = mapped_column(Integer)

    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Relative to `settings.document_storage_root`, never absolute: an absolute path would bake this
    # machine's layout into the database, and the repository's own rules keep local paths out.
    storage_path: Mapped[str] = mapped_column(Text)

    uploaded_by: Mapped[str] = mapped_column(String(8), default=UploadedBy.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`api/app/models/review.py`（结构同上，逐字段写全）：

```python
class CriterionScope(StrEnum):
    GS = "gs"
    TRANSCRIPT = "transcript"
    CV = "cv"
    PS = "ps"
    RECOMMENDATION = "recommendation"
    LANGUAGE = "language"
    GENERAL = "general"


class CheckType(StrEnum):
    PRESENCE = "presence"
    LENGTH = "length"
    LANGUAGE = "language"
    EVIDENCE = "evidence"
    CONSISTENCY = "consistency"


class CriterionStatus(StrEnum):
    """Chinese because the interface shows these two values as-is, as `SourceStatus` does."""

    UNVERIFIED = "待核验"
    VERIFIED = "已核验"


class ReviewCriterion(Base):
    """One point a review checks a material against — and the official page it was read from.

    `source_id` is NOT NULL in the database, not merely in the service: a criterion without a page
    behind it is exactly the invented requirement the product refuses to produce.
    """

    __tablename__ = "review_criteria"
    __table_args__ = (
        CheckConstraint("scope IN (...)", name="ck_review_criteria_scope"),
        CheckConstraint("check_type IN (...)", name="ck_review_criteria_check_type"),
    )
    # id, code (String(64), unique), scope, title, description, check_type,
    # rule (JSONB, nullable — null means "only a human can check this"),
    # source_id (FK sources.id ondelete RESTRICT), status (default 待核验),
    # verified_at (nullable, no server default), created_at, updated_at


class ReviewOverall(StrEnum):
    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class DocumentReview(Base):
    """One human review of one version. `version_id` is NOT NULL: a verdict describes exact bytes."""

    __tablename__ = "document_reviews"
    __table_args__ = (CheckConstraint("overall IN (...)", name="ck_document_reviews_overall"),)
    # id, document_id (FK documents CASCADE), version_id (FK document_versions CASCADE),
    # overall, summary (nullable), reviewed_by (String(64), NOT NULL), created_at


class DocumentReviewFinding(Base):
    """One concrete thing to fix, always citing the criterion it fails."""

    __tablename__ = "document_review_findings"
    __table_args__ = (
        CheckConstraint("severity IN (...)", name="ck_document_review_findings_severity"),
    )
    # id, review_id (FK document_reviews CASCADE),
    # criterion_id (FK review_criteria RESTRICT, NOT NULL),
    # severity, finding (Text), evidence_quote (Text, nullable — null when nothing was quoted)
```

- [ ] **Step 4: 导出模型**

`api/app/models/__init__.py` 按既有字母序补上新的 import 与 `__all__` 条目。漏了不会让测试变红，但 `alembic/env.py` 靠这个包看到全部表，下一次 `make revision` 会静默漏掉这五张表。

- [ ] **Step 5: 手写迁移**

`make revision m="add document library and review criteria"` 生成骨架后**手改**：`documents` 先不带 `current_version_id` 建，再建 `document_versions`，最后 `op.add_column("documents", sa.Column("current_version_id", sa.String(36)))` 与 `op.create_foreign_key(..., ondelete="SET NULL")`。两张表互相引用，一次性建只能靠 `use_alter`，分两步更清楚。`downgrade` 倒序 drop 五张表。CHECK 约束写在各自的 `create_table` 里。

- [ ] **Step 6: 升降级往返**

Run: `make migrate && cd api && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`
Expected: 三次都成功，无报错

- [ ] **Step 7: 改测试清扫（执行时移到 Task 6）**

**执行时调整**：这一步移到 Task 6。理由：清扫之所以必须改，是因为 session 级 fixture 要删 GS 来源而 `review_criteria.source_id` 是 RESTRICT——而在 Task 6 之前根本不存在任何要点行，Task 2 的模型测试自己清理自己写的行。与种子放在同一个任务里，改动才是自洽的。届时还要多做一件事：把开发者已经用 CLI 核验过的 `status` / `verified_at` 快照下来，种子跑完再还原，否则每次测试运行都会把人设的核验日期静默抹掉（本文件既有的 `restore_roadmap_tasks` 就是为同类损失写的）。

`api/tests/conftest.py` 的 `clear_the_roadmap_definition`：**它本身**要先删 `document_review_findings`、`document_reviews`、`review_criteria`，然后才删既有的 materials / phases / GS source。原因写在函数 docstring 里：`review_criteria.source_id` 是 RESTRICT，session 级 fixture 在收集第一个测试之前就会调用它，只要要点还在，删 source 会以 `review_criteria_source_id_fkey` 让整轮测试在第一个测试之前变红。同时 session 收尾在 `seed_roadmap` 之后调 `seed_review_criteria`（Task 6 建）。

- [ ] **Step 8: 跑模型测试至全绿**

Run: `cd api && .venv/bin/pytest tests/test_document_model.py -q`
Expected: 全部 PASS

- [ ] **Step 9: 跑整个后端测试，确认清扫没被弄坏**

Run: `make api-test`
Expected: 全绿（新增用例之外，既有 106 个用例的行为不变）

- [ ] **Step 10: Commit**

```bash
git add api/app/models api/alembic/versions api/tests
git commit -m "feat(api): add the document library and review criteria tables

- add documents, document_versions, review_criteria, document_reviews and
  document_review_findings, with the provenance rules pinned in the database
- keep criteria.source_id and findings.criterion_id NOT NULL so a requirement
  without an official page, and a finding without a requirement, cannot exist
- delete the new rows before the Genuine Student source in the test sweep, so
  the session fixture stops failing on review_criteria_source_id_fkey"
```

---

### Task 3: 上传服务——落盘、摘要、类型与限额

**Files:**
- Create: `api/app/services/documents.py`
- Create: `api/tests/test_documents_service.py`

**Interfaces:**
- Produces: `UploadRejected(status_code: int, detail: str)`；`MAX_UPLOAD_BYTES`；`detect_mime(head: bytes, filename: str) -> str | None`；`storage_root() -> Path`；`blob_relpath(sha256: str) -> str`；`store_upload(session, client_id, upload, *, title, task_id) -> Document`；`add_version(session, document, upload) -> DocumentVersion`
- Consumes: Task 2 的模型

- [ ] **Step 1: 写失败测试**

`api/tests/test_documents_service.py` 覆盖：超限（声明长度与实际字节两条路径）→ 413 且存储根下无文件；空文件 → 422；文本改名成 `.pdf` → 415；不含 `word/document.xml` 的 zip → 415；真 PNG 声明成 `application/octet-stream` → 入库 `image/png`；同样字节上传两次只有一个文件、两行 `storage_path` 相同；`storage_path` 是相对路径；标题缺省取文件名；`task_id` 指向别人或指不到 → 422；不带 `task_id` → 存下且为 NULL。

测试用 `starlette.datastructures.UploadFile` 直接构造上传对象，不经过 HTTP：

```python
from starlette.datastructures import Headers, UploadFile

def an_upload(data: bytes, filename: str, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd api && .venv/bin/pytest tests/test_documents_service.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.documents'`

- [ ] **Step 3: 写实现**

`api/app/services/documents.py`，docstring 写清三件事：为什么先落盘再写库（失败模式只能是孤儿 blob，永远不会是"库里指向不存在的字节"）、为什么 MIME 以魔数为准（存下来的文件会被浏览器取回，信客户端声明等于允许存储型 XSS）、为什么限额设在两处（multipart 解析器在端点运行前就把请求体 spool 成临时文件，只靠端点里计数挡不住超大请求体）。

关键实现：

```python
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
CHUNK = 64 * 1024

SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def detect_mime(head: bytes, path_on_disk: Path | None = None) -> str | None:
    """The type these bytes actually are, or None when this build does not accept them.

    The ZIP container DOCX uses only proves "this is a zip", so it is opened and asked for the part
    that makes it a Word document; refusing that whole family by its four magic bytes alone would
    both accept any archive and reject nothing.
    """
```

- [ ] **Step 4: 跑测试至全绿**

Run: `cd api && .venv/bin/pytest tests/test_documents_service.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 确认超限不会先把内容读进内存**（实现走查：读 64 KiB、累加、超过上限立刻中止并删除临时文件）

- [ ] **Step 6: Commit**

```bash
git add api/app/services/documents.py api/tests/test_documents_service.py
git commit -m "feat(api): store uploads as content-addressed blobs

- detect the type from the file's own bytes, including the DOCX container check
- copy in chunks and abort past 20 MiB, so nothing oversized reaches the storage root
- write the blob before the row, which makes an orphaned file the only failure mode"
```

---

### Task 4: 材料的读写与下载路由

**Files:**
- Create: `api/app/schemas/document.py`
- Create: `api/app/routers/documents.py`
- Modify: `api/app/main.py`
- Create: `api/tests/test_documents_api.py`

**Interfaces:**
- Produces: `GET /api/documents`、`POST /api/documents`、`GET /api/documents/{id}`、`POST /api/documents/{id}/versions`、`GET /api/documents/{id}/versions/{n}/file`
- Consumes: Task 3 的 `store_upload` / `add_version` / `UploadRejected`；`app.deps.get_client_id`、`load_or_create_profile`；`app.schemas.roadmap.SourceRef`

- [ ] **Step 1: 写失败测试**

`api/tests/test_documents_api.py` 覆盖：列表只返回本主体的材料；跨主体读详情 404；跨主体下载 404；`task_id` 指向别人的任务 422；版本号不属于该材料 404；下载响应带 `Content-Disposition: attachment`（含 RFC 5987 的 `filename*`）与 `X-Content-Type-Options: nosniff`，且内容是存进去的字节；`DELETE /api/documents/{id}` 405；`kind` 未定返回 `null`（不是 `""`、不是 `other`）；列表只带当前版本、详情带全部版本且最新在前；没有结论时是空列表。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd api && .venv/bin/pytest tests/test_documents_api.py -q`
Expected: 404（路由还不存在）

- [ ] **Step 3: 写 schema**

`api/app/schemas/document.py`：`VersionOut`、`DocumentSummaryOut`（含 `current_version`）、`CriterionRefOut`、`FindingOut`（含 `criterion`、`evidence_quote`）、`ReviewOut`、`DocumentDetailOut`。全部用 `alias_generator=_camel` + `populate_by_name=True`，与既有 schema 一致；来源复用 `app.schemas.roadmap.SourceRef`。

- [ ] **Step 4: 写路由**

`api/app/routers/documents.py`，前缀 `/api/documents`。要点：`POST /api/documents` 用 `UploadFile = File(...)`、`title: str | None = Form(None)`、`task_id: str | None = Form(None)`——**同一个路由上不能再挂 JSON body**，FastAPI 不能同时收两种。每个写路由在 body 校验通过后调 `load_or_create_profile`（与 `applications.py` 同样的理由与位置）。`UploadRejected` 映射成它的 `status_code` + 中文 `detail`，绝不漏成 500。下载用 `FileResponse`，headers 显式给全。

- [ ] **Step 5: 挂路由**

`api/app/main.py` 加 `documents` 到 import 与 `include_router`（保持字母序）。

- [ ] **Step 6: 跑测试至全绿**

Run: `cd api && .venv/bin/pytest tests/test_documents_api.py -q`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/schemas/document.py api/app/routers/documents.py api/app/main.py api/tests/test_documents_api.py
git commit -m "feat(api): serve the applicant's own material library

- add upload, version, list, detail and download routes addressed by the cookie
- report another subject's document as absent rather than forbidden
- serve downloads as an attachment with the detected type and nosniff"
```

---

### Task 5: 归档与审核状态流转

**Files:**
- Modify: `api/app/services/documents.py`、`api/app/routers/documents.py`
- Create: `api/tests/test_document_lifecycle.py`

**Interfaces:**
- Produces: `POST /api/documents/{id}/archive`、`POST /api/documents/{id}/submit`；`archive_document(session, document, kind, actor) -> Document`、`submit_document(session, document) -> Document`
- Consumes: Task 4 的路由与 schema

- [ ] **Step 1: 写失败测试**

`api/tests/test_document_lifecycle.py` 覆盖：归档写入 `kind` / `status=archived` / `archived_by` / `archived_at`；缺 `kind` 422；未知 `kind` 422；`under_review` 期间归档（**含 `kind` 不变的情况**）409；未归档就送审 409；`needs_revision` 可重送；`accepted` 无新版本重送 409；上传新版本后回到 `uploaded` 且保留 `kind` 与 `archived_at`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd api && .venv/bin/pytest tests/test_document_lifecycle.py -q`
Expected: 404

- [ ] **Step 3: 写实现**

在 `app/services/documents.py` 里加两个函数，把"允许的流转"写成一张模块级表而不是散落的 `if`，非法流转抛 `UploadRejected(409, ...)`（同一个异常类型，因为它就是同一种"拒绝并说明"）。归档在 `under_review` 时一律拒绝，理由写进 docstring：正在跑的审核引用的是该材料类型对应的要点。

- [ ] **Step 4: 跑测试至全绿**

Run: `cd api && .venv/bin/pytest tests/test_document_lifecycle.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/services/documents.py api/app/routers/documents.py api/tests/test_document_lifecycle.py
git commit -m "feat(api): archive and submit a material through defined transitions

- require a kind to archive, and refuse archiving at all while under review
- require archiving before submitting, because criteria are scoped by kind
- keep the classification when a new version resets the review state"
```

---

### Task 6: 审核要点——种子与只读接口

**Files:**
- Create: `api/app/seed_review_criteria.py`
- Modify: `api/seed_cli.py`
- Create: `api/app/schemas/review_criterion.py`
- Create: `api/app/routers/review_criteria.py`
- Modify: `api/app/main.py`、`api/tests/conftest.py`
- Create: `api/tests/test_review_criteria.py`

**Interfaces:**
- Produces: `seed_review_criteria(session) -> int`；`GET /api/review-criteria`
- Consumes: `app.seed_roadmap.GS_SOURCE_URL` 与它建的 `sources` 行；Task 2 的 `ReviewCriterion`

- [ ] **Step 1: 写失败测试**

`api/tests/test_review_criteria.py` 覆盖：种子写 10 条；每条都指向 GS 官网 URL；长度要点 `check_type == length` 且 `rule == {"maxWords": 150}`；无机器可检规则的要点 `rule is None`；跑两次结果相同且不重复；读回来全部 `待核验` 且 `verified_at is None`；`POST`/`PUT`/`PATCH`/`DELETE /api/review-criteria` 都是 405；两个不同 cookie 读到同一份列表。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd api && .venv/bin/pytest tests/test_review_criteria.py -q`
Expected: `ModuleNotFoundError: No module named 'app.seed_review_criteria'`

- [ ] **Step 3: 写种子**

`api/app/seed_review_criteria.py`：10 条，文本**逐条转录** `note/superpowers/specs/2026-10-06-stage-2-database-design.md` §6 已记录的骨架，一条都不新增、不润色。`source_id` 取 `seed_roadmap` 建的 GS 来源（按 `GS_SOURCE_URL` 查，查不到就先调 `seed_roadmap`）。`status="待核验"`，`verified_at` 一个都不设。幂等：按 `code` upsert。

代码：`"gs-answer-length"` → `check_type=CheckType.LENGTH`、`rule={"maxWords": 150}`；其余九条 `rule=None`，`check_type` 按 §6 括号里的标注（`language` / `presence` / `evidence` / `consistency`）。

- [ ] **Step 4: 接线种子**

`api/seed_cli.py` 在路线图种子之后调用并打印条数。

- [ ] **Step 5: 写只读接口**

`api/app/schemas/review_criterion.py` + `api/app/routers/review_criteria.py`：`GET /api/review-criteria` 返回 code/scope/title/description/checkType/rule/status 与 `source{url,title,status}`，**不解析 cookie**（要点是共享配置）。只声明 `GET`，其余方法由 FastAPI 自动 405。

- [ ] **Step 6: conftest 收尾补种子**

session 级 fixture 的 teardown 在 `seed_roadmap` 之后调 `seed_review_criteria`，保持"跑完把开发库还原"的既有承诺。

- [ ] **Step 7: 跑测试至全绿**

Run: `cd api && .venv/bin/pytest tests/test_review_criteria.py -q && make api-test`
Expected: 全绿

- [ ] **Step 8: 确认没有硬编码核验日期**

Run: `make check-dates`
Expected: `未发现硬编码的核验日期`

- [ ] **Step 9: Commit**

```bash
git add api/app/seed_review_criteria.py api/app/schemas/review_criterion.py api/app/routers/review_criteria.py api/app/main.py api/seed_cli.py api/tests
git commit -m "feat(api): seed the Genuine Student criteria and serve them read-only

- transcribe the ten criteria the stage-2 design recorded, each citing the same
  Department of Home Affairs page the visa materials already cite
- write every one as 待核验 with no verification date: only a human moves that
- expose the list over GET only, because no route in this batch may decide
  that a requirement has been checked"
```

---

### Task 7: 维护者 CLI——核验要点与写入审核结论

**Files:**
- Create: `api/app/services/reviews.py`
- Create: `api/review_cli.py`
- Create: `api/tests/test_review_cli.py`

**Interfaces:**
- Produces: `ReviewRejected(status_code, detail)`；`verify_criterion(session, code, *, verified: bool) -> ReviewCriterion`；`record_review(session, document_id, *, overall, reviewed_by, summary, findings) -> DocumentReview`；`main(argv=None) -> int`
- Consumes: Task 2 的 review 模型、Task 6 的种子要点

- [ ] **Step 1: 写失败测试**

`api/tests/test_review_cli.py` 覆盖：verify 写入运行时间且状态变 `已核验`；unverify 清空日期；`pass` + blocker 被拒；非 `pass` 且无 findings 被拒；`severity` 越界被拒；`reviewed_by` 为空被拒；要点 scope 与材料 kind 不匹配被拒（`general` 除外）；审核非当前版本 409；审核非 `under_review` 的材料 409；`pass` → `accepted`；`needs_revision` → `needs_revision`；`insufficient_evidence` → 仍 `under_review`；`--finding` 的第三个冒号之后原样保留（中文文本里的冒号不被吃掉）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd api && .venv/bin/pytest tests/test_review_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.reviews'`

- [ ] **Step 3: 写服务**

`api/app/services/reviews.py`：所有规则集中在这里，CLI 只做参数解析。`record_review` 一个事务内写 review + findings 并按 `overall` 推进材料状态。每条规则一个显式分支并带中文 detail。

- [ ] **Step 4: 写 CLI**

`api/review_cli.py`（argparse，风格对齐 `seed_cli.py`）：

```
python review_cli.py verify-criterion <code>
python review_cli.py unverify-criterion <code>
python review_cli.py review <document_id> --overall <pass|needs_revision|insufficient_evidence> \
    --reviewed-by NAME --summary TEXT [--finding "code:severity:text"] ...
```

`--finding` 用 `split(":", 2)`（第三个冒号之后全是文本）；少于两个冒号即参数错误。

- [ ] **Step 5: 跑测试至全绿**

Run: `cd api && .venv/bin/pytest tests/test_review_cli.py -q`
Expected: 全部 PASS

- [ ] **Step 6: 走一次真实链路**

用 `make dev` 之外的最小路径：测试里已经覆盖（CLI 写结论 → `GET /api/documents/{id}` 能读到该建议引用的要点与官网 URL）。把这个断言写进 `test_review_cli.py`，作为 5.9 的证据。

- [ ] **Step 7: Commit**

```bash
git add api/app/services/reviews.py api/review_cli.py api/tests/test_review_cli.py
git commit -m "feat(api): record sourced reviews from a maintainer command

- verify and un-verify a criterion, the only writer of verified_at anywhere
- refuse a passing verdict over a blocker, and a failing one that names nothing
- bind every review to the version it judged and to criteria scoped for its kind"
```

---

### Task 8: PR 1 验收

- [ ] **Step 1: 跑完整检查命令**

Run: `make verify`
Expected: 构建、前端类型检查与单测、四个守卫、后端测试、浏览器走查全部通过。**把输出留着**，进提交信息与 PR 描述。

- [ ] **Step 2: 独立审查**

派一个全新上下文的子代理，对照 `openspec/changes/stage-2-m3-document-library/` 的 spec 审 `git diff main...HEAD`，只报影响正确性或本 change 需求的问题。

- [ ] **Step 3: 按审查结论修复并重跑 `make verify`**

- [ ] **Step 4: 提交并开 PR**

```bash
git diff --cached --check
git push -u origin dsh/stage-2-m3-document-library-backend
gh pr create --base main --title "..." --body "..."
```

PR 描述必须写明：改了什么、`make verify` 的输出、CI 覆盖到哪一步、没覆盖什么（浏览器走查只在本地）。**不合并**，等用户。
