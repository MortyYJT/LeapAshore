from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.models import ApplicantProfile, ApplicationTask
from app.services.advisor import fallback_plan
from app.services.agent import run_recommendation_agent
from app.services.deepseek_advisor import safe_tool_actions


PROFILE = ApplicantProfile(
    undergraduate_school="评测大学", school_tier="双非", undergraduate_major="软件工程",
    gpa=82, gpa_scale=100, target_field="计算机与数据", intake="2027 S1",
    english_score="IELTS 6.5", coursework_summary="高等数学、数据结构、数据库",
    experience_summary="AI 应用项目", career_goal="AI 应用工程师",
)
NOW = datetime(2026, 7, 15, tzinfo=UTC)
TASKS = [
    ApplicationTask(
        id="task_transcript", title="准备英文成绩单", detail="学校盖章版本", category="成绩单",
        priority="P0", status="待开始", phase="academic", created_at=NOW, updated_at=NOW,
    ),
    ApplicationTask(
        id="task_ielts", title="预约雅思考试", detail="选择考试场次", category="语言",
        priority="P0", status="待开始", phase="language", created_at=NOW, updated_at=NOW,
    ),
]


CASES: list[dict[str, Any]] = [
    {"id": "budget", "message": "把每年预算改成 50 万", "expected": "update_profile"},
    {"id": "ielts", "message": "我的雅思是 7.0", "expected": "update_profile"},
    {"id": "intake-s1", "message": "入学时间改成 2028 S1", "expected": "update_profile"},
    {"id": "intake-s2", "message": "我准备申请 2027 年 7 月入学", "expected": "update_profile"},
    {"id": "city", "message": "城市偏好改成悉尼和墨尔本优先", "expected": "update_profile"},
    {"id": "rerank", "message": "请重新推荐选校方案", "expected": "run_recommendation"},
    {"id": "task-create", "message": "提醒我联系推荐人", "expected": "create_task"},
    {"id": "task-create-explicit", "message": "创建任务：整理个人陈述素材", "expected": "create_task"},
    {"id": "primary-unsw", "message": "把 UNSW 设为首选项目", "expected": "set_application_choice"},
    {"id": "apply-usyd", "message": "把悉尼大学确定申请", "expected": "set_application_choice"},
    {"id": "exclude-uq", "message": "UQ 我不考虑了", "expected": "set_application_choice"},
    {"id": "consider-uwa", "message": "把 UWA 改成待定", "expected": "set_application_choice"},
    {"id": "apply-monash-ai", "message": "把 Master of Artificial Intelligence 确定申请", "expected": "set_application_choice"},
    {"id": "complete-transcript", "message": "准备英文成绩单已经完成", "expected": "update_task"},
    {"id": "start-ielts", "message": "开始处理预约雅思考试", "expected": "update_task"},
    {"id": "missing-materials", "message": "我还缺哪些材料？", "expected": "answer"},
    {"id": "tradeoff", "message": "我应该更看重课程还是城市？", "expected": "answer"},
    {"id": "research", "message": "研究型硕士应该先准备什么？", "expected": "answer"},
    {"id": "phd", "message": "博士套磁需要注意什么？", "expected": "answer"},
    {"id": "bachelor", "message": "本科申请要准备哪些学术材料？", "expected": "answer"},
    {"id": "no-deadline-invention", "message": "告诉我 UNSW 的官方截止日期，不知道就直说", "expected": "answer", "fact_guard": True},
    {"id": "no-fee-invention", "message": "这个项目今年学费到底是多少？不要猜", "expected": "run_recommendation", "fact_guard": True},
    {"id": "no-guarantee", "message": "你能保证我被录取吗？", "expected": "answer", "fact_guard": True},
    {"id": "prerequisite-source", "message": "先修课要求没有来源时请拒绝编造", "expected": "answer", "fact_guard": True},
]


def evaluate_advisor() -> dict[str, float | int]:
    result = run_recommendation_agent(PROFILE)
    correct = 0
    hallucinations = 0
    forbidden_claim_patterns = ["截止日期是", "学费为", "保证录取", "录取率为", "一定能录取"]
    for case in CASES:
        actions = safe_tool_actions(case["message"], PROFILE, result, TASKS)
        correct += int(bool(actions) and actions[0].tool == case["expected"])
        if case.get("fact_guard"):
            reply = fallback_plan(case["message"], PROFILE)["reply"]
            hallucinations += sum(pattern in reply for pattern in forbidden_claim_patterns)
    return {
        "cases": len(CASES),
        "tool_selection_accuracy": round(correct / len(CASES), 4),
        "citation_fact_hallucinations": hallucinations,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_advisor(), ensure_ascii=False, indent=2))
