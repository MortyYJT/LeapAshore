"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button, Empty, Loading, Notice, Panel, Pill } from "@/components/ui";
import { PAGE_SIZE, fetchVerificationPages, type PageListItem, type VerificationStatus } from "@/lib/admin";

const STATUS_OPTIONS: [VerificationStatus, string][] = [
  ["unverified", "待核验"],
  ["verified", "已核验"],
  ["all", "全部"],
];

/** Pages that back imported programs; the ones applicants put in a portfolio come first. */
export function VerificationList() {
  const [status, setStatus] = useState<VerificationStatus>("unverified");
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: PageListItem[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchVerificationPages({ status, q, offset })
      .then((body) => live && (setData(body), setError(null)))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [status, q, offset]);

  return (
    <section className="section" aria-labelledby="verify-head">
      <div className="section-head">
        <h2 id="verify-head">
          官方页面<span className="count num">{data ? data.total : ""}</span>
        </h2>
        <div className="toolbar">
          <div className="seg" role="group" aria-label="核验状态">
            {STATUS_OPTIONS.map(([value, label]) => (
              <button key={value} type="button" aria-pressed={status === value} onClick={() => (setStatus(value), setOffset(0))}>
                {label}
              </button>
            ))}
          </div>
          <form
            className="toolbar"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              setQ(draft);
              setOffset(0);
            }}
          >
            <label htmlFor="verify-q" className="sr-only">搜索学校、项目或网址</label>
            <input id="verify-q" className="input" style={{ width: 240 }} placeholder="学校、项目或网址" value={draft} onChange={(e) => setDraft(e.target.value)} />
            <Button type="submit" small>搜索</Button>
          </form>
        </div>
      </div>
      {error && <Notice error>{error}</Notice>}
      {!data && !error && <Loading what="页面列表" />}
      {data && data.items.length === 0 && <Empty>没有符合条件的页面。</Empty>}
      {data && data.items.length > 0 && (
        <Panel label="官方页面">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>页面</th>
                  <th>学校</th>
                  <th>项目</th>
                  <th className="num">在组合里</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.sourceId}>
                    <td>
                      <div className="two-line">
                        <Link className="l1" href={`/admin/sources/${encodeURIComponent(item.sourceId)}`}>{item.title}</Link>
                        <div className="l2" style={{ overflowWrap: "anywhere" }}>{item.url}</div>
                      </div>
                    </td>
                    <td>{item.school ?? "未知"}</td>
                    <td>
                      <span className="num">{item.programs.length}</span> 个
                      {item.programs.some((p) => p.dataStatus !== "机器核对") && <span className="muted">（含待核验）</span>}
                    </td>
                    <td className="num">{item.inPortfolios}</td>
                    <td>
                      {item.verifiedAt ? <Pill kind="tier">已核验</Pill> : <Pill>待核验</Pill>}
                      {!item.snapshotReady && <span className="muted small"> 无快照</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <span className="muted">
              第 <span className="num">{offset + 1}</span>–<span className="num">{offset + data.items.length}</span> 条，共{" "}
              <span className="num">{data.total}</span> 条
            </span>
            <div className="toolbar">
              <Button small disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</Button>
              <Button small disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</Button>
            </div>
          </div>
        </Panel>
      )}
    </section>
  );
}
