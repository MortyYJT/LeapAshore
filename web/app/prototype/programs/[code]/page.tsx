import Link from 'next/link';
import { notFound } from 'next/navigation';
import { courses, requirements } from '../../../../prototype-fixtures/data';
import { Attribution, Heading, RequirementRows, Sample, button } from '../../../../components/prototype/shared';
import ChineseRules from '../../../../components/prototype/chinese-rules';
export default async function Page({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params; const c = courses.find(c => c['CRICOS Course Code'] === code); if (!c) notFound();
  return <><Heading title={c['Course Name']}><Link className="text-emerald-800 underline" href={`/prototype/schools/${c['CRICOS Provider Code']}`}>{c['Institution Name']}</Link></Heading><section className="rounded-2xl border border-slate-200 bg-white p-6"><h2 className="mb-4 text-lg font-bold">项目基本信息</h2><dl className="grid gap-5 sm:grid-cols-2">{[['CRICOS 编码', code], ['课程层级', c['Course Level']], ['学科', c['Field of Education 1 Broad Field']], ['细分领域', c['Field of Education 1 Narrow Field']], ['学制', `${c['Duration (Weeks)']} 周`], ['CRICOS 登记总学费', `${c['Tuition Fee']} 澳元`]].map(([k,v]) => <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="mt-2 text-sm font-semibold">{v}</dd></div>)}</dl><Attribution/></section><section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6"><h2 className="text-lg font-bold">录取要求 <Sample/></h2><p className="mt-2 text-xs text-slate-500">下列门槛、引文和核验档位均为示例；均分先展示 985 门槛。</p><RequirementRows requirements={requirements(c)}/></section><ChineseRules/><Link className={`${button} mt-6`} href={`/prototype/assess?code=${code}`}>测我能不能申 →</Link></>;
}
