from ..models import ActionPlanItem, ActionPlanResponse, AgentRecommendationResponse


def build_action_plan(result: AgentRecommendationResponse) -> ActionPlanResponse:
    items = [
        ActionPlanItem(id="verify-transcript", title="确认成绩单与先修课程", detail="整理中英文成绩单，逐项确认数学、算法、编程与数据库课程。", priority="P0"),
        ActionPlanItem(id="verify-language", title="确认语言成绩与小分", detail="对照每个项目的英语要求，记录总分、单项和考试日期。", priority="P0"),
        ActionPlanItem(id="shortlist", title="确认最终申请组合", detail="从推荐中选择 2 个冲刺、2–3 个匹配和 1 个稳妥项目。", priority="P1"),
        ActionPlanItem(id="deadlines", title="建立申请截止日期日历", detail="以项目官网为准，记录开放时间、轮次和材料截止日期。", priority="P1"),
        ActionPlanItem(id="materials", title="准备申请材料", detail="整理简历、个人陈述、推荐信和官方成绩单。", priority="P2"),
    ]
    if not result.missing_information:
        items[0].status = "已完成"
        items[1].status = "已完成"
    return ActionPlanResponse(run_id=result.run_id, items=items)
