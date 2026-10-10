import Link from 'next/link';
import { Attribution, input, secondary } from './shared';
import { institutionSlug, type OverseasInstitution, type MasterProgram, type Query } from '../../lib/prototype-library';
import { schoolHref } from '../../lib/prototype-library-server';
export function Pagination({ page, pages, total, query, path }: {page: number; pages: number; total: number; query: Query; path: string}) {
  const href = (n: number) => { const params = new URLSearchParams(); for (const [key,value] of Object.entries(query)) if (value) params.set(key,value); params.set('page',String(n)); return `${path}?${params}`; };
  return <nav aria-label="分页" className="my-6 flex flex-wrap items-center gap-4"><p className="text-sm">共 {total} 条 · 第 {page} / {pages} 页</p>{page > 1 && <Link className={secondary} href={href(page-1)}>上一页</Link>}{page < pages && <Link className={secondary} href={href(page+1)}>下一页</Link>}<form action={path} className="flex items-center gap-2">{Object.entries(query).filter(([k,v]) => k !== 'page' && v).map(([k,v]) => <input key={k} type="hidden" name={k} value={v}/>)}<label className="text-sm">跳至 <input className="w-20 rounded border p-2" aria-label="页码" name="page" type="number" min="1" max={pages} defaultValue={page}/></label><button className={secondary}>前往</button></form></nav>;
}
export function SchoolCard({school}: {school: OverseasInstitution}) {
  return <article className="rounded-2xl border border-slate-200 bg-white p-5"><Link className="text-lg font-bold text-emerald-900" href={`/prototype/schools/${encodeURIComponent(institutionSlug(school))}`}>{school.name_zh || school.name_en || '未知'}</Link>{school.name_zh && <p className="mt-1 text-sm">{school.name_en || '未知'}</p>}<p className="mt-3 text-sm">{school.country || '未知'} · {school.city || '未知'}</p><p className="mt-3 text-xs leading-6 text-slate-500">入选依据：{school.selection_basis.join('；') || '未知'}</p>{school.country === 'Australia' && <Attribution/>}</article>;
}
export function MasterCard({program, children}: {program: MasterProgram; children?: React.ReactNode}) {
  return <article className="rounded-2xl border border-slate-200 bg-white p-5"><Link className="text-xs text-emerald-800 underline" href={schoolHref(program.provider)}>{program.institution || '未知'}</Link><h2 className="my-3 text-lg font-bold"><Link href={`/prototype/programs/${program.code}`}>{program.name || '未知'}</Link></h2><p className="text-xs">CRICOS {program.code}</p><p className="my-3 text-sm">{program.field || '未知'}</p><p className="text-sm">学制：{program.weeks ?? '未知'}{program.weeks !== null && ' 周'}</p><p className="mt-2 text-sm">CRICOS 登记总学费：{program.tuition || '未知'} 澳元</p><Attribution/>{children}</article>;
}
export function FilterSelect({name, label, value, options}: {name: string; label: string; value?: string; options: [string,string][]}) {
  return <label className="text-sm">{label}<select name={name} defaultValue={value || ''} className={`${input} mt-2`}><option value="">全部</option>{options.map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>;
}
