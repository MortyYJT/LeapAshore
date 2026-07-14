from typing import Literal

from pydantic import BaseModel, Field


class ApplicantProfile(BaseModel):
    undergraduate_school: str = Field(min_length=1, max_length=120)
    school_tier: Literal["985", "211/双一流", "双非", "海外重点", "其他"]
    undergraduate_major: str = Field(min_length=1, max_length=120)
    gpa: float = Field(gt=0)
    gpa_scale: float = Field(gt=0)
    target_field: Literal["计算机与数据", "商科与金融", "工程", "教育与社会科学", "生命科学"]
    intake: str = "2027 S1"
    english_score: str | None = None
    experience_summary: str | None = None


class University(BaseModel):
    slug: str
    name: str
    city: str
    fields: list[str]
    threshold: int
    official_url: str
    note: str


class Recommendation(BaseModel):
    university: University
    tier: Literal["冲刺", "匹配", "稳妥"]
    match_score: int
    reasons: list[str]
    risks: list[str]
    next_action: str


class RecommendationResponse(BaseModel):
    algorithm_version: str
    disclaimer: str
    recommendations: list[Recommendation]
