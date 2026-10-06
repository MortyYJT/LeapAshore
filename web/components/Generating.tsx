"use client";

import { useEffect, useState } from "react";

const STEPS = [
  "背景已获取",
  "正在归一化成绩口径",
  "正在比对已核验的项目门槛",
  "正在生成申请组合建议",
];

export default function Generating({ onDone }: { onDone: () => void }) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (idx >= STEPS.length) {
      const t = setTimeout(onDone, 400);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setIdx((i) => i + 1), 620);
    return () => clearTimeout(t);
  }, [idx, onDone]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center text-5xl">🧭</div>
        <ul className="grid gap-4">
          {STEPS.map((s, i) => (
            <li
              key={s}
              className="flex items-center gap-3 text-base font-semibold transition-opacity"
              style={{ opacity: i <= idx ? 1 : 0.25 }}
            >
              <span
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm text-white"
                style={{
                  background: i < idx ? "var(--color-brand)" : i === idx ? "var(--color-warn)" : "var(--color-line)",
                }}
              >
                {i < idx ? "✓" : i === idx ? "•" : ""}
              </span>
              {s}
            </li>
          ))}
        </ul>
        <div className="progress-track mt-10">
          <div
            className="progress-fill"
            style={{ width: `${Math.min(100, (idx / STEPS.length) * 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
