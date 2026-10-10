import { overseasInstitutions } from '../../../lib/prototype-library-server';
import { filterSchools, paginate, singleQuery } from '../../../lib/prototype-library';
import { SchoolCard, Pagination, FilterSelect } from '../../../components/prototype/library';
import { Heading, input, button, secondary } from '../../../components/prototype/shared';
import Link from 'next/link';
export default async function Page({searchParams}: {searchParams: Promise<Record<string,string|string[]|undefined>>}) {
  const query = singleQuery(await searchParams);
  const result = paginate(filterSchools(overseasInstitutions, query), query.page);
  return <><Heading title="学校库">收录 {overseasInstitutions.length} 所院校。入选依据仅说明收录范围。</Heading><form className="grid gap-4 rounded-2xl bg-white p-5 sm:grid-cols-2" action="/prototype/schools"><label className="text-sm">搜索学校<input className={`${input} mt-2`} name="q" defaultValue={query.q} placeholder="中文或英文名称"/></label><FilterSelect name="country" label="国家 / 地区" value={query.country} options={[...new Set(overseasInstitutions.map(s => s.country))].sort().map(c => [c,c])}/><button className={button}>筛选</button><Link className={secondary} href="/prototype/schools">重置</Link></form><Pagination {...result} query={query} path="/prototype/schools"/><div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{result.items.map(s => <SchoolCard key={s.name_en || s.name_zh} school={s}/>)}</div>{!result.total && <p>没有符合条件的学校。</p>}<Pagination {...result} query={query} path="/prototype/schools"/></>;
}
