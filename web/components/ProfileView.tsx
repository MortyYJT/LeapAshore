"use client";

import type { Profile } from "@/lib/types";

interface Props {
  profile: Profile;
  onRestart: () => void;
  onClear: () => void;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-[var(--color-line)] py-3 last:border-b-0">
      <span className="text-sm text-[var(--color-ink-soft)]">{label}</span>
      <span className="text-right text-sm font-semibold">{value || "—"}</span>
    </div>
  );
}

export default function ProfileView({ profile, onRestart, onClear }: Props) {
  const school =
    profile.schoolOrigin === "海外"
      ? `${profile.schoolName || "海外院校"} · ${profile.overseasBand ?? "—"}`
      : profile.schoolName
        ? `${profile.schoolName} · ${profile.domesticTier ?? "层次未识别"}`
        : `未填写校名 · ${profile.domesticTier ?? "—"}`;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="card">
        <h2 className="text-lg font-extrabold">申请档案</h2>
        <div className="mt-3">
          <Row label="当前学历" value={profile.educationLevel ?? "—"} />
          <Row label="院校" value={school} />
          <Row label="本科专业" value={profile.major} />
          <Row
            label="均分"
            value={profile.gpaScore ? `${profile.gpaScore} / ${profile.gpaScale}` : ""}
          />
          <Row label="目标学位" value={profile.targetDegree ?? "—"} />
          <Row label="目标方向" value={profile.targetField ?? "—"} />
          <Row label="语言成绩" value={profile.englishScore || "未提供"} />
          <Row
            label="年度预算"
            value={profile.annualBudgetCny ? `${profile.annualBudgetCny / 10000} 万` : ""}
          />
          <Row label="入学时间" value={profile.intake} />
        </div>
        <button className="btn btn-ghost mt-5" onClick={onRestart}>
          重新填写背景
        </button>
      </section>

      <section className="card">
        <h2 className="text-lg font-extrabold">数据与隐私</h2>
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          MVP 阶段，申请档案与进度
          <strong> 保存在这台设备的浏览器里</strong>
          （localStorage），没有上传到任何服务器，也没有账号体系。清除下面这个按钮即可完全删除。
        </p>
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          接入后端后，这里会换成服务端存储，并提供导出与删除接口；档案中不应包含姓名、邮箱等可以直接识别个人身份的信息。
        </p>
        <button className="btn btn-ghost mt-5 !text-[var(--color-danger)]" onClick={onClear}>
          清除本机全部数据
        </button>
      </section>
    </div>
  );
}
