"use client";

import Link from "next/link";
import { useMemo, useRef, useState, type ReactNode } from "react";

import { RequireAccount, useAuth } from "@/components/auth/AuthProvider";
import { MaterialsBoard, type MaterialsActions } from "@/components/materials/MaterialsBoard";
import { MaterialFiles } from "@/components/profile/MeView";
import { useApplicationRecords } from "@/components/shell/ApplicationRecords";
import { Loading, Notice } from "@/components/ui";
import { writeApplicationRecord, type ApplicationRecord } from "@/lib/application-records";
import { materialsModel, type MapLine, type MaterialsModel } from "@/lib/materials-map";
import { StaleVersionError } from "@/lib/sync-conflict";

/**
 * 材料: what each program asks the applicant to send, drawn as a line map and listed under it, then
 * the applicant's own checklists and the files they uploaded.
 *
 * Everything about a program's requirements is what the catalogue collected from its official page;
 * a program whose page has not been read says so, and so does one whose page lists no documents. A signed-out visitor gets the same map for a few
 * catalogue programs when enough of them have been read, and the plain sign-in block otherwise.
 */
export default function MaterialsPage() {
  return (
    <main className="page materials">
      <RequireAccount
        what="你的材料"
        fallback={<SignedOut />}
        pending={
          <Frame finding="正在读取登录状态…">
            <Loading what="你的材料" />
          </Frame>
        }
      >
        <Workspace />
      </RequireAccount>
    </main>
  );
}

function Frame({ finding, demo = false, children }: { finding: ReactNode; demo?: boolean; children: ReactNode }) {
  return (
    <>
      <header className={`page-head${demo ? " has-note" : ""}`}>
        <div>
          {demo ? (
            <div className="marked">
              <h1>材料</h1>
              <span className="pill pill-sample">演示</span>
            </div>
          ) : (
            <h1>材料</h1>
          )}
          <p className="finding">{finding}</p>
        </div>
      </header>
      {children}
    </>
  );
}

/** A few programs by name, more than two as a count. */
function named(lines: readonly MapLine[]): string {
  return lines.length > 2 ? `${lines.length} 个项目` : lines.map((line) => line.record.school).join("、");
}

/** The sentence under the title: how much is known, what is shared, what differs, how far along. */
function Finding({ model }: { model: MaterialsModel }) {
  const { lines, unread, silent, manual, shared, differing, total, done, closed } = model;
  const open = lines.length + unread.length + silent.length + manual.length;
  if (!open) return <>{closed ? `${closed} 个申请都已提交或已有结果，没有要备的材料。` : "还没有申请。"}</>;
  const waiting = named(unread);
  if (!lines.length) {
    // A page that lists nothing is said as that, and never as a program that asks for nothing.
    if (silent.length) {
      return (
        <>
          {unread.length > 0 && `${waiting}的官网要求还没提取。`}
          {named(silent)}的项目页没有列申请材料，要到官网核对。
        </>
      );
    }
    return <>{unread.length ? `${waiting}的官网要求还没提取，先用自己的清单记。` : "手动添加的申请没有学校库的材料清单，用自己的清单记。"}</>;
  }
  return (
    <>
      {lines.length === 1 ? (
        <>
          {lines[0].record.school}的官网要求有 <b>{total} 项</b>，已备好 {done} 项。
        </>
      ) : (
        <>
          {lines.length} 个项目都要、要求也一样的材料有 <b>{shared.length} 项</b>
          {shared.length > 0 && "，准备一份就够"}；要求不一样的有 <b>{differing.length} 项</b>。按项目累计 {total} 项，已备好 {done} 项。
        </>
      )}
      {unread.length > 0 && `${waiting}的官网要求还没提取。`}
      {silent.length > 0 && `${named(silent)}的项目页没有列申请材料，要到官网核对。`}
      {closed > 0 && `另有 ${closed} 个已提交或已有结果的申请没有列出。`}
    </>
  );
}

function Workspace() {
  const records = useApplicationRecords();
  const model = useMemo(() => (records.data ? materialsModel(records.data) : null), [records.data]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const latest = useRef<ApplicationRecord[] | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const pending = useRef(0);

  if (!model || !records.data) {
    return records.error ? (
      <Frame finding="没能读取你的申请。">
        <Notice error>{records.error}</Notice>
        <p>
          <button type="button" className="btn btn-secondary" onClick={records.reload}>
            重试
          </button>
        </p>
        {/* The uploaded files have their own read, and do not wait for the applications. */}
        <section className="block block-files" aria-label="上传的文件">
          <MaterialFiles />
        </section>
      </Frame>
    ) : (
      <Frame finding="正在读取你的申请…">
        <Loading what="你的材料" />
      </Frame>
    );
  }

  // Saves run one after another, whatever started them: ticking a shared material sends one save per
  // program, and each is based on the version the save before it returned.
  latest.current = records.data;
  function save(record: ApplicationRecord, payload: Record<string, unknown>): Promise<void> {
    pending.current += 1;
    setBusy(true);
    setProblem(null);
    const run = queue.current.then(async () => {
      try {
        const stored = latest.current?.find((other) => other.id === record.id) ?? record;
        const saved = await writeApplicationRecord(record.id, { ...payload, baseVersion: stored.version });
        if (saved && latest.current) {
          latest.current = latest.current.map((other) => (other.id === saved.id ? saved : other));
          records.set(latest.current);
        }
      } catch (error) {
        if (error instanceof StaleVersionError) {
          // Changed on another device, or the catalogue's requirement was imported again: nothing was
          // written. The refusal carries the record as it is stored, so the page shows that at once and
          // the next save in the queue is based on it; a reload could be overtaken by that save.
          const stored = error.current as ApplicationRecord | null;
          if (stored && latest.current) {
            latest.current = latest.current.map((other) => (other.id === stored.id ? stored : other));
            records.set(latest.current);
          } else records.reload();
          setProblem("这条申请在别处改过，或者官网的要求更新了，这次的改动没有保存。页面已经换成最新的内容，请再做一次。");
        } else {
          // Refused for another reason (the catalogue dropped the entry, the network): read again, so
          // the page does not keep showing what the server would refuse.
          records.reload();
          setProblem(error instanceof Error ? error.message : "没有保存，请稍后再试。");
        }
      } finally {
        pending.current -= 1;
        if (!pending.current) setBusy(false);
      }
    });
    queue.current = run;
    return run;
  }
  const actions: MaterialsActions = {
    tick: (record, entries, ready) =>
      save(record, {
        materialTicks: Object.fromEntries(entries.map((entry) => [entry.key, ready])),
        ...(ready ? { materialBasis: Object.fromEntries(entries.map((entry) => [entry.key, entry.digest])) } : {}),
      }),
    custom: (record, next) => save(record, { customMaterials: next }),
  };
  const drawn = [...model.lines, ...model.unread, ...model.silent, ...model.manual];
  const open = drawn.length;
  // The rail also lists submitted applications, which this screen leaves out: one of those picked
  // must not dim every line here.
  const selected = records.selected && drawn.some((line) => line.record.id === records.selected) ? records.selected : null;

  return (
    <Frame finding={<Finding model={model} />}>
      {records.error && <Notice error>没能更新，下面是上次读到的内容：{records.error}</Notice>}
      {problem && <Notice error>{problem}</Notice>}
      {open > 0 ? (
        <MaterialsBoard model={model} selected={selected} actions={actions} busy={busy} />
      ) : (
        <section className="block" aria-labelledby="h-map">
          <div className="block-head">
            <h2 id="h-map">各项目要什么</h2>
          </div>
          <div className="map-empty">
            <p>
              <b>{model.closed ? "没有在准备的申请" : "先添加申请"}</b>
              每个在准备的申请是一条线，它的官网要什么材料，线就在哪里停。
            </p>
            <Link className="btn btn-primary" href="/applications?add=1">
              添加申请项目
            </Link>
            <Link className="btn btn-secondary" href="/schools">
              浏览学校库
            </Link>
          </div>
        </section>
      )}
      <section className="block block-files" aria-label="上传的文件">
        <MaterialFiles />
      </section>
    </Frame>
  );
}

/**
 * For a visitor: the map for a few catalogue programs, labelled as a demo, when the catalogue has read
 * enough of their pages. Otherwise the plain block: no requirement is ever drawn that was not collected.
 */
function SignedOut() {
  const { requireLogin } = useAuth();
  const { demo, demoMaterials, demoPending, selected } = useApplicationRecords();
  // A program the rail's demo list also shows takes the rail's colour.
  const model = useMemo(
    () => (demoMaterials ? materialsModel(demoMaterials, (demo ?? []).map((record) => record.id)) : null),
    [demo, demoMaterials],
  );
  if (demoPending) {
    return (
      <Frame finding="正在读取学校库…">
        <Loading what="学校库" />
      </Frame>
    );
  }
  if (!model) {
    return (
      <Frame finding="登录后，每个申请要交的材料在这里画成一张线路图。">
        <section className="block" aria-labelledby="h-map">
          <div className="block-head">
            <h2 id="h-map">各项目要什么</h2>
          </div>
          <div className="map-empty">
            <p>
              <b>登录后查看你的材料</b>
              用邮箱收一个 6 位验证码就能登录，第一次登录会自动注册。学校库不用登录也能看。
            </p>
            <button type="button" className="btn btn-primary" onClick={() => void requireLogin()}>
              登录
            </button>
            <Link className="btn btn-secondary" href="/schools">
              浏览学校库
            </Link>
          </div>
        </section>
      </Frame>
    );
  }
  const picked = selected && model.lines.some((line) => line.record.id === selected) ? selected : null;
  return (
    <Frame demo finding={<Finding model={model} />}>
      <div className="demo-note" role="note">
        <p>这是演示：项目和材料要求来自学校库，都没有勾选。登录后这里是你自己的申请。</p>
        <button type="button" className="btn btn-primary" onClick={() => void requireLogin()}>
          登录
        </button>
      </div>
      <MaterialsBoard model={model} selected={picked} actions={null} onBlocked={() => void requireLogin()} />
    </Frame>
  );
}
