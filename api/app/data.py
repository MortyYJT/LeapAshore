from .models import University


UNIVERSITIES = [
    University(slug="unimelb", name="墨尔本大学", city="墨尔本", fields=["计算机与数据", "商科与金融", "教育与社会科学"], threshold=88, official_url="https://www.unimelb.edu.au/", note="研究导向强，热门课程竞争激烈。"),
    University(slug="anu", name="澳大利亚国立大学", city="堪培拉", fields=["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold=87, official_url="https://www.anu.edu.au/", note="学术与研究资源突出，适合目标清晰的申请者。"),
    University(slug="unsw", name="新南威尔士大学", city="悉尼", fields=["计算机与数据", "商科与金融", "工程"], threshold=85, official_url="https://www.unsw.edu.au/", note="工程、技术与就业连接紧密。"),
    University(slug="usyd", name="悉尼大学", city="悉尼", fields=["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold=85, official_url="https://www.sydney.edu.au/", note="学科覆盖广，热门方向需要更强的综合背景。"),
    University(slug="monash", name="蒙纳士大学", city="墨尔本", fields=["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold=82, official_url="https://www.monash.edu/", note="课程选择丰富，产业合作与实践机会较多。"),
    University(slug="uq", name="昆士兰大学", city="布里斯班", fields=["计算机与数据", "商科与金融", "工程", "生命科学"], threshold=82, official_url="https://www.uq.edu.au/", note="科研实力与校园体验兼具。"),
    University(slug="uwa", name="西澳大学", city="珀斯", fields=["计算机与数据", "商科与金融", "工程", "生命科学"], threshold=78, official_url="https://www.uwa.edu.au/", note="工程与资源相关方向具有地域优势。"),
    University(slug="adelaide", name="阿德莱德大学", city="阿德莱德", fields=["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold=78, official_url="https://adelaideuni.edu.au/", note="2026 年正式启用，由原阿德莱德大学与南澳大学整合而成。"),
]
