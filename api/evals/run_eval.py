from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from app.models import ApplicantProfile
from app.services.agent import run_recommendation_agent


BASE = {
    "undergraduate_school": "评测大学",
    "school_tier": "双非",
    "undergraduate_major": "软件工程",
    "gpa": 82,
    "gpa_scale": 100,
    "target_field": "计算机与数据",
    "intake": "2027 S1",
    "english_score": "IELTS 6.5",
    "experience_summary": "AI 应用项目",
}


CASES: list[dict[str, Any]] = [
    {"id": "relevant-strong", "overrides": {}, "expected": {"unsw-master-it": "稳妥"}},
    {"id": "relevant-medium", "overrides": {"gpa": 74}, "expected": {"unsw-master-it": "匹配"}},
    {"id": "relevant-borderline", "overrides": {"gpa": 68}, "expected": {"unsw-master-it": "冲刺"}},
    {"id": "relevant-low", "overrides": {"gpa": 60}, "expected": {"unsw-master-it": "暂不推荐"}},
    {"id": "non-cognate", "overrides": {"undergraduate_major": "市场营销"}, "expected": {"monash-master-cs": "暂不推荐", "uq-master-data-science": "暂不推荐"}},
    {"id": "missing-language", "overrides": {"english_score": None}, "expected_missing": ["语言成绩"]},
    {"id": "missing-experience", "overrides": {"experience_summary": None}, "expected_missing": ["相关实习、科研或项目经历"]},
    {"id": "gpa-four-scale", "overrides": {"gpa": 3.4, "gpa_scale": 4}, "expected": {"usyd-master-cs": "稳妥"}},
    {"id": "non-211-special-rule", "overrides": {"gpa": 68}, "expected": {"unsw-master-it": "冲刺", "usyd-master-cs": "冲刺"}},
    {"id": "high-non-cognate", "overrides": {"undergraduate_major": "英语", "gpa": 90}, "expected": {"monash-master-ai": "稳妥", "monash-master-cs": "暂不推荐"}},
]


def evaluate() -> dict[str, float | int]:
    checked = correct = missing_checked = missing_correct = 0
    citation_total = citation_present = tool_total = tool_completed = 0
    durations: list[float] = []

    for case in CASES:
        profile_data = {**BASE, **case.get("overrides", {})}
        started = perf_counter()
        result = run_recommendation_agent(ApplicantProfile.model_validate(profile_data))
        durations.append((perf_counter() - started) * 1000)
        by_slug = {item.program.slug: item for item in result.recommendations}

        for slug, expected_tier in case.get("expected", {}).items():
            checked += 1
            correct += int(by_slug[slug].tier == expected_tier)
        for item in case.get("expected_missing", []):
            missing_checked += 1
            missing_correct += int(item in result.missing_information)
        for item in result.recommendations:
            citation_total += 1
            citation_present += int(bool(item.citations and item.citations[0].url.startswith("https://")))
        for step in result.tool_trace[:5]:
            tool_total += 1
            tool_completed += int(step.status == "completed")

    return {
        "cases": len(CASES),
        "hard_constraint_accuracy": round(correct / checked, 4),
        "missing_information_accuracy": round(missing_correct / missing_checked, 4),
        "citation_coverage": round(citation_present / citation_total, 4),
        "tool_success_rate": round(tool_completed / tool_total, 4),
        "average_runtime_ms": round(sum(durations) / len(durations), 3),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
