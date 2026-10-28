import Link from 'next/link';
import { notFound } from 'next/navigation';
import { masterPrograms, sampleRequirements, schoolHref } from '../../../../lib/prototype-library-server';
import { Attribution, Heading, RequirementRows, Sample, button } from '../../../../components/prototype/shared';
import ChineseRules from '../../../../components/prototype/chinese-rules';
export default async function Page({params}: {params: Promise<{code: string}>}) {
  const {code} = await params; const p = masterPrograms.find(p => p.code === code); if (!p) notFound();
  const rules = sampleRequirements(code);
  return <><Heading title={p.name || '未知'}><Link className="text-emerald-800 underline" href={schoolHref(p.provider)}>{p.institution || '未知'}</Link></Heading><section className="rounded-2xl border border-slate-200 bg-white p-6"><h2 className="mb-4 text-lg font-bold">项目基本信息</h2><dl className="grid gap-5 sm:grid-cols-2">{[['CRICOS 编码',code],['课程层级','Masters Degree (Coursework)'],['学科',p.field || '未知'],['细分领域',p.narrow || '未知'],['学制',p.weeks === null ? '未知' : `${p.weeks} 周`],['CRICOS 登记总学费',p.tuition ? `${p.tuition} 澳元` : '未知'],['CRICOS 登记总费用',p.total_cost ? `${p.total_cost} 澳元` : '未知']].map(([k,v]) => <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="mt-2 text-sm font-semibold">{v}</dd></div>)}</dl><Attribution/></section><section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6"><h2 className="text-lg font-bold">录取要求 {rules && <Sample/>}</h2>{rules ? <><p className="mt-2 text-xs text-slate-500">下列门槛、引文和核验档位均为示例；均分先展示 985 门槛。</p><RequirementRows requirements={rules}/></> : <dl className="mt-4 space-y-3">{['本科加权均分','雅思总分','本科专业领域'].map(label => <div key={label}><dt>{label}</dt><dd>未知（待采集）</dd></div>)}</dl>}</section>{rules ? <><ChineseRules/><Link className={`${button} mt-6`} href={`/prototype/assess?code=${code}`}>测我能不能申 →</Link></> : <p className="mt-6 text-sm">此项目缺少录取要求，不参与测评分档。</p>}</>;
}
