"""Seed the placeholder program catalogue.

The values mirror web/lib/programs.ts, which is the current source of truth until the annotation stage
replaces both with reviewed data. Every record is written as 待核验.

The frontend carries two program fields that have no column here. ``excerpt`` is a manual summary
rather than captured page text, so it is dropped on purpose. ``university`` is the frontend's display
name for the institution, which the seed keeps only as ``university_id`` pointing at
``universities.name``: the name lives once in the university row instead of being copied onto every
program. In the other direction the model has two booleans the frontend has no counterpart for,
``requires_supervisor`` and ``research_proposal_required``; both stay at their model default of False.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus

# The frontend has no university table, so name_en and official_url are the two values the brief
# leaves to the seed author. Every official_url is the university domain of the course page the
# matching program already cites.
UNIVERSITIES = [
    {
        "id": "unsw",
        "name": "新南威尔士大学",
        "name_en": "UNSW Sydney",
        "city": "悉尼",
        "official_url": "https://www.unsw.edu.au/",
    },
    {
        "id": "usyd",
        "name": "悉尼大学",
        "name_en": "University of Sydney",
        "city": "悉尼",
        "official_url": "https://www.sydney.edu.au/",
    },
    {
        "id": "monash",
        "name": "蒙纳士大学",
        "name_en": "Monash University",
        "city": "墨尔本",
        "official_url": "https://www.monash.edu/",
    },
    {
        "id": "uq",
        "name": "昆士兰大学",
        "name_en": "University of Queensland",
        "city": "布里斯班",
        "official_url": "https://www.uq.edu.au/",
    },
    {
        "id": "uwa",
        "name": "西澳大学",
        "name_en": "University of Western Australia",
        "city": "珀斯",
        "official_url": "https://www.uwa.edu.au/",
    },
]

# Each entry keeps the same official url and title the frontend already cites. The frontend mixes the
# local name and the English name between 大学 / 项目; ``name`` and ``name_en`` follow that split.
PROGRAMS = [
    {
        "id": "unsw-master-of-it",
        "university_id": "unsw",
        "name": "信息技术硕士",
        "name_en": "Master of Information Technology",
        "city": "悉尼",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "2 年",
        "minimum_mark": 65,
        "non_211_minimum_mark": 70,
        "requires_cognate": False,
        "english_requirement": "按 UNSW 英语语言要求核验",
        "source_url": (
            "https://www.unsw.edu.au/study/postgraduate/"
            "master-of-information-technology?studentType=International"
        ),
        "source_title": "UNSW Master of Information Technology",
        "prerequisites": [],
    },
    {
        "id": "usyd-master-cs",
        "university_id": "usyd",
        "name": "计算机科学硕士",
        "name_en": "Master of Computer Science",
        "city": "悉尼",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "2 年",
        "minimum_mark": 65,
        "non_211_minimum_mark": None,
        "requires_cognate": False,
        "english_requirement": "按悉尼大学课程页英语要求核验",
        "source_url": (
            "https://www.sydney.edu.au/content/courses/courses/pc/"
            "master-of-computer-science.html"
        ),
        "source_title": "University of Sydney Master of Computer Science",
        "prerequisites": [],
    },
    {
        "id": "monash-master-ai",
        "university_id": "monash",
        "name": "人工智能硕士",
        "name_en": "Master of Artificial Intelligence",
        "city": "墨尔本",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "1.5–2 年",
        "minimum_mark": 60,
        "non_211_minimum_mark": None,
        "requires_cognate": False,
        "english_requirement": "需同时满足 Monash 英语要求",
        "source_url": (
            "https://www.monash.edu/study/courses/find-a-course/"
            "artificial-intelligence-c6007"
        ),
        "source_title": "Monash Master of Artificial Intelligence",
        "prerequisites": [],
    },
    {
        "id": "monash-master-cs",
        "university_id": "monash",
        "name": "计算机科学硕士",
        "name_en": "Master of Computer Science",
        "city": "墨尔本",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "1.5–2 年",
        "minimum_mark": 60,
        "non_211_minimum_mark": None,
        "requires_cognate": True,
        "english_requirement": "需同时满足 Monash 英语要求",
        "source_url": (
            "https://www.monash.edu/study/courses/find-a-course/"
            "computer-science-c6008"
        ),
        "source_title": "Monash Master of Computer Science",
        "prerequisites": ["编程", "算法或数据结构"],
    },
    {
        "id": "uq-master-data-science",
        "university_id": "uq",
        "name": "数据科学硕士",
        "name_en": "Master of Data Science",
        "city": "布里斯班",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "1.5–2 年",
        "minimum_mark": 71.4,
        "non_211_minimum_mark": None,
        "requires_cognate": True,
        "english_requirement": "IELTS 6.5，单项不低于 6.0",
        "source_url": (
            "https://study.uq.edu.au/study-options/programs/master-data-science-5660"
        ),
        "source_title": "UQ Master of Data Science",
        "prerequisites": ["微积分或高等数学", "线性代数与统计，或编程与数据库"],
    },
    {
        "id": "uwa-master-it",
        "university_id": "uwa",
        "name": "信息技术硕士",
        "name_en": "Master of Information Technology",
        "city": "珀斯",
        "degree_level": "授课型硕士",
        "field": "计算机与数据",
        "duration": "1.5–2 年",
        "minimum_mark": 65,
        "non_211_minimum_mark": None,
        "requires_cognate": False,
        "english_requirement": "IELTS 6.5，单项不低于 6.0",
        "source_url": (
            "https://www.uwa.edu.au/study/courses/master-of-information-technology"
        ),
        "source_title": "UWA Master of Information Technology",
        "prerequisites": ["Mathematics Methods ATAR 或同等数学基础"],
    },
]


def seed_programs(session: Session) -> int:
    """Insert missing universities, sources and programs. Returns how many programs were added."""
    added = 0

    for row in UNIVERSITIES:
        if session.get(University, row["id"]) is None:
            session.add(University(**row))
    session.flush()

    for row in PROGRAMS:
        # A program that already exists is skipped whole, so its source and prerequisites are not
        # written twice either.
        if session.get(Program, row["id"]) is not None:
            continue

        source = session.execute(
            select(Source).where(Source.url == row["source_url"])
        ).scalar_one_or_none()
        if source is None:
            source = Source(
                id=f"src-{row['id']}",
                url=row["source_url"],
                title=row["source_title"],
                publisher=row["university_id"],
                domain=row["source_url"].split("/")[2],
                status=SourceStatus.UNVERIFIED,
                verified_at=None,
            )
            session.add(source)
            session.flush()

        session.add(
            Program(
                id=row["id"],
                university_id=row["university_id"],
                name=row["name"],
                name_en=row["name_en"],
                city=row["city"],
                degree_level=row["degree_level"],
                field=row["field"],
                duration=row["duration"],
                minimum_mark=row["minimum_mark"],
                non_211_minimum_mark=row.get("non_211_minimum_mark"),
                requires_cognate=row.get("requires_cognate", False),
                english_requirement=row.get("english_requirement"),
                source_id=source.id,
                # The string matches the brief's column contract, not SourceStatus.
                data_status="待核验",
            )
        )

        for index, label in enumerate(row.get("prerequisites", [])):
            session.add(
                ProgramPrerequisite(
                    id=f"{row['id']}-pre-{index}",
                    program_id=row["id"],
                    label=label,
                    sort_order=index,
                )
            )
        added += 1

    session.commit()
    return added
