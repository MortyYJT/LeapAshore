"""Which study area a program belongs to, read from its English name.

The CRICOS catalogue states each Australian course's field, and `app.seed_catalog.study_area` maps that to
the interface's twelve study areas. A program the requirement importer collects from any other country
has only its name. This module reads the area from the name with ordered keyword rules, so the result
page can list every program in the applicant's target field, not only the Australian ones.

The rules are checked against the 2,920 CRICOS courses, whose areas are known
(`tests/test_collect_fields.py`). The first matching rule wins, so the more specific phrases come first:
"software engineering" is computing before "engineering" can claim it, as CRICOS files it. A name no rule
matches stays `None`: an unclassified program is listed as such rather than forced into an area.

A study area is a filing label for search, not an admission fact, so a wrong guess files a program
under a neighbouring heading; it never changes a requirement, a source or a verification state.
"""

import re

# (pattern, study area), first match wins. Patterns are matched against the lower-cased name.
RULES: list[tuple[str, str]] = [
    # Law before "international" and "business": an LLM in business law is a law degree.
    (r"\bll\.?m\b|\blaws?\b|\blegal\b|juris|criminolog|criminal justice|taxation", "法律与犯罪学"),
    # Language work before "communication" claims it for the media heading.
    (r"translation|interpreting|linguistic|theolog|divinity|religio", "人文与语言"),
    # Running a health service is management, as CRICOS files it.
    (r"health (services? )?(management|leadership|administration)|healthcare management|sports? management"
     r"|valuation|property|real estate", "商科与金融"),
    # Psychology is filed under society and culture by CRICOS, even when it is clinical.
    (r"psycholog|counsell?ing|social work|sociolog|anthropolog|political|politics|international relations"
     r"|public policy|policy studies|public administration|\bmpa\b|development studies|social science"
     r"|gender|demograph|affairs|security studies|international security|conflict|peace|human rights"
     r"|welfare|geograph|cultural studies|international studies|area studies|asian studies|global studies"
     r"|strategic studies|(?<!cyber )\bsecurity studies|behaviou?r|economics|econometric|economic analysis"
     r"|bioethic|genocide|african studies|pacific studies|globalisation|globalization", "教育与社会科学"),
    (r"\beducation|early childhood|teaching|\bteacher|\bm\.?\s?ed\b|pedagog|tesol|curriculum", "教育与社会科学"),
    (r"computer|computing|software|data science|data analytics|\bdata\b|artificial intelligence|machine learning"
     r"|cyber|information technology|\bit\b|informatics|information systems|information security"
     r"|human-computer|\bhci\b|games? development|internet of things|informati[kq]|embedded systems"
     r"|information governance|digital transformation", "计算机与数据"),
    (r"biomedical engineering|medical engineering", "工程"),
    (r"medicine|medical|clinical|nursing|midwif|\bhealth|pharmac|physiotherap|dentist|dental|optometr"
     r"|nutrition|dietetic|epidemiolog|occupational therapy|speech pathology|audiolog|radiograph"
     r"|sonograph|paramedic|rehabilitation|ageing|aging|surgery|veterinar|chiropract|podiatr|osteopath"
     r"|hygiene|imaging|kinesiolog|exercise|sport|critical care|physical therapy|infectious|advanced practice"
     r"|forensic", "医学与健康"),
    (r"architect|urban|planning|landscape|built environment|construction|quantity surveying", "建筑规划与设计"),
    (r"engineering|engineer|mechatronic|robotic|aerospace|aeronaut|electrical|electronic|mechanical"
     r"|civil|chemical|materials science|mining|petroleum|telecommunication|nanotechnolog|électr"
     r"|manufacturing|quantum technolog|carbon technolog|automation|automatique", "工程"),
    (r"business|management|\bmba\b|finance|financial|accounting|accountancy|commerce|marketing|actuarial"
     r"|banking|human resource|supply chain|logistics|entrepreneur|innovation|tourism|hospitality"
     r"|event|leadership|administration|analytics|fintech|investment|insurance|procurement", "商科与金融"),
    (r"music|\bart\b|\barts\b|fine art|film|cinema|media|journalism|communication|creative|design"
     r"|photograph|theatre|theater|performance|animation|screen|writing|curatorial|museum", "传媒艺术与音乐"),
    (r"agricultur|agronom|forest|biomass|environment|sustainab|climate|conservation|ecolog|marine|water"
     r"|food|wine|viticulture|fisheries|natural resource|energy", "环境与农业"),
    (r"biotech|biolog|bioscience|life science|genetic|genomic|molecular|neuroscience|biochem|microbio"
     r"|immunolog|bioinformatic", "生命科学"),
    (r"mathemat|statistic|physics|chemistry|geolog|earth science|geoscience|astronom|\bscience\b"
     r"|quantitative|nanoscience|quantum|chimie|computational mechanics|advanced materials", "自然科学与数学"),
    (r"language|history|philosoph|literature|english|humanities|classics|cultural|librar|archiv|heritage"
     r"|archaeolog|aesthetic|american studies", "人文与语言"),
]

_COMPILED = [(re.compile(pattern), area) for pattern, area in RULES]


def study_area_from_name(name: str | None) -> str | None:
    """The study area a program's English name points to, or None when no rule matches."""
    if not name:
        return None
    text = name.lower()
    for pattern, area in _COMPILED:
        if pattern.search(text):
            return area
    return None
