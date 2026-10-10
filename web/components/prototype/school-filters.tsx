'use client';

import Link from 'next/link';
import { useState } from 'react';
import { schoolListHref, schoolRegions, schoolQsRanges, type Query } from '../../lib/prototype-library';
import { button, input, secondary } from './shared';

const chip = 'inline-flex rounded-full border px-3 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700';
const selected = 'border-emerald-800 bg-emerald-800 text-white';
const idle = 'border-slate-200 bg-white text-slate-600 hover:border-emerald-700 hover:text-emerald-800';

export function SchoolFilters({query}: {query: Query}) {
  const [open, setOpen] = useState(false);
  const qs = query.qs?.split(',') || [];
  return <section aria-label="学校筛选" className="mb-6 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
    <button type="button" className={`${secondary} w-full justify-between md:hidden`} aria-expanded={open} aria-controls="school-filters" onClick={() => setOpen(!open)}>筛选 <span aria-hidden="true">{open ? '−' : '+'}</span></button>
    <div id="school-filters" className={`${open ? 'block' : 'hidden'} mt-4 space-y-5 md:mt-0 md:block`}>
      <form action="/prototype/schools" className="flex flex-wrap items-end gap-3">
        <label className="min-w-0 flex-1 basis-48 text-sm font-semibold">搜索学校<input key={query.q || ''} className={`${input} mt-2 font-normal`} type="search" name="q" defaultValue={query.q} placeholder="中文或英文名称"/></label>
        {query.region && <input type="hidden" name="region" value={query.region}/>}
        {qs.map(value => <input key={value} type="hidden" name="qs" value={value}/>)}
        <button className={button}>搜索</button><Link className={secondary} href="/prototype/schools">重置</Link>
      </form>
      <div><h2 className="mb-2 text-sm font-semibold">地区 <span className="text-xs font-normal text-slate-400">单选</span></h2><div className="flex flex-wrap gap-2">{['不限', ...schoolRegions].map(region => {
        const active = region === (query.region || '不限');
        return <Link key={region} aria-current={active ? 'true' : undefined} className={`${chip} ${active ? selected : idle}`} href={schoolListHref(query, {region: region === '不限' ? undefined : region})}>{region}</Link>;
      })}</div></div>
      <div><h2 className="mb-2 text-sm font-semibold">QS 排名 <span className="text-xs font-normal text-slate-400">多选</span></h2><div className="flex flex-wrap gap-2">{schoolQsRanges.map(([value, label]) => {
        const active = qs.includes(value);
        const next = active ? qs.filter(q => q !== value) : [...qs, value];
        return <Link key={value} aria-current={active ? 'true' : undefined} className={`${chip} ${active ? selected : idle}`} href={schoolListHref(query, {qs: next.join(',') || undefined})}>{label}{active && <span className="ml-1" aria-hidden="true">✓</span>}</Link>;
      })}</div></div>
    </div>
  </section>;
}
