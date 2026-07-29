from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from .models import Program, ProgramSourceChange, ProgramSourceSnapshot, ProgramSourceVersion
from .program_data import PROGRAMS, SEED_PROGRAMS, replace_published_program
from .source_fetch import ALLOWED_SOURCE_CONTENT_TYPES
from .store import Store


OFFICIAL_SOURCE_DOMAINS: dict[str, tuple[str, ...]] = {
    "unsw-master-it": ("unsw.edu.au",),
    "usyd-master-cs": ("sydney.edu.au",),
    "monash-master-ai": ("monash.edu",),
    "monash-master-cs": ("monash.edu",),
    "uq-master-data-science": ("uq.edu.au",),
    "uwa-master-it": ("uwa.edu.au",),
}


def _content_payload(program: Program) -> dict[str, Any]:
    payload = program.model_dump(mode="json")
    payload["source"].pop("version_id", None)
    payload["source"].pop("content_hash", None)
    return payload


def program_content_hash(program: Program) -> str:
    canonical = json.dumps(
        _content_payload(program),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def source_version_content_hash(
    program: Program,
    source_snapshot: ProgramSourceSnapshot | None,
) -> str:
    program_hash = program_content_hash(program)
    if not source_snapshot:
        return program_hash
    snapshot_identity = json.dumps(
        {
            "content_sha256": source_snapshot.content_sha256,
            "content_type": source_snapshot.content_type,
            "final_url": source_snapshot.final_url,
            "requested_url": source_snapshot.requested_url,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(f"{program_hash}:{snapshot_identity}".encode("utf-8")).hexdigest()


def attach_version(program: Program, version_id: str, content_hash: str) -> Program:
    source = program.source.model_copy(update={
        "version_id": version_id,
        "content_hash": content_hash,
    })
    return program.model_copy(update={"source": source}, deep=True)


def diff_programs(before: Program, after: Program) -> list[ProgramSourceChange]:
    changes: list[ProgramSourceChange] = []

    def walk(path: str, old: Any, new: Any) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(set(old) | set(new)):
                walk(f"{path}.{key}" if path else key, old.get(key), new.get(key))
            return
        if old != new:
            changes.append(ProgramSourceChange(field=path, before=old, after=new))

    walk("", _content_payload(before), _content_payload(after))
    return changes


def _canonical_official_url(program_slug: str, url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("候选来源 URL 端口无效") from error
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed = OFFICIAL_SOURCE_DOMAINS.get(program_slug, ())
    if (
        parsed.scheme.lower() != "https"
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in allowed
        )
    ):
        raise ValueError("候选来源必须使用该项目已登记学校的 HTTPS 官方域名")
    return urlunsplit(("https", hostname, parsed.path or "/", parsed.query, ""))


def validate_official_source(program: Program) -> None:
    _canonical_official_url(program.slug, program.source.url)
    if program.verification_status != "已核验":
        raise ValueError("只有标记为已核验的项目事实可以进入发布流程")
    if len(program.source.excerpt.strip()) < 20:
        raise ValueError("候选来源必须保留可人工复核的证据摘录")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", program.source.verified_at):
        raise ValueError("核验日期必须使用 YYYY-MM-DD 格式")
    try:
        verified_at = date.fromisoformat(program.source.verified_at)
    except ValueError as error:
        raise ValueError("核验日期不是有效日历日期") from error
    if verified_at > datetime.now(UTC).date():
        raise ValueError("核验日期不能晚于当前日期")


def validate_source_snapshot(program: Program, snapshot: ProgramSourceSnapshot) -> None:
    requested_url = _canonical_official_url(program.slug, snapshot.requested_url)
    final_url = _canonical_official_url(program.slug, snapshot.final_url)
    if requested_url != _canonical_official_url(program.slug, program.source.url):
        raise ValueError("官网快照必须来自候选事实登记的来源 URL")
    if final_url != snapshot.final_url:
        raise ValueError("官网快照最终 URL 未规范化")
    if snapshot.content_type not in ALLOWED_SOURCE_CONTENT_TYPES:
        raise ValueError("官网快照内容类型不受支持")
    if sha256(snapshot.body_text.encode("utf-8")).hexdigest() != snapshot.content_sha256:
        raise ValueError("官网快照正文与 SHA-256 不一致")
    if snapshot.fetched_at.tzinfo is None:
        raise ValueError("官网快照抓取时间必须包含时区")
    if snapshot.fetched_at > datetime.now(UTC) + timedelta(minutes=5):
        raise ValueError("官网快照抓取时间不能晚于当前时间")


def _snapshot_changes(
    before: ProgramSourceSnapshot | None,
    after: ProgramSourceSnapshot | None,
) -> list[ProgramSourceChange]:
    if before == after:
        return []
    changes: list[ProgramSourceChange] = []
    for field in ("content_sha256", "content_type", "content_bytes", "final_url"):
        old_value = getattr(before, field, None)
        new_value = getattr(after, field, None)
        if old_value != new_value:
            changes.append(ProgramSourceChange(
                field=f"source_snapshot.{field}",
                before=old_value,
                after=new_value,
            ))
    return changes


def _seed_version(program: Program) -> ProgramSourceVersion:
    content_hash = program_content_hash(program)
    version_id = f"seed-{program.slug}-{content_hash[:12]}"
    verified_at = datetime.fromisoformat(program.source.verified_at).replace(tzinfo=UTC)
    return ProgramSourceVersion(
        version_id=version_id,
        program_slug=program.slug,
        source_id=program.source.id,
        content_hash=content_hash,
        status="published",
        program=attach_version(program, version_id, content_hash),
        submitted_by="seed-manifest",
        submitted_at=verified_at,
        reviewed_by="seed-manifest",
        reviewed_at=verified_at,
        review_note="由受版本控制的项目事实种子初始化",
    )


def initialize_source_registry(store: Store) -> None:
    """Seed version history once and hydrate the process registry from storage."""

    for seed in SEED_PROGRAMS:
        versions = store.list_program_source_versions(seed.slug)
        if not versions:
            store.save_program_source_version(_seed_version(seed))
    refresh_source_registry(store)


def refresh_source_registry(store: Store) -> None:
    """Load one request-scoped view of every currently published program."""

    published: dict[str, ProgramSourceVersion] = {}
    for item in store.list_program_source_versions(status="published"):
        published.setdefault(item.program_slug, item)
    for program_slug, version in published.items():
        if version.program_slug == program_slug:
            replace_published_program(version.program)


def current_program(program_slug: str) -> Program | None:
    return next((program for program in PROGRAMS if program.slug == program_slug), None)


def new_candidate(
    *,
    current: ProgramSourceVersion,
    proposed: Program,
    submitted_by: str,
    rollback_of: str | None = None,
    source_snapshot: ProgramSourceSnapshot | None = None,
) -> ProgramSourceVersion:
    validate_official_source(proposed)
    if source_snapshot:
        validate_source_snapshot(proposed, source_snapshot)
    if proposed.slug != current.program_slug:
        raise ValueError("候选版本的项目标识与路径不一致")
    content_hash = source_version_content_hash(proposed, source_snapshot)
    if content_hash == current.content_hash:
        raise ValueError("候选内容与当前发布版本完全一致")
    version_id = f"srcv_{uuid4().hex}"
    return ProgramSourceVersion(
        version_id=version_id,
        program_slug=proposed.slug,
        source_id=proposed.source.id,
        content_hash=content_hash,
        base_hash=current.content_hash,
        status="pending_review",
        program=attach_version(proposed, version_id, content_hash),
        changes=diff_programs(current.program, proposed) + _snapshot_changes(
            current.source_snapshot,
            source_snapshot,
        ),
        submitted_by=submitted_by,
        submitted_at=datetime.now(UTC),
        rollback_of=rollback_of,
        source_snapshot=source_snapshot,
    )
