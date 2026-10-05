// Domestic institution tier detection.
// Source: the public Ministry of Education lists, 39 Project 985 and 116 Project 211 institutions.
// QS rankings change every year, so overseas institutions are self-reported rather than inferred.

import type { DomesticTier } from "./types";

export const C985: string[] = [
  "清华大学", "北京大学", "中国人民大学", "北京航空航天大学", "北京理工大学",
  "中国农业大学", "北京师范大学", "中央民族大学", "南开大学", "天津大学",
  "大连理工大学", "东北大学", "吉林大学", "哈尔滨工业大学", "复旦大学",
  "同济大学", "上海交通大学", "华东师范大学", "南京大学", "东南大学",
  "浙江大学", "中国科学技术大学", "厦门大学", "山东大学", "中国海洋大学",
  "武汉大学", "华中科技大学", "湖南大学", "中南大学", "中山大学",
  "华南理工大学", "四川大学", "电子科技大学", "重庆大学", "西安交通大学",
  "西北工业大学", "西北农林科技大学", "兰州大学", "国防科技大学",
];

/** Project 211 institutions that are not also Project 985. */
export const C211_ONLY: string[] = [
  "北京交通大学", "北京工业大学", "北京科技大学", "北京化工大学", "北京邮电大学",
  "北京林业大学", "北京中医药大学", "北京外国语大学", "中国传媒大学", "中央财经大学",
  "对外经济贸易大学", "北京体育大学", "中央音乐学院", "中国政法大学", "华北电力大学",
  "中国矿业大学(北京)", "中国石油大学(北京)", "中国地质大学(北京)",
  "天津医科大学", "河北工业大学", "太原理工大学", "内蒙古大学",
  "辽宁大学", "大连海事大学", "东北师范大学", "延边大学",
  "哈尔滨工程大学", "东北农业大学", "东北林业大学",
  "华东理工大学", "东华大学", "上海外国语大学", "上海财经大学", "上海大学", "第二军医大学",
  "苏州大学", "南京航空航天大学", "南京理工大学", "中国矿业大学", "河海大学",
  "江南大学", "南京农业大学", "中国药科大学", "南京师范大学",
  "安徽大学", "合肥工业大学", "福州大学", "南昌大学",
  "中国石油大学(华东)", "郑州大学",
  "中国地质大学(武汉)", "武汉理工大学", "华中农业大学", "华中师范大学", "中南财经政法大学",
  "湖南师范大学", "暨南大学", "华南师范大学", "广西大学", "海南大学", "西南大学",
  "西南交通大学", "四川农业大学", "西南财经大学", "贵州大学", "云南大学", "西藏大学",
  "西北大学", "西安电子科技大学", "长安大学", "陕西师范大学",
  "青海大学", "宁夏大学", "新疆大学", "石河子大学", "第四军医大学",
];

/** Common abbreviations mapped to full names. Matches still validate against the full list. */
const ALIASES: Record<string, string> = {
  北大: "北京大学", 清华: "清华大学", 人大: "中国人民大学",
  北航: "北京航空航天大学", 北理: "北京理工大学", 北师大: "北京师范大学",
  中国农大: "中国农业大学", 民大: "中央民族大学",
  南开: "南开大学", 天大: "天津大学", 大工: "大连理工大学", 东大: "东北大学",
  吉大: "吉林大学", 哈工大: "哈尔滨工业大学",
  复旦: "复旦大学", 同济: "同济大学", 上交: "上海交通大学", 上海交大: "上海交通大学",
  华东师大: "华东师范大学", 华师: "华东师范大学",
  南大: "南京大学", 东南: "东南大学", 浙大: "浙江大学", 中科大: "中国科学技术大学",
  厦大: "厦门大学", 山大: "山东大学", 海大: "中国海洋大学",
  武大: "武汉大学", 华科: "华中科技大学", 湖大: "湖南大学", 中南: "中南大学",
  中大: "中山大学", 华南理工: "华南理工大学", 川大: "四川大学",
  电子科大: "电子科技大学", 重大: "重庆大学", 西交: "西安交通大学",
  西工大: "西北工业大学", 西农: "西北农林科技大学", 兰大: "兰州大学", 国防科大: "国防科技大学",
  北交: "北京交通大学", 北工大: "北京工业大学", 北科: "北京科技大学",
  北邮: "北京邮电大学", 北化: "北京化工大学", 北林: "北京林业大学",
  中传: "中国传媒大学", 央财: "中央财经大学", 对外经贸: "对外经济贸易大学",
  北外: "北京外国语大学", 法大: "中国政法大学", 华电: "华北电力大学",
  天医: "天津医科大学", 河工大: "河北工业大学", 太理: "太原理工大学", 内大: "内蒙古大学",
  辽大: "辽宁大学", 大连海事: "大连海事大学", 东北师大: "东北师范大学", 延大: "延边大学",
  哈工程: "哈尔滨工程大学", 东北农大: "东北农业大学", 东北林大: "东北林业大学",
  华东理工: "华东理工大学", 东华: "东华大学", 上外: "上海外国语大学",
  上财: "上海财经大学", 上大: "上海大学",
  苏大: "苏州大学", 南航: "南京航空航天大学", 南理工: "南京理工大学",
  河海: "河海大学", 江南: "江南大学", 南农: "南京农业大学",
  南师大: "南京师范大学", 安大: "安徽大学", 合工大: "合肥工业大学",
  福大: "福州大学", 昌大: "南昌大学", 郑大: "郑州大学",
  武理工: "武汉理工大学", 华农: "华中农业大学", 华中师大: "华中师范大学",
  中南财大: "中南财经政法大学", 湖南师大: "湖南师范大学", 暨大: "暨南大学",
  华南师大: "华南师范大学", 西大: "广西大学", 云大: "云南大学",
  西电: "西安电子科技大学", 长大: "长安大学", 陕西师大: "陕西师范大学",
  新疆大学: "新疆大学",
};

/** Normalise a name: strip whitespace and the trailing university or college suffix. */
function normalize(name: string): string {
  return name
    .trim()
    .replace(/\s+/g, "")
    .replace(/[（(].*?[)）]/g, "")
    .replace(/(大学|学院|大學)$/, "");
}

export interface SchoolMatch {
  /** Full name that was matched. */
  name: string;
  tier: DomesticTier;
  /** Whether the match came from an abbreviation or the full name. */
  matchedBy: "exact" | "alias";
}

function lookup(query: string): SchoolMatch | null {
  const q = normalize(query);
  if (q.length < 2) return null;

  const all = [...C985, ...C211_ONLY];
  const exact = all.find((s) => normalize(s) === q);
  if (exact) {
    return { name: exact, tier: C985.includes(exact) ? "985" : "211", matchedBy: "exact" };
  }

  const aliasFull = ALIASES[query.trim()];
  if (aliasFull) {
    return {
      name: aliasFull,
      tier: C985.includes(aliasFull) ? "985" : "211",
      matchedBy: "alias",
    };
  }

  // Fallback for partial input, for example a school name with a college suffix attached.
  const contained = all.find((s) => normalize(s).includes(q) || q.includes(normalize(s)));
  if (contained) {
    return {
      name: contained,
      tier: C985.includes(contained) ? "985" : "211",
      matchedBy: "exact",
    };
  }
  return null;
}

/** Detect a domestic institution tier. Returns null so the interface can ask the user instead. */
export function recognizeDomesticSchool(input: string): SchoolMatch | null {
  return lookup(input);
}

export const DOMESTIC_TIER_OPTIONS: { value: DomesticTier; label: string; hint: string }[] = [
  { value: "985", label: "985 工程", hint: "共 39 所，认可度最高" },
  { value: "211", label: "211 工程（非 985）", hint: "共 116 所（含 985）" },
  { value: "双一流", label: "双一流（非 211）", hint: "第二轮名单新增院校" },
  { value: "一本", label: "普通一本", hint: "非 985/211 的公办本科一批" },
  { value: "二本", label: "普通二本", hint: "" },
  { value: "专科", label: "专科 / 高职", hint: "" },
  { value: "其他", label: "其他 / 不便透露", hint: "不影响继续使用" },
];

export const OVERSEAS_BAND_OPTIONS: { value: string; label: string }[] = [
  { value: "QS 1-50", label: "QS 前 50" },
  { value: "QS 51-100", label: "QS 51–100" },
  { value: "QS 101-200", label: "QS 101–200" },
  { value: "QS 201-500", label: "QS 201–500" },
  { value: "QS 500+", label: "QS 500 之后" },
  { value: "不确定", label: "不确定 / 不便透露" },
];
