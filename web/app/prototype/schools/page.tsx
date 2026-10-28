import { overseasInstitutions } from '../../../lib/prototype-library-server';
import { filterSchools, sortSchools, paginateSchools, schoolQuery } from '../../../lib/prototype-library';
import { SchoolRow } from '../../../components/prototype/school-row';
import { SchoolFilters } from '../../../components/prototype/school-filters';
import { SchoolPagination } from '../../../components/prototype/school-pagination';
import { Heading } from '../../../components/prototype/shared';

export default async function Page({searchParams}: {searchParams: Promise<Record<string, string | string[] | undefined>>}) {
  const query = schoolQuery(await searchParams);
  const result = paginateSchools(sortSchools(filterSchools(overseasInstitutions, query)), query.page);
  return <>
    <Heading title="学校库">收录 {overseasInstitutions.length} 所院校。按地区和 QS 排名筛选，找到想了解的学校。</Heading>
    <SchoolFilters query={query}/>
    <p role="status" className="mb-4 text-sm text-slate-600">共找到 <strong className="text-emerald-900">{result.total}</strong> 个学校符合条件</p>
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white divide-y divide-slate-200">
      {result.items.map(s => <SchoolRow key={s.name_en || s.name_zh} school={s}/>)}
      {!result.total && <p className="p-6 text-sm text-slate-500">没有符合条件的学校，请调整筛选条件。</p>}
    </div>
    <SchoolPagination page={result.page} pages={result.pages} query={query}/>
    <p className="text-xs leading-6 text-slate-500">QS 排名来源：<a href="https://www.topuniversities.com/world-university-rankings" className="text-emerald-800 underline">QS World University Rankings 2027</a>（2026-06-18 发布）。</p><p className="text-xs leading-6 text-slate-500">校徽图标取自各校官网，归各校所有，仅用于识别学校，不代表与任何学校存在合作关系。</p>
  </>;
}
