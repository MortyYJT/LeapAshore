"use client";

import { useState } from "react";

const VERSION = "0.1.0";

const SECTIONS = [
  {
    key: "data",
    title: "数据说明",
    body: [
      "项目数据目前是用于产品演示的占位数据，还没有接入数据库，也还没有完成数据标注。请只把它当作结构示例。",
      "所有时间都是按入学日期倒推的「系统建议」，不是官方截止日期。官方日期字段留空。",
      "系统判不出档位时会显示「需要人工核验」，不会替你猜一个基线。",
      "正式版本会接入经过标注核验的数据，并以学校官网为准。",
    ],
  },
  {
    key: "privacy",
    title: "隐私政策",
    body: [
      "收集的内容：院校、均分、专业、语言成绩、预算、目标方向、入学时间，以及你在流程里勾选的材料。不包含姓名、邮箱、手机号等可以直接识别你身份的字段。",
      "存放位置：申请档案保存在服务器上，靠这台设备上的匿名标识认领；申请组合、已勾选的材料和流程进度还保存在这台设备的浏览器里。现在还没有导出与删除接口，接入后会提供。",
      "头像：如果你上传了头像，图片会在你的浏览器里先压缩到 256×256 再存到本机，不会上传。",
      "第三方：目前没有接入任何分析、广告或模型服务。「留学顾问」还没有接入模型。",
      "你的控制权：可以在下面一键清除本机保存的内容；服务器上的档案不会随之删除。",
    ],
  },
  {
    key: "terms",
    title: "用户协议",
    body: [
      "本工具提供申请规划参考，不构成录取承诺，也不能替代学校的官方说明。",
      "推荐档位是规划建议，不是录取概率。",
      "数据可能滞后或存在录入错误，最终以官网为准。",
    ],
  },
  {
    key: "about",
    title: "关于",
    body: [`OfferPilot 第一阶段 MVP，版本 ${VERSION}。`],
  },
];

export default function SettingsView({ onClear }: { onClear: () => void }) {
  const [open, setOpen] = useState<string | null>("data");
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="grid gap-6">
      <header>
        <h1 className="text-xl font-extrabold">设置</h1>
      </header>

      <section className="card !p-0">
        {SECTIONS.map((s) => {
          const expanded = open === s.key;
          return (
            <div key={s.key} className="border-b border-[var(--color-line)] last:border-b-0">
              <button
                onClick={() => setOpen(expanded ? null : s.key)}
                aria-expanded={expanded}
                className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
              >
                <span className="text-sm font-bold">{s.title}</span>
                <span
                  className="text-xs font-bold text-[var(--color-ink-soft)] transition-transform"
                  style={{ transform: expanded ? "rotate(90deg)" : "none" }}
                >
                  ▶
                </span>
              </button>
              {expanded && (
                <ul className="grid gap-2 px-5 pb-5">
                  {s.body.map((line) => (
                    <li
                      key={line}
                      className="text-sm leading-relaxed text-[var(--color-ink-soft)]"
                    >
                      · {line}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </section>

      <section className="card">
        <h2 className="text-sm font-bold text-[var(--color-ink-soft)]">数据管理</h2>
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          清除这台设备上的内容：申请组合、已勾选的材料与流程进度。服务器上的申请档案不在清除范围内，
          所以下次打开仍然会加载回来。此操作无法撤销。
        </p>
        {confirming ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-[var(--color-danger)]">确定要清除吗？</span>
            <button
              className="btn !px-4 !py-2 !text-sm"
              style={{ background: "var(--color-danger)", color: "#fff" }}
              onClick={() => {
                onClear();
                setConfirming(false);
              }}
            >
              确认清除
            </button>
            <button className="btn btn-ghost !px-4 !py-2 !text-sm" onClick={() => setConfirming(false)}>
              取消
            </button>
          </div>
        ) : (
          <button
            className="btn btn-ghost mt-4 !text-[var(--color-danger)]"
            onClick={() => setConfirming(true)}
          >
            清除本机全部数据
          </button>
        )}
      </section>
    </div>
  );
}
