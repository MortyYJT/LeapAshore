from __future__ import annotations

import re

from ..models import ProgramPrerequisiteMatch, TranscriptAnalysisResponse, TranscriptCourse
from ..program_data import PROGRAMS


CATEGORY_KEYWORDS = {
    "数学与统计": ["数学", "微积分", "高数", "线性代数", "概率", "统计", "calculus", "algebra", "statistics"],
    "编程": ["程序设计", "编程", "python", "java", "c++", "programming"],
    "算法与数据结构": ["算法", "数据结构", "algorithm", "data structure"],
    "数据库": ["数据库", "database", "sql"],
    "计算机基础": ["操作系统", "计算机网络", "组成原理", "软件工程", "人工智能", "机器学习", "operating system", "network"],
}


def _category(name: str) -> str:
    lowered = name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "其他"


def _course_names(text: str) -> list[str]:
    # Accept copied tables, CSV-like text and the common one-course-per-line format.
    fragments = re.split(r"[\n,，;；|]+", text)
    names: list[str] = []
    for fragment in fragments:
        cleaned = re.sub(r"(?:\s+|\t)+(?:\d+(?:\.\d+)?|[A-F][+-]?)\s*$", "", fragment.strip(), flags=re.I)
        cleaned = re.sub(r"^\d+[.)、\s-]*", "", cleaned).strip(" :-")
        if 2 <= len(cleaned) <= 80 and cleaned not in names:
            names.append(cleaned)
    return names[:100]


def _matches(requirement: str, courses: list[TranscriptCourse]) -> bool:
    if "数学" in requirement or "微积分" in requirement or "线性代数" in requirement:
        return any(course.category == "数学与统计" for course in courses)
    if "算法" in requirement or "数据结构" in requirement:
        return any(course.category == "算法与数据结构" for course in courses)
    if "编程" in requirement:
        return any(course.category in {"编程", "算法与数据结构"} for course in courses)
    if "数据库" in requirement:
        return any(course.category == "数据库" for course in courses)
    return any(any(word.lower() in course.name.lower() for word in requirement.split("或")) for course in courses)


def analyze_transcript(text: str) -> TranscriptAnalysisResponse:
    courses = [TranscriptCourse(name=name, category=_category(name)) for name in _course_names(text)]
    matches = []
    for program in PROGRAMS:
        matched = [requirement for requirement in program.prerequisites if _matches(requirement, courses)]
        missing = [requirement for requirement in program.prerequisites if requirement not in matched]
        status = "无需指定先修课" if not program.prerequisites else "满足" if not missing else "部分满足"
        matches.append(ProgramPrerequisiteMatch(
            program_slug=program.slug,
            program_name=program.name,
            matched=matched,
            missing=missing,
            status=status,
        ))
    category_counts = {category: sum(course.category == category for course in courses) for category in CATEGORY_KEYWORDS}
    strengths = [category for category, count in category_counts.items() if count]
    warnings = []
    if not courses:
        warnings.append("未识别到课程名称，请粘贴可复制的成绩单文本。")
    if not category_counts["数学与统计"]:
        warnings.append("未识别到数学或统计课程，数据科学项目通常需要重点核验。")
    if not category_counts["算法与数据结构"]:
        warnings.append("未识别到算法或数据结构课程，部分计算机项目可能要求相关基础。")
    summary = f"共识别 {len(courses)} 门课程；可验证的核心领域包括：{'、'.join(strengths) if strengths else '暂未识别'}。"
    return TranscriptAnalysisResponse(courses=courses, program_matches=matches, academic_summary=summary, warnings=warnings)
