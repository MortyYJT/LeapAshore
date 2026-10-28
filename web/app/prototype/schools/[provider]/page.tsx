import { notFound } from 'next/navigation';
import { overseasInstitutions, masterPrograms, schoolForProvider } from '../../../../lib/prototype-library-server';
import { institutionSlug, paginate, singleQuery } from '../../../../lib/prototype-library';
import { Attribution } from '../../../../components/prototype/shared';
import { MasterCard, Pagination } from '../../../../components/prototype/library';
import { SchoolRow } from '../../../../components/prototype/school-row';
export default async function Page({ params, searchParams }: { params: Promise<{provider: string}>; searchParams: Promise<Record<string,string|string[]|undefined>> }) {
  const {provider} = await params;
  const school = overseasInstitutions.find(s => institutionSlug(s) === provider) || schoolForProvider(provider);
  if (!school) notFound();
  const query = singleQuery(await searchParams);
  const result = paginate(school.country === 'Australia' ? masterPrograms.filter(p => school.cricos_codes?.includes(p.provider)) : [],query.page);
  return <><div className="mb-6 overflow-hidden rounded-2xl border border-slate-200"><SchoolRow school={school} detail/><div className="bg-white px-5 pb-5 text-sm text-slate-600"><p>入选依据：{school.selection_basis.join('；') || '未知'}</p>{school.country === 'Australia' && <Attribution/>}</div></div><section className="mb-6 rounded-2xl bg-white p-5"><p className="text-sm">资料来源：{school.sources.length ? school.sources.map((url,i) => <a className="mr-4 text-emerald-800 underline" key={url} href={url}>来源 {i+1}</a>) : '未知（待采集）'}</p><p className="mt-3 text-sm">官网：{school.website ? <a className="break-all text-emerald-800 underline" href={/^https?:\/\//.test(school.website) ? school.website : `https://${school.website}`}>{school.website}</a> : '未知'}</p></section>{school.country === 'Australia' ? <><h2 className="text-lg font-bold">CRICOS 授课型硕士</h2><Pagination {...result} query={query} path={`/prototype/schools/${encodeURIComponent(institutionSlug(school))}`}/><div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{result.items.map(p => <MasterCard key={p.code} program={p}/>)}</div>{!result.total && <p>项目资料未知（待采集）。</p>}<Pagination {...result} query={query} path={`/prototype/schools/${encodeURIComponent(institutionSlug(school))}`}/></> : <p>项目资料未知（待采集）。</p>}</>;
}
