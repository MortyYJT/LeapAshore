from __future__ import annotations

import json
from typing import Any

from app.models import KnowledgeSearchRequest
from app.services.knowledge_rag import retrieve_official_knowledge


CASES: list[dict[str, Any]] = [
    {"query": "UNSW 双非学生需要多少均分", "program": "unsw-master-it", "section": "学术与背景"},
    {"query": "新南威尔士大学信息技术成绩门槛", "program": "unsw-master-it", "section": "学术与背景"},
    {"query": "悉尼大学 Master of Computer Science 入学成绩", "program": "usyd-master-cs", "section": "学术与背景"},
    {"query": "USYD MCS 接受什么背景", "program": "usyd-master-cs", "section": "学术与背景"},
    {"query": "Monash AI 非 IT 背景能申请吗", "program": "monash-master-ai", "section": "学术与背景"},
    {"query": "蒙纳士人工智能均分要求", "program": "monash-master-ai", "section": "学术与背景"},
    {"query": "Monash CS 先修课程", "program": "monash-master-cs", "section": "先修课与语言"},
    {"query": "蒙纳士计算机科学需要算法吗", "program": "monash-master-cs", "section": "先修课与语言"},
    {"query": "UQ 数据科学雅思要求", "program": "uq-master-data-science", "section": "先修课与语言"},
    {"query": "昆大数据科学需要哪些数学课程", "program": "uq-master-data-science", "section": "先修课与语言"},
    {"query": "UWA IT 数学基础要求", "program": "uwa-master-it", "section": "先修课与语言"},
    {"query": "西澳大学信息技术雅思多少", "program": "uwa-master-it", "section": "先修课与语言"},
]


def evaluate_rag() -> dict[str, float | int]:
    top_one_program = top_one_section = recall_at_three = cited = 0
    for case in CASES:
        response = retrieve_official_knowledge(KnowledgeSearchRequest(query=case["query"], top_k=3))
        if response.hits:
            first = response.hits[0]
            top_one_program += int(first.program_slug == case["program"])
            top_one_section += int(first.program_slug == case["program"] and first.section == case["section"])
        recall_at_three += int(any(hit.program_slug == case["program"] for hit in response.hits))
        cited += int(all(hit.source.url.startswith("https://") and hit.source.id for hit in response.hits))
    total = len(CASES)
    return {
        "cases": total,
        "top_one_program_accuracy": round(top_one_program / total, 4),
        "top_one_section_accuracy": round(top_one_section / total, 4),
        "program_recall_at_3": round(recall_at_three / total, 4),
        "citation_coverage": round(cited / total, 4),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_rag(), ensure_ascii=False, indent=2))
