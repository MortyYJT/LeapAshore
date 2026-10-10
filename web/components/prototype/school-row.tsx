import Link from 'next/link';
import { institutionSlug, type OverseasInstitution } from '../../lib/prototype-library';
import { ConsultantButton } from './consultant-button';

export function SchoolRow({school, detail = false}: {school: OverseasInstitution; detail?: boolean}) {
  const name = school.name_zh || school.name_en || '未知';
  const href = `/prototype/schools/${encodeURIComponent(institutionSlug(school))}`;
  const names = <>{name}{school.name_zh_kind && <span className="ml-2 inline-block rounded bg-slate-100 px-2 py-0.5 align-middle text-xs font-normal text-slate-600">{school.name_zh_kind}</span>}</>;
  return <article className="relative flex min-w-0 flex-col gap-4 bg-white px-4 py-5 sm:flex-row sm:items-center sm:px-5">
    {!detail && <Link href={href} aria-label={`查看${name}`} className="absolute inset-0 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"/>}
    <div className="pointer-events-none flex min-w-0 flex-1 items-start gap-4">
      <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-xl font-bold text-emerald-800">{Array.from(name)[0]}</span>
      <div className="min-w-0 flex-1">
        {detail ? <h1 className="break-words text-2xl font-bold text-emerald-900 sm:text-3xl">{names}</h1> : <h2 className="break-words text-lg font-bold text-emerald-900">{names}</h2>}
        <p className="mt-1 break-words text-sm text-slate-600">{school.name_en || '未知'}</p>
        <p className="mt-2 break-words text-xs text-slate-500">{school.city || '未知'} · {school.country || '未知'}</p>
        {!!school.alliances?.length && <div className="mt-3 flex flex-wrap gap-2">{school.alliances.map(alliance => <a key={alliance.name} href={alliance.source} className="pointer-events-auto relative z-10 rounded-full border border-emerald-200 px-2.5 py-1 text-xs text-emerald-800 hover:bg-emerald-50 focus-visible:outline-2 focus-visible:outline-emerald-700">{alliance.name}</a>)}</div>}
      </div>
    </div>
    <div className="pointer-events-none flex flex-wrap items-center justify-between gap-3 sm:shrink-0 sm:flex-col sm:items-end">
      <p className="text-sm font-semibold text-slate-700">QS 排名：{school.qs_rank || '未进入前 300'}</p>
      <div className="pointer-events-auto"><ConsultantButton/></div>
    </div>
  </article>;
}
