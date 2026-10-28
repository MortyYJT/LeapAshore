import Link from 'next/link';
import { masterPrograms } from '../../../lib/prototype-library-server';
import { filterPrograms, paginate, singleQuery } from '../../../lib/prototype-library';
import { MasterCard, Pagination, FilterSelect } from '../../../components/prototype/library';
import { Heading, Attribution, input, button, secondary } from '../../../components/prototype/shared';
import { ProgramSelection, ProgramCheckbox } from '../../../components/prototype/program-selection';
export default async function Page({searchParams}: {searchParams: Promise<Record<string,string|string[]|undefined>>}) {
  const query = singleQuery(await searchParams);
  const result = paginate(filterPrograms(masterPrograms, query), query.page);
  const schools = [...new Map(masterPrograms.map(p => [p.provider,p.institution])).entries()].sort((a,b) => a[1].localeCompare(b[1]));
  return <><Heading title="找到适合你的项目">全部 {masterPrograms.length} 个澳大利亚授课型硕士。九个项目保留示例要求，其余要求未知（待采集）。</Heading><form action="/prototype/programs" className="grid gap-4 rounded-2xl bg-white p-5 sm:grid-cols-2 lg:grid-cols-3"><FilterSelect name="school" label="学校" value={query.school} options={schools}/><FilterSelect name="field" label="学科" value={query.field} options={[...new Set(masterPrograms.map(p => p.field))].sort().map(f => [f,f])}/><FilterSelect name="duration" label="学制" value={query.duration} options={[...new Set(masterPrograms.map(p => p.weeks).filter((w): w is number => w !== null))].sort((a,b) => a-b).map(w => [String(w),`${w} 周`])}/>{[['min','总学费下限（澳元）'],['max','总学费上限（澳元）']].map(([name,label]) => <label key={name} className="text-sm">{label}<input className={`${input} mt-2`} type="number" min="0" name={name} defaultValue={query[name]}/></label>)}<div className="flex items-end gap-3"><button className={button}>筛选</button><Link className={secondary} href="/prototype/programs">重置</Link></div><Attribution/></form><Pagination {...result} query={query} path="/prototype/programs"/><ProgramSelection codes={result.items.map(p => p.code)}><div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{result.items.map(p => <MasterCard key={p.code} program={p}><ProgramCheckbox code={p.code}/></MasterCard>)}</div></ProgramSelection>{!result.total && <p>没有符合筛选条件的项目。</p>}<Pagination {...result} query={query} path="/prototype/programs"/></>;
}
