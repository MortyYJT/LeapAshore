import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page">
      <h1>没有这个页面</h1>
      <p className="lede">地址可能已经变了。可以从这里继续：</p>
      <div className="toolbar section">
        <Link className="btn btn-primary" href="/">首页</Link>
        <Link className="btn btn-secondary" href="/schools">学校库</Link>
      </div>
    </main>
  );
}
