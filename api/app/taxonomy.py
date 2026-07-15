from typing import Literal, TypeAlias


DegreeLevel: TypeAlias = Literal["本科", "授课型硕士", "研究型硕士", "博士"]
StudyArea: TypeAlias = Literal[
    "计算机与数据",
    "商科与金融",
    "工程",
    "教育与社会科学",
    "生命科学",
    "医学与健康",
    "法律与犯罪学",
    "自然科学与数学",
    "人文与语言",
    "建筑规划与设计",
    "传媒艺术与音乐",
    "环境与农业",
]
EducationLevel: TypeAlias = Literal["高中", "本科", "硕士", "其他"]


DEGREE_LEVELS: tuple[DegreeLevel, ...] = ("本科", "授课型硕士", "研究型硕士", "博士")
STUDY_AREAS: tuple[StudyArea, ...] = (
    "计算机与数据",
    "商科与金融",
    "工程",
    "教育与社会科学",
    "生命科学",
    "医学与健康",
    "法律与犯罪学",
    "自然科学与数学",
    "人文与语言",
    "建筑规划与设计",
    "传媒艺术与音乐",
    "环境与农业",
)
