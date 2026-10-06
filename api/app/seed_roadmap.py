"""Seed the roadmap definition.

The six existing phases and their materials mirror web/lib/roadmap.ts, which stays the source of truth
until the annotation stage replaces both with reviewed data. The visa phase is new: it is authored
here and every material under it cites the Department of Home Affairs Genuine Student page.

The mapping from the frontend shape to the two tables is deliberate and worth writing down, because
three of the names differ and a rename is where a value gets lost:

- ``PHASE_DEFS[].id`` becomes ``roadmap_phases.key`` and ``MATERIALS[...][].id`` becomes
  ``material_templates.key``. The frontend's id is the join key ``roadmap_tasks.material_key`` will
  use, so the spelling is the contract, not a label.
- ``PHASE_DEFS[].detail`` becomes ``roadmap_phases.subtitle``. The column is the only place a phase
  description can live, and the frontend renders it under the title; leaving it empty would drop the
  phase's description from every phase the applicant sees. The visa phase has no counterpart to
  transcribe, so its subtitle stays ``None`` rather than being written from memory.
- ``MATERIALS[...][].label`` becomes ``material_templates.title``; ``detail`` and ``appliesTo`` come
  across unchanged. A material's ``appliesTo`` is kept verbatim even when it is not ``"all"``
  (``spe-portfolio`` is ``portfolio`` and ``spe-research`` is ``research``): the frontend filters on
  it, so dropping those two entries to make the count smaller would drop two real requirements.
- ``sort_order`` is the index in the frontend's own arrays. The TypeScript carries order as array
  position, so the index is the only faithful translation, and it is what makes the served list come
  back in the order the frontend renders today.
- Not every frontend field has a column, and none is invented to make room for it. ``PHASE_DEFS`` has
  no subtitle of its own, and both structures carry nothing else this seed would have to drop.

Two numbers disagree with the M2a plan, and the disagreement is settled knowledge rather than a
choice. The plan records "29 materials"; web/lib/roadmap.ts holds 31 (selection 5, academic 5,
language 4, specialized 6, submission 5, decision 6), counted both by reading the file and by
importing it. The 29 comes from the frontend's own test ``counts 29 materials for the taught-master
default``, which counts the materials *visible* to the default profile: ``spe-portfolio`` and
``spe-research`` are filtered out for a taught master because their ``appliesTo`` is ``"portfolio"``
and ``"research"``. Both are real requirements for other applicants, and ``applies_to`` is the column
that keeps them expressible, so all 31 entries are transcribed here.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source, SourceStatus

# The official page both visa materials cite. Verified by a human before the status moves off
# 待核验; ``verified_at`` is left unset because no one has checked it yet.
GS_SOURCE_URL = (
    "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/"
    "genuine-student-requirement"
)

# Transcribed from PHASE_DEFS in web/lib/roadmap.ts, entry for entry and in its order:
# id -> key, title -> title, detail -> subtitle, offsetDays -> offset_days, index -> sort_order.
PHASES = [
    {
        "key": "selection",
        "title": "锁定申请组合",
        "subtitle": "确定申请哪些项目，并标出一个首选。",
        "offset_days": 330,
        "sort_order": 0,
    },
    {
        "key": "academic",
        "title": "学术与身份材料",
        "subtitle": "整理成绩单、在读或学位证明、护照及认证材料。",
        "offset_days": 270,
        "sort_order": 1,
    },
    {
        "key": "language",
        "title": "语言准备",
        "subtitle": "对照每个项目的总分与单项要求，安排考试。",
        "offset_days": 240,
        "sort_order": 2,
    },
    {
        "key": "specialized",
        "title": "专项申请材料",
        "subtitle": "准备简历、陈述、推荐信及专业特有材料。",
        "offset_days": 210,
        "sort_order": 3,
    },
    {
        "key": "submission",
        "title": "提交申请",
        "subtitle": "逐校核验官方截止日期，完成提交并保存回执。",
        "offset_days": 150,
        "sort_order": 4,
    },
    {
        "key": "decision",
        "title": "Offer 与入学",
        "subtitle": "跟进补件、Offer、押金、CoE 与签证安排。",
        "offset_days": 60,
        "sort_order": 5,
    },
    # Authored here rather than transcribed: the frontend has no visa phase. Its offset sits inside
    # the decision phase's 60 days because the visa is applied for after the CoE.
    {
        "key": "visa",
        "title": "签证与行前",
        "offset_days": 30,
        "sort_order": 6,
    },
]

# Transcribed from MATERIALS in web/lib/roadmap.ts: the record's phase key -> phase, id -> key,
# label -> title, detail -> detail, appliesTo -> applies_to, and the index within each phase's array
# -> sort_order. Nothing is reworded, reordered or summarised.
MATERIALS = [
    # selection
    {
        "key": "sel-goal",
        "phase": "selection",
        "title": "明确目标国家与方向",
        "detail": "结合预算、就业方向和家庭意见，先锁定国家与专业大类。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "sel-shortlist",
        "phase": "selection",
        "title": "筛选候选项目清单",
        "detail": "从官方课程目录里挑出 8–12 个候选项目，逐一记录官网链接。",
        "applies_to": "all",
        "sort_order": 1,
    },
    {
        "key": "sel-check",
        "phase": "selection",
        "title": "逐项核对门槛",
        "detail": "对每个候选项目核对均分基线、院校层次要求、先修课与语言要求。",
        "applies_to": "all",
        "sort_order": 2,
    },
    {
        "key": "sel-portfolio",
        "phase": "selection",
        "title": "确定申请组合（冲/稳/保）",
        "detail": "从候选中选出 5–8 个，分成冲刺、匹配、稳妥三档。",
        "applies_to": "all",
        "sort_order": 3,
    },
    {
        "key": "sel-primary",
        "phase": "selection",
        "title": "标出首选项目",
        "detail": "确定一个最想去的项目，后续材料准备以它为主。",
        "applies_to": "all",
        "sort_order": 4,
    },
    # academic
    {
        "key": "aca-transcript",
        "phase": "academic",
        "title": "中英文成绩单（学校盖章）",
        "detail": "在读生通常需要 5–6 学期成绩；毕业后需完整成绩单。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "aca-enroll",
        "phase": "academic",
        "title": "在读证明 / 学位证毕业证",
        "detail": "在读生开在读证明；已毕业提供学位证与毕业证。",
        "applies_to": "all",
        "sort_order": 1,
    },
    {
        "key": "aca-scale",
        "phase": "academic",
        "title": "评分标准说明（GPA 换算口径）",
        "detail": "学校评分体系不是百分制时，需要官方换算说明，否则对方按最低口径折算。",
        "applies_to": "all",
        "sort_order": 2,
    },
    {
        "key": "aca-passport",
        "phase": "academic",
        "title": "护照首页扫描件",
        "detail": "注意有效期需覆盖整个学习周期。",
        "applies_to": "all",
        "sort_order": 3,
    },
    {
        "key": "aca-verify",
        "phase": "academic",
        "title": "学信网 / 学位网认证（如需）",
        "detail": "部分学校要求 CHESICC 认证报告，办理需要时间。",
        "applies_to": "all",
        "sort_order": 4,
    },
    # language
    {
        "key": "lang-requirement",
        "phase": "language",
        "title": "确认每个项目的总分与单项要求",
        "detail": "最容易踩的坑：总分够但单项不够。逐项记录到项目卡片。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "lang-book",
        "phase": "language",
        "title": "报名并规划考试场次",
        "detail": "预留至少两次考试机会，避免出分晚于申请截止。",
        "applies_to": "all",
        "sort_order": 1,
    },
    {
        "key": "lang-score",
        "phase": "language",
        "title": "取得成绩并核对有效期",
        "detail": "多数学校要求成绩在入学时仍在有效期内。",
        "applies_to": "all",
        "sort_order": 2,
    },
    {
        "key": "lang-send",
        "phase": "language",
        "title": "成绩送分（如需）",
        "detail": "部分学校要求官方送分而非上传截图。",
        "applies_to": "all",
        "sort_order": 3,
    },
    # specialized
    {
        "key": "spe-cv",
        "phase": "specialized",
        "title": "学术简历（CV）",
        "detail": "一页为主，突出课程项目、实习与技能。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "spe-ps",
        "phase": "specialized",
        "title": "个人陈述（PS / SOP）",
        "detail": "针对每个项目单独调整，说明选校动机与职业目标。",
        "applies_to": "all",
        "sort_order": 1,
    },
    {
        "key": "spe-ref",
        "phase": "specialized",
        "title": "推荐信 2–3 封",
        "detail": "优先学术推荐人；提前 1 个月联系并给足材料。",
        "applies_to": "all",
        "sort_order": 2,
    },
    {
        "key": "spe-portfolio",
        "phase": "specialized",
        "title": "作品集",
        "detail": "设计、建筑、艺术类专业需要，注意各校格式与页数限制。",
        "applies_to": "portfolio",
        "sort_order": 3,
    },
    {
        "key": "spe-research",
        "phase": "specialized",
        "title": "研究计划 + 导师匹配",
        "detail": "研究型硕士与博士通常需要研究计划与导师接收意向。",
        "applies_to": "research",
        "sort_order": 4,
    },
    {
        "key": "spe-work",
        "phase": "specialized",
        "title": "工作 / 实习证明",
        "detail": "部分项目对工作经验有要求或有加分。",
        "applies_to": "all",
        "sort_order": 5,
    },
    # submission
    {
        "key": "sub-account",
        "phase": "submission",
        "title": "逐校注册申请账号",
        "detail": "每个学校系统独立，建议统一记录账号与申请编号。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "sub-form",
        "phase": "submission",
        "title": "填写在线申请表",
        "detail": "注意姓名拼写与护照一致。",
        "applies_to": "all",
        "sort_order": 1,
    },
    {
        "key": "sub-upload",
        "phase": "submission",
        "title": "上传全部材料",
        "detail": "对照清单逐个勾选，避免漏传导致审核延后。",
        "applies_to": "all",
        "sort_order": 2,
    },
    {
        "key": "sub-fee",
        "phase": "submission",
        "title": "缴纳申请费",
        "detail": "多数澳洲院校申请费在 100 澳元上下，注意是否可退。",
        "applies_to": "all",
        "sort_order": 3,
    },
    {
        "key": "sub-receipt",
        "phase": "submission",
        "title": "保存提交回执与申请编号",
        "detail": "后续补件和查询都要用。",
        "applies_to": "all",
        "sort_order": 4,
    },
    # decision
    {
        "key": "dec-follow",
        "phase": "decision",
        "title": "跟进补件与审核状态",
        "detail": "定期查看邮箱与申请系统，补件通常有时间限制。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "dec-interview",
        "phase": "decision",
        "title": "面试准备（如需要）",
        "detail": "部分项目或奖学金会安排面试。",
        "applies_to": "all",
        "sort_order": 1,
    },
    {
        "key": "dec-compare",
        "phase": "decision",
        "title": "比较 Offer 条件",
        "detail": "注意条件 Offer 上的均分、语言或补充材料要求。",
        "applies_to": "all",
        "sort_order": 2,
    },
    {
        "key": "dec-deposit",
        "phase": "decision",
        "title": "确认接受期限并缴纳押金",
        "detail": "押金通常不可退，缴前务必确认。",
        "applies_to": "all",
        "sort_order": 3,
    },
    {
        "key": "dec-coe",
        "phase": "decision",
        "title": "换取 CoE",
        "detail": "缴费后学校出具 CoE，是办签证的前提。",
        "applies_to": "all",
        "sort_order": 4,
    },
    {
        "key": "dec-visa",
        "phase": "decision",
        "title": "准备签证与行前材料",
        "detail": "学生签证、体检、海外学生保险（OSHC）、住宿。",
        "applies_to": "all",
        "sort_order": 5,
    },
]

# Authored for the visa phase. Each cites the official page; nothing here is invented from memory.
VISA_MATERIALS = [
    {
        "key": "visa-gs-responses",
        "phase": "visa",
        "title": "GS 问卷逐题作答",
        "detail": "申请表中逐题作答，每题不超过 150 词，且必须使用英文。",
        "applies_to": "all",
        "sort_order": 0,
    },
    {
        "key": "visa-gs-evidence",
        "phase": "visa",
        "title": "GS 支持材料",
        "detail": "成绩单、雇主信息、税单或银行流水等，用于支撑陈述。",
        "applies_to": "all",
        "sort_order": 1,
    },
]


def seed_roadmap(session: Session) -> tuple[int, int]:
    """Insert missing phases and materials. Returns (phases added, materials added)."""
    phases_added = 0
    for row in PHASES:
        if session.get(RoadmapPhase, row["key"]) is None:
            session.add(RoadmapPhase(**row))
            phases_added += 1
    session.flush()

    source = session.execute(
        select(Source).where(Source.url == GS_SOURCE_URL)
    ).scalar_one_or_none()
    if source is None:
        source = Source(
            id="src-gs-requirement",
            url=GS_SOURCE_URL,
            title="Genuine Student requirement",
            publisher="Department of Home Affairs",
            domain="immi.homeaffairs.gov.au",
            status=SourceStatus.UNVERIFIED,
            verified_at=None,
        )
        session.add(source)
        session.flush()

    materials_added = 0
    for row in MATERIALS + VISA_MATERIALS:
        if session.get(MaterialTemplate, row["key"]) is not None:
            continue
        payload = dict(row)
        if payload["phase"] == "visa":
            payload["source_id"] = source.id
        session.add(MaterialTemplate(**payload))
        materials_added += 1

    session.commit()
    return phases_added, materials_added
