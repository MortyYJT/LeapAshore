from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .models import Program, ProgramSourceChange, ProgramSourceVersion
from .program_data import PROGRAMS, SEED_PROGRAMS, replace_published_program
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


def validate_official_source(program: Program) -> None:
    parsed = urlsplit(program.source.url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed = OFFICIAL_SOURCE_DOMAINS.get(program.slug, ())
    if parsed.scheme != "https" or not any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in allowed
    ):
        raise ValueError("候选来源必须使用该项目已登记学校的 HTTPS 官方域名")
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
) -> ProgramSourceVersion:
    validate_official_source(proposed)
    if proposed.slug != current.program_slug:
        raise ValueError("候选版本的项目标识与路径不一致")
    content_hash = program_content_hash(proposed)
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
        changes=diff_programs(current.program, proposed),
        submitted_by=submitted_by,
        submitted_at=datetime.now(UTC),
        rollback_of=rollback_of,
    )
