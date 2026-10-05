"use client";

export default function AdvisorView() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="card">
        <div className="flex items-center gap-2">
          <span className="text-xl">💬</span>
          <h2 className="text-lg font-extrabold">留学顾问</h2>
          <span className="tag tag-muted">建设中</span>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          很快你就可以直接用说话的方式推进申请，不用一格格填表。
        </p>
        <ul className="mt-4 grid gap-3 text-sm">
          <li className="rounded-xl bg-[var(--color-surface)] p-3">
            <strong>问要求</strong>
            <span className="mt-0.5 block text-[var(--color-ink-soft)]">
              问某个项目要什么均分、什么先修课，只回答有官方来源的；查不到就直说查不到。
            </span>
          </li>
          <li className="rounded-xl bg-[var(--color-surface)] p-3">
            <strong>说情况</strong>
            <span className="mt-0.5 block text-[var(--color-ink-soft)]">
              比如「我雅思考了 6.5」「预算降到 40 万」，档案和流程进度自动更新。
            </span>
          </li>
          <li className="rounded-xl bg-[var(--color-surface)] p-3">
            <strong>改决定</strong>
            <span className="mt-0.5 block text-[var(--color-ink-soft)]">
              换首选项目、换申请组合这类会影响到后面安排的操作，会先跟你确认一次。
            </span>
          </li>
        </ul>
      </section>

      <section className="card">
        <h2 className="text-lg font-extrabold">暂时你可以这样做</h2>
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          顾问还没接上之前，档案在「个人中心」改，材料清单在「流程进度」里勾——效果是一样的，
          只是要多点几下。
        </p>
      </section>
    </div>
  );
}
