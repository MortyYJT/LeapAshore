'use client';

import { createContext, useContext } from 'react';
import { button } from './shared';

export const ConsultantContext = createContext<(() => void) | null>(null);

export function ConsultantButton() {
  const open = useContext(ConsultantContext);
  return <button type="button" className={`${button} relative z-10 shrink-0`} aria-controls="consultant-panel" onClick={open ?? undefined}>在线咨询</button>;
}
