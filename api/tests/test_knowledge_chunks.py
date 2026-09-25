from app.program_data import PROGRAMS
from app.services.knowledge_chunks import PublishedProgramSnapshot, build_published_chunks


def test_only_published_sources_with_valid_version_hash_are_chunked() -> None:
    program = PROGRAMS[0]
    approved = PublishedProgramSnapshot(program, "version-42", "a" * 64, status="published")
    draft = PublishedProgramSnapshot(program, "version-43", "b" * 64, status="pending_review")
    no_hash = PublishedProgramSnapshot(program, "version-44", "bad", status="published")

    chunks = build_published_chunks([approved, draft, no_hash])

    assert len(chunks) == 3
    assert all(chunk.source_version_id == "version-42" for chunk in chunks)
    assert all(chunk.source_id and chunk.source_title and chunk.source_url for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all("applicant" not in chunk.content.lower() for chunk in chunks)


def test_chunk_id_changes_with_approved_source_version() -> None:
    program = PROGRAMS[0]
    first = build_published_chunks([PublishedProgramSnapshot(program, "version-1", "a" * 64)])[0]
    second = build_published_chunks([PublishedProgramSnapshot(program, "version-2", "a" * 64)])[0]
    assert first.chunk_id != second.chunk_id


def test_requirement_clause_and_its_exception_stay_in_same_chunk() -> None:
    chunk = build_published_chunks([
        PublishedProgramSnapshot(PROGRAMS[0], "version-1", "a" * 64)
    ])[1]
    assert "65%" in chunk.content
    assert "非 211" in chunk.content
    assert "衔接路径" in chunk.content
