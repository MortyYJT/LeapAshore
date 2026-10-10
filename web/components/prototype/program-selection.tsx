'use client';
import Link from 'next/link';
import { createContext, useContext, useEffect, useState } from 'react';
import { button } from './shared';
const Selection = createContext<{selected: string[]; toggle: (code: string) => void}>({selected:[],toggle:() => {}});
const key = 'offerpilot-prototype-comparison';
export function ProgramSelection({children}: {children: React.ReactNode; codes?: string[]}) {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => { try { const stored = JSON.parse(sessionStorage.getItem(key) || '[]'); if (Array.isArray(stored)) setSelected([...new Set(stored.filter((c): c is string => typeof c === 'string' && /^[a-z0-9]+$/i.test(c)))].slice(0,4)); } catch {} }, []);
  const save = (codes: string[]) => { setSelected(codes); try { sessionStorage.setItem(key,JSON.stringify(codes)); } catch {} };
  return <Selection.Provider value={{selected,toggle:code => save(selected.includes(code) ? selected.filter(c => c !== code) : selected.length < 4 ? [...selected,code] : selected)}}><div className="mb-5 flex flex-wrap items-center gap-4"><p className="text-sm">已选 {selected.length}/4 · 可跨页选择</p>{selected.length >= 2 && <Link className={button} href={`/prototype/compare?codes=${selected.join(',')}`}>开始对比</Link>}<button className="text-sm underline" onClick={() => save([])}>清空选择</button></div>{children}</Selection.Provider>;
}
export function ProgramCheckbox({code}: {code: string}) {
  const {selected,toggle} = useContext(Selection);
  return <label className="mt-4 flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.includes(code)} disabled={!selected.includes(code) && selected.length >= 4} onChange={() => toggle(code)}/>加入对比</label>;
}
