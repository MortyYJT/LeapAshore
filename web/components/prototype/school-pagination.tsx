import Link from 'next/link';
import { schoolListHref, type Query } from '../../lib/prototype-library';
import { secondary } from './shared';

export function SchoolPagination({page, pages, query}: {page: number; pages: number; query: Query}) {
  const href = (n: number) => schoolListHref(query, {page: String(n)});
  return <nav aria-label="学校分页" className="my-6 flex flex-wrap items-center gap-2">
    <Link href={href(1)} className={secondary}>首页</Link>
    {page > 1 && <Link href={href(page - 1)} className={secondary}>上一页</Link>}
    {Array.from({length: pages}, (_, i) => i + 1).map(n => <Link key={n} href={href(n)} aria-label={`第 ${n} 页`} aria-current={n === page ? 'page' : undefined} className={`flex h-9 min-w-9 items-center justify-center rounded-lg border px-2 text-sm ${n === page ? 'border-emerald-800 bg-emerald-800 text-white' : 'border-slate-200 bg-white hover:bg-slate-100'}`}>{n}</Link>)}
    {page < pages && <Link href={href(page + 1)} className={secondary}>下一页</Link>}
    <Link href={href(pages)} className={secondary}>末页</Link>
    <form action="/prototype/schools" className="flex flex-wrap items-center gap-2 text-sm">
      {query.q && <input type="hidden" name="q" value={query.q}/>}
      {query.region && <input type="hidden" name="region" value={query.region}/>}
      {query.qs?.split(',').map(qs => <input key={qs} type="hidden" name="qs" value={qs}/>)}
      <label>跳至 <input aria-label="页码" className="w-16 rounded-lg border border-slate-300 bg-white p-2" type="number" name="page" min="1" max={pages} defaultValue={page} key={page}/></label>
      <button className={secondary}>前往</button>
      <span className="text-xs text-slate-500">第 {page} / {pages} 页</span>
    </form>
  </nav>;
}
