from .models import CatalogCoverage
from .taxonomy import DEGREE_LEVELS, STUDY_AREAS


# These are official discovery entry points, not course-level admission evidence.
# A coverage cell only means that OfferPilot can route the user to the university
# catalogue for this search intent. It must never be used as an admission rule.
CATALOG_SOURCES = (
    ("anu", "澳大利亚国立大学", "堪培拉", "https://programsandcourses.anu.edu.au/Search"),
    ("unimelb", "墨尔本大学", "墨尔本", "https://study.unimelb.edu.au/"),
    ("unsw", "新南威尔士大学", "悉尼", "https://www.unsw.edu.au/study/find-a-degree-or-course"),
    ("usyd", "悉尼大学", "悉尼", "https://www.sydney.edu.au/courses/search.html"),
    ("monash", "蒙纳士大学", "墨尔本", "https://www.monash.edu/study/courses/find-a-course"),
    ("uq", "昆士兰大学", "布里斯班", "https://study.uq.edu.au/study-options/programs?type=program"),
    ("uwa", "西澳大学", "珀斯", "https://www.uwa.edu.au/study/courses"),
    ("adelaide", "阿德莱德大学", "阿德莱德", "https://adelaideuni.edu.au/study/degrees"),
)


CATALOG_COVERAGE = [
    CatalogCoverage(
        university_slug=slug,
        university=university,
        city=city,
        degree_level=degree_level,
        field=field,
        catalog_url=url,
        source_title=f"{university}官方课程目录",
    )
    for slug, university, city, url in CATALOG_SOURCES
    for degree_level in DEGREE_LEVELS
    for field in STUDY_AREAS
]
