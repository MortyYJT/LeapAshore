from ..data import UNIVERSITIES
from ..models import ApplicantProfile, Recommendation, RecommendationResponse


def normalize_gpa(profile: ApplicantProfile) -> int:
    return min(100, round(profile.gpa / profile.gpa_scale * 100))


def generate_recommendations(profile: ApplicantProfile) -> RecommendationResponse:
    """Generate explainable planning tiers; scores are not admission probabilities."""
    gpa = normalize_gpa(profile)
    school_bonus = 3 if profile.school_tier in {"985", "海外重点"} else 2 if profile.school_tier == "211/双一流" else 0
    english_bonus = 1 if profile.english_score else 0
    results: list[Recommendation] = []

    for university in UNIVERSITIES:
        field_bonus = 2 if profile.target_field in university.fields else -4
        gap = gpa + school_bonus + english_bonus + field_bonus - university.threshold
        tier = "稳妥" if gap >= 5 else "匹配" if gap >= -2 else "冲刺"
        score = max(55, min(96, 76 + gap))
        reasons = [
            f"标准化 GPA 为 {gpa}/100，已纳入学校级 Demo 基线比较。",
            f"本科院校背景按“{profile.school_tier}”参与评估。",
        ]
        risks = []
        if profile.target_field not in university.fields:
            risks.append("当前目标方向不是本 Demo 的重点标签，需要核验具体课程。")
        if not profile.english_score:
            risks.append("尚未提供语言成绩，推荐完整度有限。")
        if not risks:
            risks.append("具体课程的先修课与小分要求尚未核验。")

        results.append(
            Recommendation(
                university=university,
                tier=tier,
                match_score=score,
                reasons=reasons,
                risks=risks,
                next_action="进入学校官网，选择具体课程并核验最新入学要求。",
            )
        )

    results.sort(key=lambda item: ({"匹配": 0, "冲刺": 1, "稳妥": 2}[item.tier], -item.match_score))
    return RecommendationResponse(
        algorithm_version="0.1.0",
        disclaimer="学校级推荐仅用于早期规划，不构成录取承诺；最终要求以具体课程官网为准。",
        recommendations=results,
    )
