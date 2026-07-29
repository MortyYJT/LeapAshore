from datetime import UTC, datetime
from hashlib import sha256

import pytest

from app.models import ProgramSourceSnapshot
from app.program_data import SEED_PROGRAMS
from app.source_governance import (
    attach_version,
    diff_programs,
    initialize_source_registry,
    new_candidate,
    program_content_hash,
    validate_official_source,
)
from app.store import DemoStore


def test_program_content_hash_is_canonical_and_ignores_version_metadata() -> None:
    program = SEED_PROGRAMS[0]
    content_hash = program_content_hash(program)
    tagged = attach_version(program, "srcv_test", content_hash)

    assert program_content_hash(tagged) == content_hash
    assert program_content_hash(program.model_copy(update={"duration": "2.5 年"})) != content_hash


def test_program_diff_reports_only_changed_fact_paths() -> None:
    program = SEED_PROGRAMS[0]
    changed = program.model_copy(update={
        "duration": "2.5 年",
        "source": program.source.model_copy(update={"excerpt": "更新后的证据摘录"}),
    })

    changes = {item.field: item for item in diff_programs(program, changed)}
    assert set(changes) == {"duration", "source.excerpt"}
    assert changes["duration"].before == "2 年"
    assert changes["duration"].after == "2.5 年"


def test_source_candidate_requires_registered_school_https_domain() -> None:
    program = SEED_PROGRAMS[0]
    validate_official_source(program)

    untrusted = program.model_copy(update={
        "source": program.source.model_copy(update={"url": "https://example.com/unsw-requirements"}),
    })
    with pytest.raises(ValueError, match="HTTPS 官方域名"):
        validate_official_source(untrusted)


def test_source_candidate_rejects_a_snapshot_with_tampered_body() -> None:
    program = SEED_PROGRAMS[0]
    store = DemoStore()
    initialize_source_registry(store)
    current = next(
        version for version in store.list_program_source_versions(program.slug)
        if version.status == "published"
    )
    body = "<html>official source body</html>"
    snapshot = ProgramSourceSnapshot(
        requested_url=program.source.url,
        final_url=program.source.url,
        fetched_at=datetime.now(UTC),
        content_type="text/html",
        content_sha256=sha256(body.encode()).hexdigest(),
        content_bytes=len(body.encode()),
        body_text=f"{body}tampered",
    )

    with pytest.raises(ValueError, match="正文与 SHA-256 不一致"):
        new_candidate(
            current=current,
            proposed=program.model_copy(update={"duration": "2.5 年"}),
            submitted_by="reviewer",
            source_snapshot=snapshot,
        )
