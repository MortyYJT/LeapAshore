from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import math
import re

from ..models import (
    KnowledgeEvidence,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    Program,
)
from ..observability import record_rag_retrieval, traced
from ..program_data import PROGRAMS


RETRIEVAL_VERSION = "official-knowledge-bm25-1.0.0"
MIN_RELEVANCE_SCORE = 4.0

PROGRAM_ALIASES = {
    "unsw-master-it": ["unsw", "新南威尔士", "新南", "master of information technology", "mit", "信息技术"],
    "usyd-master-cs": ["usyd", "悉尼大学", "悉大", "master of computer science", "mcs", "cs", "计算机科学"],
    "monash-master-ai": ["monash", "蒙纳士", "莫纳什", "master of artificial intelligence", "mai", "人工智能", "ai"],
    "monash-master-cs": ["monash", "蒙纳士", "莫纳什", "master of computer science", "mcs", "cs", "计算机科学"],
    "uq-master-data-science": ["uq", "昆士兰大学", "昆大", "master of data science", "mds", "数据科学"],
    "uwa-master-it": ["uwa", "西澳大学", "西澳", "master of information technology", "mit", "信息技术"],
}

QUERY_EXPANSIONS = {
    "均分": ["成绩", "gpa", "minimum mark", "学术"],
    "成绩": ["均分", "gpa", "minimum mark", "学术"],
    "雅思": ["ielts", "英语", "语言"],
    "英语": ["ielts", "雅思", "语言"],
    "语言": ["ielts", "雅思", "英语"],
    "先修": ["课程", "背景", "prerequisite"],
    "非相关": ["非it", "背景", "cognate"],
    "双非": ["non211", "非211", "成绩"],
}


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    program: Program
    section: str
    content: str
    search_text: str


def _academic_text(program: Program) -> str:
    parts = [program.source.excerpt]
    if program.minimum_mark is not None:
        parts.append(f"公开基础成绩参考为 {program.minimum_mark:g}%。")
    if program.non_211_minimum_mark is not None:
        parts.append(f"中国非 211 院校参考成绩为 {program.non_211_minimum_mark:g}%。")
    parts.append("要求相关专业背景。" if program.requires_cognate else "课程存在面向非相关背景申请人的路径，仍需按官方页面确认具体学制。")
    return "".join(parts)


def _prerequisite_text(program: Program) -> str:
    prerequisites = "、".join(program.prerequisites) if program.prerequisites else "官方课程页未列入本地结构化先修课清单"
    research = []
    if program.requires_supervisor:
        research.append("需要核验导师匹配或接收要求")
    if program.research_proposal_required:
        research.append("需要准备研究计划")
    suffix = f"；{'、'.join(research)}" if research else ""
    return f"先修课或背景重点：{prerequisites}。英语要求：{program.english_requirement}{suffix}。"


def build_knowledge_chunks(programs: list[Program] | None = None) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for program in programs or PROGRAMS:
        aliases = " ".join(PROGRAM_ALIASES.get(program.slug, []))
        base = f"{program.university} {program.name} {program.city} {program.degree_level} {program.field} {aliases}"
        sections = [
            ("项目概览", f"{program.university}的 {program.name} 位于{program.city}，学制 {program.duration}，属于{program.degree_level}·{program.field}。"),
            ("学术与背景", _academic_text(program)),
            ("先修课与语言", _prerequisite_text(program)),
        ]
        for index, (section, content) in enumerate(sections, start=1):
            chunks.append(KnowledgeChunk(
                chunk_id=f"{program.slug}:{index}",
                program=program,
                section=section,
                content=content,
                search_text=f"{base} {section} {content}",
            ))
    return chunks


def _tokens(value: str) -> list[str]:
    normalized = value.lower().replace("非 it", "非it").replace("非 211", "非211")
    tokens = re.findall(r"[a-z0-9.]+|[\u3400-\u9fff]+", normalized)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            expanded.extend(token[index:index + 2] for index in range(max(0, len(token) - 1)))
        for key, synonyms in QUERY_EXPANSIONS.items():
            if key in token:
                expanded.extend(synonyms)
    return [token for token in expanded if token]


def _filtered_chunks(request: KnowledgeSearchRequest) -> list[KnowledgeChunk]:
    allowed_slugs = set(request.program_slugs)
    return [
        chunk for chunk in build_knowledge_chunks()
        if (not request.target_degree_level or chunk.program.degree_level == request.target_degree_level)
        and (not request.target_field or chunk.program.field == request.target_field)
        and (not allowed_slugs or chunk.program.slug in allowed_slugs)
    ]


@traced("rag.retrieve", layer="rag")
def retrieve_official_knowledge(request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    chunks = _filtered_chunks(request)
    query_tokens = _tokens(request.query)
    if not chunks or not query_tokens:
        record_rag_retrieval(0, None)
        return KnowledgeSearchResponse(
            query=request.query,
            retrieval_version=RETRIEVAL_VERSION,
            generated_at=datetime.now(UTC),
            hits=[],
            coverage_notice="当前已核验知识库中没有可引用的匹配内容。",
        )

    document_tokens = [_tokens(chunk.search_text) for chunk in chunks]
    average_length = sum(map(len, document_tokens)) / len(document_tokens)
    document_frequency = Counter(
        token for tokens in document_tokens for token in set(tokens)
    )
    scores: list[tuple[float, KnowledgeChunk]] = []
    query_lower = request.query.lower().replace(" ", "")
    k1, b = 1.5, 0.75

    for chunk, tokens in zip(chunks, document_tokens, strict=True):
        counts = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            inverse_frequency = math.log(1 + (len(chunks) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
            denominator = frequency + k1 * (1 - b + b * len(tokens) / average_length)
            score += inverse_frequency * (frequency * (k1 + 1) / denominator)

        aliases = PROGRAM_ALIASES.get(chunk.program.slug, [])
        matched_aliases = sum(alias.lower().replace(" ", "") in query_lower for alias in aliases)
        score += min(9.0, matched_aliases * 3.0)
        section_terms = {
            "学术与背景": ["成绩", "均分", "gpa", "背景", "双非", "非相关", "门槛"],
            "先修课与语言": ["先修", "课程", "数学", "雅思", "ielts", "英语", "语言"],
            "项目概览": ["学制", "多久", "城市", "哪里", "项目"],
        }
        if any(term in query_lower for term in section_terms[chunk.section]):
            score += 2.5
        if score > 0:
            scores.append((score, chunk))

    scores.sort(key=lambda item: (-item[0], item[1].chunk_id))
    hits = [
        KnowledgeEvidence(
            chunk_id=chunk.chunk_id,
            program_slug=chunk.program.slug,
            university=chunk.program.university,
            program_name=chunk.program.name,
            section=chunk.section,
            content=chunk.content,
            relevance_score=round(score, 4),
            source=chunk.program.source,
        )
        for score, chunk in scores[:request.top_k]
        if score >= MIN_RELEVANCE_SCORE
    ]
    record_rag_retrieval(len(hits), scores[0][0] if scores else None)
    return KnowledgeSearchResponse(
        query=request.query,
        retrieval_version=RETRIEVAL_VERSION,
        generated_at=datetime.now(UTC),
        hits=hits,
        coverage_notice=(
            "仅检索已完成人工核验的项目事实；目录级覆盖但未核验的课程不会用于回答。"
            if hits else "当前已核验知识库中没有可引用的匹配内容。"
        ),
    )


def grounded_fallback_answer(query: str, hits: list[KnowledgeEvidence]) -> str | None:
    """Create a no-model answer that remains visibly bound to retrieved evidence."""
    if not hits or not any(term in query.lower() for term in [
        "要求", "申请", "成绩", "均分", "gpa", "背景", "先修", "课程", "数学", "雅思", "ielts", "英语", "学制", "项目", "学校",
    ]):
        return None
    selected: list[KnowledgeEvidence] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.program_slug, hit.section)
        if key not in seen:
            selected.append(hit)
            seen.add(key)
        if len(selected) == 3:
            break
    lines = ["我从已核验的官方项目资料中找到了这些信息："]
    for index, hit in enumerate(selected, start=1):
        lines.append(f"{index}. {hit.university} · {hit.program_name}：{hit.content}")
        lines.append(f"来源：{hit.source.title} {hit.source.url}（核验日期 {hit.source.verified_at}）")
    lines.append("以上是检索证据，不是录取承诺；提交前请再次打开来源页面确认最新要求。")
    return "\n".join(lines)
