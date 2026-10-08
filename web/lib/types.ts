// OfferPilot domain model, front-end MVP version.
// Mirrors the Pydantic models the FastAPI service will expose, so it can be swapped for API responses.

export type EducationLevel = "高中" | "本科" | "硕士" | "其他";

export type SchoolOrigin = "国内" | "海外";

/** Domestic tier. 985 and 211 are detected automatically; the rest are self-reported. */
export type DomesticTier = "985" | "211" | "双非" | "专科";

/** Overseas institutions are self-reported by QS band; rankings change every year. */
export type OverseasBand =
  | "QS 1-50"
  | "QS 51-100"
  | "QS 101-200"
  | "QS 201-500"
  | "QS 500+"
  | "不确定";

export type DegreeLevel = "本科" | "授课型硕士" | "研究型硕士" | "博士";

export type StudyArea =
  | "计算机与数据"
  | "商科与金融"
  | "工程"
  | "教育与社会科学"
  | "生命科学"
  | "医学与健康"
  | "法律与犯罪学"
  | "自然科学与数学"
  | "人文与语言"
  | "建筑规划与设计"
  | "传媒艺术与音乐"
  | "环境与农业";

/** Application profile: the object the whole product revolves around. */
export interface Profile {
  educationLevel: EducationLevel | null;
  schoolOrigin: SchoolOrigin | null;
  /** Raw school name as typed. May be empty when the user prefers not to disclose it. */
  schoolName: string;
  /** Detected or self-reported tier. */
  domesticTier: DomesticTier | null;
  overseasBand: OverseasBand | null;
  major: string;
  /** Undergraduate average and its scale, normalised to a percentage. */
  gpaScore: number | null;
  gpaScale: number | null;
  targetDegree: DegreeLevel | null;
  targetField: StudyArea | null;
  englishScore: string;
  annualBudgetCny: number | null;
  intake: string;
}

export type SourceStatus = "已核验" | "待核验";

/** Official source citation. The excerpt is a manual summary, not captured page text. */
export interface SourceCitation {
  id: string;
  title: string;
  url: string;
  excerpt: string;
  verifiedAt: string | null;
  status: SourceStatus;
}

/** An admission program. */
export interface Program {
  slug: string;
  university: string;
  /**
   * The English program name, which is what the product shows.
   *
   * The served catalogue names it `nameEn` and calls its own `name` the Chinese one; the adapter in
   * `programs-source.ts` makes that mapping, and `note/superpowers/specs/2026-10-06-stage-2-m2-design.md`
   * §3.6 is the ruling. `null` on the wire means the catalogue has no English name yet, and the render
   * sites show `UNKNOWN` rather than an empty string.
   */
  name: string | null;
  /**
   * The five fields the served catalogue can leave unknown.
   *
   * `null` is "this catalogue does not know yet" and it is not the same claim as `""`, which says the
   * program has none of this. `api/app/schemas/program.py` keeps the nullability visible on the wire
   * for that reason, and the render sites show `UNKNOWN`; nothing may substitute an empty string.
   */
  city: string | null;
  degreeLevel: string | null;
  field: string | null;
  duration: string | null;
  /** Grade baseline as a percentage. Provenance and verification status live in source. */
  minimumMark: number | null;
  /** Separate baseline for Chinese non-211 institutions, only when an official page states one. */
  non211MinimumMark: number | null;
  requiresCognate: boolean;
  prerequisites: string[];
  englishRequirement: string | null;
  source: SourceCitation;
  /** Overall data confidence. Every record is pending verification during the MVP stage. */
  dataStatus: SourceStatus;
}

export type PortfolioTier = "冲" | "稳" | "保";

export interface PortfolioItem {
  programSlug: string;
  tier: PortfolioTier;
  /** Whether the user confirmed this program into the application portfolio. */
  confirmed: boolean;
  /** True when the user added a program the system could not tier automatically. */
  needsReview?: boolean;
  /**
   * Whether this row is the applicant's first choice.
   *
   * A fact the server enforces rather than a display detail: `applications` carries the partial unique
   * index `uq_applications_one_primary_per_client`, and a whole replacement restates the flag, so a
   * payload that omitted it would read as `False` and silently release a first choice the applicant
   * already had. It is carried through the round trip for that reason, not because a screen shows it
   * today.
   */
  isPrimary?: boolean;
}

export type PhaseId =
  | "selection"
  | "academic"
  | "language"
  | "specialized"
  | "submission"
  | "decision";

export type PhaseStatus = "pending" | "in_progress" | "completed" | "overdue";

/** A preparation item, shown when a roadmap node is opened. */
export interface MaterialItem {
  id: string;
  label: string;
  detail: string;
  /** Applicability filter by degree level and study area. */
  appliesTo?: "research" | "portfolio" | "all";
}

export interface PhaseTask {
  materialId: string;
  label: string;
  detail: string;
  done: boolean;
  /** official = confirmed deadline with a source; suggested = derived system suggestion. */
  scheduleOrigin: "suggested" | "official" | "user";
  dueAt: string | null;
  deadlineSourceUrl: string | null;
}

export interface RoadmapPhase {
  /**
   * The served phase key. A plain string, not `PhaseId`: the definition comes from the server, so the
   * set of phases is the server's to change, and a phase it adds must render rather than be rejected
   * by a union that was written before it existed.
   */
  id: string;
  title: string;
  detail: string;
  /** Suggested start date, derived backwards from the intake term. */
  suggestedAt: string;
  status: PhaseStatus;
  tasks: PhaseTask[];
}

export interface Roadmap {
  intake: string;
  anchorAt: string;
  generatedAt: string;
  phases: RoadmapPhase[];
}

/**
 * The phase and material definitions the roadmap is built from, without any dates.
 *
 * This is what `GET /api/roadmap` describes and what `buildRoadmap` takes: the server owns which
 * phases exist and what each one asks for, while the date arithmetic stays on the client by design.
 * The shape is deliberately loose — neither the phase id nor the material grouping is keyed by
 * `PhaseId` — because the server owns the list and may name a phase this build has never heard of,
 * such as the authored `visa` phase the constants here do not carry. A phase it adds has to render
 * rather than be rejected by a union written before it existed. The constants satisfy this shape
 * because a `PhaseId` is a string and their material record is one entry per phase.
 */
export interface RoadmapDefinition {
  phases: {
    id: string;
    title: string;
    detail: string;
    /** Days before the intake date, counted backwards. */
    offsetDays: number;
  }[];
  materials: Record<string, MaterialItem[]>;
}

export type AppStage = "onboarding" | "generating" | "portfolio" | "app";
