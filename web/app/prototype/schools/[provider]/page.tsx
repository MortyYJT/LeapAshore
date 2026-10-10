import { notFound } from 'next/navigation';
import { overseasInstitutions, masterPrograms, schoolForProvider } from '../../../../lib/prototype-library-server';
import { institutionSlug, paginate, singleQuery } from '../../../../lib/prototype-library';
import { Heading, Attribution } from '../../../../components/prototype/shared';
import { MasterCard, Pagination } from '../../../../components/prototype/library';
export default async function Page({ params, searchParams }: { params: Promise<{provider: string}>; searchParams: Promise<Record<string,string|string[]|undefined>> }) {
  const {provider} = await params;
  const school = overseasInstitutions.find(s => institutionSlug(s) === provider) || schoolForProvider(provider);
  if (!school) notFound();
  const query = singleQuery(await searchParams);
  const result = paginate(school.country === 'Australia' ? masterPrograms.filter(p => school.cricos_codes?.includes(p.provider)) : [],query.page);
  return <><Heading title={school.name_zh || school.name_en || '未知'}>{school.name_zh && <p>{school.name_en || '未知'}{school.name_zh_kind && <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">中文名：{school.name_zh_kind}</span>}</p>}<p>{school.country || '未知'} · {school.city || '未知'}</p><p>入选依据：{school.selection_basis.join('；') || '未知'}</p>{school.country === 'Australia' && <Attribution/>}</Heading><section className="mb-6 rounded-2xl bg-white p-5"><p className="text-sm">资料来源：{school.sources.length ? school.sources.map((url,i) => <a className="mr-4 text-emerald-800 underline" key={url} href={url}>来源 {i+1}</a>) : '未知（待采集）'}</p><p className="mt-3 text-sm">官网：{school.website ? <a className="text-emerald-800 underline" href={/^https?:\/\//.test(school.website) ? school.website : `https://${school.website}`}>{school.website}</a> : '未知'}</p></section>{school.country === 'Australia' ? <><h2 className="text-lg font-bold">CRICOS 授课型硕士</h2><Pagination {...result} query={query} path={`/prototype/schools/${encodeURIComponent(institutionSlug(school))}`}/><div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">{result.items.map(p => <MasterCard key={p.code} program={p}/>)}</div>{!result.total && <p>项目资料未知（待采集）。</p>}<Pagination {...result} query={query} path={`/prototype/schools/${encodeURIComponent(institutionSlug(school))}`}/></> : <p>项目资料未知（待采集）。</p>}</>;
}
