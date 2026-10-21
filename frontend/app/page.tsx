"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, ArrowRight, BarChart3, Check, ChevronDown, ChevronRight, CircleAlert, ExternalLink, FileText, Layers3, LoaderCircle, MessageSquareQuote, Search, ShieldCheck, Sparkles, Star, X } from "lucide-react";
import type { Evidence, Finding, Health, Report, Review, Task, Topic } from "../lib/types";

const uniqueCount = (evidence: Evidence[]) => new Set(evidence.map(e => e.review_id)).size;
const formatTime = (value: string) => new Date(value).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", hour12: false});
const safeLink = (value: string | null) => value && /^https?:\/\//i.test(value) ? value : undefined;

class ApiError extends Error {
  constructor(message: string, public status: number) {super(message);}
}

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...options, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof body?.detail === "string" ? body.detail : body?.detail?.message;
    throw new ApiError(message || (response.status === 422 ? "请输入正确的 10 位 ASIN。" : `请求失败（${response.status}），请检查后端连接。`), response.status);
  }
  return body;
}

function ReviewCard({review, quotes = []}: {review: Review; quotes?: string[]}) {
  return <article className="review-card">
    <div className="review-meta"><span className={`rating rating-${review.rating}`}><Star size={12} fill="currentColor"/> {review.rating}.0</span><span>{review.date || review.date_raw || "日期未知"}</span><span>ASIN · {review.source_asin || "归属未确认"}</span>{safeLink(review.review_url) && <a href={safeLink(review.review_url)} target="_blank" rel="noreferrer">原评论 <ExternalLink size={12}/></a>}</div>
    {quotes.length > 0 && <div className="evidence-quotes">{quotes.map((quote, i) => <p key={i}>“{quote}”</p>)}</div>}
    <div className="review-columns"><div><span className="eyebrow">ORIGINAL · 评论原文</span><h4>{review.title_original}</h4><p>{review.body_original}</p></div><div><span className="eyebrow">TRANSLATION · 中文翻译</span><h4>{review.title_zh}</h4><p>{review.body_zh || "此条评论尚未完成翻译。"}</p></div></div>
    <small className="review-id">{review.id} · 请求 ASIN {review.requested_asin}</small>
  </article>;
}

function SectionHeading({label, description, tag}: {label: string; description?: string; tag?: string}) {
  return <div className="section-heading"><div><h2>{label}</h2>{description && <p>{description}</p>}</div>{tag && <span className="tag"><Sparkles size={12}/>{tag}</span>}</div>;
}

function FeedbackBars({items, positive, onOpen}: {items: Finding[]; positive?: boolean; onOpen: (name: string, evidence: Evidence[]) => void}) {
  const max = Math.max(1, ...items.map(f => uniqueCount(f.evidence)));
  return <div className={`feedback-column ${positive ? "positive" : "negative"}`}><h3><span className="status-dot"/>{positive ? "用户认可点" : "差评痛点"}<small>{positive ? "4–5 星" : "1–2 星"}</small></h3>{items.length ? items.slice(0, 8).map((item, index) => <button className="feedback-row" onClick={() => onOpen(item.name, item.evidence)} key={item.name + index}><span>{item.name}</span><div className="bar-track"><i style={{width: `${uniqueCount(item.evidence) / max * 100}%`}}/></div><strong>{uniqueCount(item.evidence)}<small> 条</small></strong><ChevronRight size={14}/></button>) : <p className="quiet-empty">当前暂无可展示的已核验反馈</p>}</div>;
}

function Findings({items, onOpen, causes = false}: {items: Finding[]; onOpen: (name: string, evidence: Evidence[]) => void; causes?: boolean}) {
  return <div className="findings">{items.map((item, index) => <article className="finding" key={item.name + index}><div className="finding-top"><div><span className="issue-tag">{item.name}</span><small>{uniqueCount(item.evidence)} 条评论涉及</small></div><button className="evidence-button" onClick={() => onOpen(item.name, item.evidence)}>查看证据 <ChevronRight size={13}/></button></div><p>{item.description}</p>{causes && item.possible_cause && <div className="hypothesis"><span><Sparkles size={12}/> AI 推测 · 尚需验证</span><p>{item.possible_cause}</p><small>引用支持买家描述的现象，不代表已证实故障原因。</small></div>}{uniqueCount(item.evidence) === 1 && <small className="single-note">单条反馈，尚不足以判断问题的普遍性。</small>}</article>)}</div>;
}

export default function Home() {
  const [asin, setAsin] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [drawer, setDrawer] = useState<{name: string; evidence: Evidence[]} | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [starFilter, setStarFilter] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const busy = submitting || task?.status === "fetching" || task?.status === "analyzing";
  const report = task?.result;
  const final = !!task && !["fetching", "analyzing"].includes(task.status);

  useEffect(() => {api<Health>("/api/health").then(setHealth).catch(() => setConnectionError("后端服务尚未连接，请启动 FastAPI 后刷新页面。"));}, []);

  useEffect(() => {
    if (!task || !["fetching", "analyzing"].includes(task.status)) return;
    let cancelled = false;
    let revision = task.revision ?? -1;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const metadata = await api<Task>(`/api/analyses/${task.id}?include_result=false`);
        if (metadata.revision !== revision) {
          const next = await api<Task>(`/api/analyses/${task.id}`);
          revision = next.revision ?? -1;
          if (!cancelled) setTask(next);
        } else if (!cancelled) {
          setTask(previous => previous ? {...previous, ...metadata, result: previous.result} : previous);
        }
        if (!cancelled) setConnectionError("");
      } catch (e) {
        if (!cancelled && e instanceof ApiError && e.status === 404) {
          setTask(previous => previous ? {...previous, status: "failed", stage_message: "任务已不可用", error: {code: "TASK_EXPIRED", message: e.message}} : null);
          return;
        }
        if (!cancelled) setConnectionError(e instanceof Error ? e.message : "查询进度失败");
      }
      if (!cancelled) timer = setTimeout(poll, 2500);
    };
    timer = setTimeout(poll, 700);
    return () => {cancelled = true; clearTimeout(timer);};
  }, [task?.id, task?.status]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (drawer && dialog && !dialog.open) dialog.showModal();
    if (!drawer && dialog?.open) dialog.close();
  }, [drawer]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const value = asin.trim().toUpperCase();
    if (!/^[A-Z0-9]{10}$/.test(value)) {setError("请输入 10 位字母与数字组成的美国站 ASIN。"); return;}
    setSubmitting(true); setError(""); setConnectionError(""); setDrawer(null);
    try {
      const created = await api<{task_id: string}>("/api/analyses", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({asin: value})});
      setTask({id: created.task_id, asin: value, status: "fetching", stage_message: "正在获取评论", result: null, error: null, expires_at: null});
      setShowAll(false); setStarFilter(0);
    } catch (e) {setError(e instanceof Error ? e.message : "提交失败");}
    finally {setSubmitting(false);}
  }

  const openEvidence = (name: string, evidence: Evidence[]) => setDrawer({name, evidence});
  async function download(format: "xlsx" | "md") {
    if (!task || downloading) return;
    setDownloading(true);
    try {
      const response = await fetch(`/api/analyses/${task.id}/export?format=${format}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail?.message || "导出失败，请重试。");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] || `${task.asin}.${format}`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {setError(e instanceof Error ? e.message : "导出失败");}
    finally {setDownloading(false);}
  }
  const dateRange = report?.reviews.map(r => r.date).filter((d): d is string => !!d).sort();
  const reviews = report?.reviews.filter(r => !starFilter || r.rating === starFilter) || [];
  const selectedIds = new Set(drawer?.evidence.map(e => e.review_id));

  return <>
    <header className="topbar"><div className="topbar-inner"><a className="brand" href="/"><span className="brand-mark"><Layers3 size={21}/></span><strong>Review<span>Lens</span></strong><span className="brand-divider"/><span className="brand-description">亚马逊评论洞察</span></a><div className="header-right"><span className="market"><span className="us-flag">US</span>美国站</span><span className="version">MVP 01</span></div></div></header>
    <main>
      <section className="intro"><div><div className="eyebrow intro-eyebrow"><span/> VOICE OF CUSTOMER</div><h1>读懂评论，发现产品机会<span>。</span></h1><p>从买家原声中提炼认可与问题，每一个洞察，都有原文可循。</p></div><div className="intro-note"><ShieldCheck size={18}/><div>基于原文 · 证据可溯<small>AI 辅助分析，保留人工判断</small></div></div></section>

      <section className="card search-card"><form onSubmit={submit}><label htmlFor="asin">开始分析商品<span>输入 Amazon.com 商品 ASIN</span></label><div className="search-row"><div className="input-wrap"><Search size={19}/><input id="asin" value={asin} onChange={e => setAsin(e.target.value.toUpperCase())} maxLength={10} placeholder="例如 B0XXXXXXXX" autoComplete="off" disabled={busy} aria-describedby="input-help"/><span className="input-market">US</span></div><button className="primary-button" disabled={busy || !asin.trim()} type="submit">{busy ? <><LoaderCircle size={17} className="spin"/>分析进行中</> : <>分析评论 <ArrowRight size={17}/></>}</button></div><div className="search-help" id="input-help"><span><Check size={13}/> 最新最多 {health?.max_reviews ?? 100} 条</span><span><Check size={13}/> 不限评论日期</span><span><Check size={13}/> 原文 + 中文翻译</span><span className="source-note">数据源 Bright Data <span>·</span> AI 分析</span></div></form></section>

      {error && <div className="notice error" role="alert"><CircleAlert size={17}/>{error}</div>}
      {connectionError && <div className="notice warning" role="status"><CircleAlert size={17}/>{connectionError}</div>}
      {health && !health.configured && <div className="notice warning"><CircleAlert size={17}/><div><strong>服务端配置待完成</strong><p>请在后端 .env 中配置 Bright Data API Key、Dataset ID 及模型 API Key。配置完成并重启后端后，即可获取真实评论。</p></div></div>}

      {task && <section className="card progress-card" aria-live="polite"><div className="progress-summary">{busy ? <LoaderCircle size={18} className="spin orange"/> : task.status === "failed" ? <CircleAlert size={18} className="orange"/> : <Check size={18} className="green"/>}<div><strong>{task.stage_message}</strong><small>ASIN · {task.asin}{task.expires_at && ` · 临时结果保留至 ${formatTime(task.expires_at)}（北京时间）`}</small></div></div><div className="steps">{["获取评论", "分析与翻译", "完成"].map((step, i) => {const active = task.status === "fetching" ? 0 : task.status === "analyzing" ? 1 : 2; return <span className={i <= active ? "active" : ""} key={step}><i>{i < active && task.status !== "failed" ? <Check size={10}/> : i + 1}</i>{step}{i < 2 && <b/>}</span>;})}</div></section>}
      {task?.error && <div className="notice error" role="alert"><CircleAlert size={18}/><div><strong>{task.error.message}</strong><p>错误码：{task.error.code}</p></div></div>}

      {task?.timings && <div className="sample-caption">{task.timings.collection_seconds !== undefined && <span>评论采集 {task.timings.collection_seconds.toFixed(1)} 秒</span>}{task.timings.analysis_seconds !== undefined && <span>AI 分析 {task.timings.analysis_seconds.toFixed(1)} 秒</span>}{final && task.timings.total_seconds !== undefined && <span>总耗时 {task.timings.total_seconds.toFixed(1)} 秒</span>}</div>}
      {report ? <div className="report">
        {!final && <div className="notice warning" role="status"><LoaderCircle size={16} className="spin"/>正在分批更新：已完成的原文、翻译和反馈会提前展示；当前分类及条数仍可能变化，请以最终报告为准。</div>}
        <div className="report-title"><div><span className="eyebrow">ANALYSIS REPORT</span><h2>{report.product_name || `商品 ${report.asin}`}</h2><p><a href={safeLink(report.product_url)} target="_blank" rel="noreferrer">{report.asin} <ExternalLink size={12}/></a><span>采集于 {formatTime(report.collected_at)}（北京时间）</span></p></div><div className="export-buttons"><button className="secondary-button" disabled={downloading || !final} onClick={() => download("md")}><FileText size={15}/>Markdown</button><button className="secondary-button" disabled={downloading || !final} onClick={() => download("xlsx")}><ArrowDownToLine size={15}/>导出 Excel</button></div></div>
        {!!report.warnings.length && <details className="coverage" open={task.status === "partial" || task.status === "failed" ? true : undefined}><summary><CircleAlert size={15}/><span>数据范围与分析说明</span><small>{report.warnings.length} 项</small><ChevronDown size={15}/></summary><ul>{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
        <section className="card stats-card"><div className="sample-total"><span>本次有效样本</span><strong>{report.total}<small>条</small></strong><small>已分析 {report.analyzed_count} 条</small></div><div className="star-stats">{[1,2,3,4,5].map(i => <div key={i}><span><Star size={12} fill="currentColor"/>{i} 星</span><strong>{report.stars[String(i)]}</strong></div>)}</div><div className="negative-rate"><span>样本差评占比 <small>1–2 星</small></span><strong>{report.negative_percentage === null ? "—" : <>{report.negative_percentage}<small>%</small></>}</strong><small>仅代表本次样本，非商品整体差评率</small></div></section>
        <div className="sample-caption">评论日期：{dateRange?.length ? `${dateRange[0]} 至 ${dateRange[dateRange.length-1]}` : "未提供可靠日期"} <span>·</span> {report.latest_verified ? "数据源最新排序已确认" : "最新覆盖未确认"} <span>·</span> 评论范围：{{unknown: "未确认", parent_page: "父商品页面", child_only: "子商品", mixed: "混合变体"}[report.scope] || report.scope}</div>

        {report.total === 0 ? <section className="card empty-result"><MessageSquareQuote size={32}/><h2>当前未获取到有效评论</h2><p>这不代表商品没有评论。请查看数据范围说明或供应商任务详情。</p></section> : <>
          {report.analyzed_count > 0 ? <>
          <section className="summary-card"><span className="summary-icon"><MessageSquareQuote size={22}/></span><div><div className="summary-title"><h2>评论摘要</h2><span className="tag">AI 归纳</span></div><p>{report.analyzed_count ? `已分析 ${report.analyzed_count} 条评论，识别 ${report.issues.length} 类低星问题与 ${report.praises.length} 类高星认可点。${report.issues[0] ? `低星样本重点提及“${report.issues[0].name}”` : "当前没有可展示的已核验低星问题"}${report.praises[0] ? `；高星买家关注“${report.praises[0].name}”。` : "。"}以下结论均可查看对应原文证据。` : "评论已获取，但 AI 分析尚未完成。请查看错误说明；原文仍可在下方查看。"}</p></div></section>
          <section className="card"><SectionHeading label="用户反馈分布" description="按涉及评论条数展示，点击反馈查看原文证据"/><div className="feedback-grid"><FeedbackBars items={report.praises} positive onOpen={openEvidence}/><FeedbackBars items={report.issues} onOpen={openEvidence}/></div></section>
          <section className="card"><SectionHeading label="评价主题表现" description="全部星级参与分析，同一条评论可以涉及多个主题"/><div className="table-scroll"><table className="topic-table"><thead><tr><th>评价主题</th><th>涉及条数</th><th>星级结构</th><th/></tr></thead><tbody>{report.topics.map((topic: Topic, index) => {const ids = new Set(topic.evidence.map(e => e.review_id)); const group = report.reviews.filter(r => ids.has(r.id)); const counts = [group.filter(r => r.rating <= 2).length, group.filter(r => r.rating === 3).length, group.filter(r => r.rating >= 4).length]; return <tr key={topic.name + index}><td>{topic.name}</td><td><strong>{ids.size}</strong><small> 条</small></td><td><div className="stacked-bar">{counts.map((n, i) => n > 0 && <i className={`segment segment-${i}`} key={i} style={{width: `${n / ids.size * 100}%`}}>{n}</i>)}</div><div className="stacked-labels"><span>低星 {counts[0]}</span><span>3 星 {counts[1]}</span><span>高星 {counts[2]}</span></div></td><td><button className="text-button" onClick={() => openEvidence(topic.name, topic.evidence)}>查看评论 <ChevronRight size={12}/></button></td></tr>;})}</tbody></table></div>{!report.topics.length && <p className="quiet-empty">暂无已核验主题</p>}<p className="footnote"><i className="legend low"/>1–2 星 <i className="legend mid"/>3 星 <i className="legend high"/>4–5 星 <span>各主题条数相加可能超过样本总数。</span></p></section>
          <section className="card"><SectionHeading label="常见差评问题与可能原因" description="买家反馈与 AI 推测分开展示，保留人工判断" tag="原文可溯"/>{report.issues.length ? <Findings items={report.issues} causes onOpen={openEvidence}/> : <p className="quiet-empty">{report.stars["1"] + report.stars["2"] === 0 ? "当前最新样本暂无 1–2 星差评。" : "差评分析未形成可核验结果，不代表没有问题。"}</p>}</section>
          <div className="two-columns"><section className="card"><SectionHeading label="3 星评论反馈" description="中评中的认可、不足与改进诉求"/>{report.neutral_feedback.length ? <Findings items={report.neutral_feedback} onOpen={openEvidence}/> : <p className="quiet-empty">当前无可展示的已核验 3 星反馈</p>}</section><section className="card"><SectionHeading label="好评摘要" description="仅依据 4–5 星评论" tag="AI 归纳"/>{report.praises.length ? <Findings items={report.praises} onOpen={openEvidence}/> : <p className="quiet-empty">当前无可展示的已核验好评摘要</p>}</section></div>
          {report.usage_insights.length > 0 && <section className="card"><SectionHeading label="使用情境洞察" description="仅归纳原文明确提及的情境"/><Findings items={report.usage_insights} onOpen={openEvidence}/></section>}
          </> : <section className="card"><SectionHeading label={final ? "AI 分析暂不可用" : "正在生成 AI 分析"}/><p className="quiet-empty">{final ? "本次分析尚未完成，不代表没有问题或认可点。请查看上方具体错误；下方原始评论仍可查看和导出。" : "原文与星级统计已就绪，第一批分析完成后将在此自动展示，无需刷新。"}</p></section>}
          <section className="card"><SectionHeading label="评论明细" description="保留买家原声与中文翻译，方便交叉核对"/><div className="review-filters">{[0,1,2,3,4,5].map(i => <button key={i} className={starFilter === i ? "selected" : ""} onClick={() => {setStarFilter(i);setShowAll(false);}}>{i ? `${i} 星` : "全部"}<span>{i ? report.stars[String(i)] : report.total}</span></button>)}</div><div className="review-list">{(showAll ? reviews : reviews.slice(0,5)).map(r => <ReviewCard review={r} key={r.id}/>)}</div>{!reviews.length && <p className="quiet-empty">此星级暂无评论</p>}{reviews.length > 5 && <button className="expand-button" onClick={() => setShowAll(!showAll)}>{showAll ? "收起评论" : `查看全部 ${reviews.length} 条评论`}<ChevronDown size={15}/></button>}</section>
        </>}
      </div> : !busy && !task && <section className="welcome"><div className="welcome-symbol"><MessageSquareQuote size={30}/><span><Search size={17}/></span></div><h2>下一次产品改进，藏在买家的评论里</h2><p>输入一个 ASIN，开始一次有证据的评论分析。</p><div className="welcome-features"><div><BarChart3 size={20}/><strong>看清反馈分布</strong><p>各星级样本与买家认可点</p></div><div><MessageSquareQuote size={20}/><strong>追溯问题证据</strong><p>差评分类、原文及中文翻译</p></div><div><FileText size={20}/><strong>带走分析结果</strong><p>导出 Excel 与 Markdown</p></div></div></section>}
      {busy && !final && !report && <section className="working"><div className="working-graphic"><span/><span/><span/></div><h2>{task?.status === "analyzing" ? "正在阅读买家的每一条反馈" : "正在收集买家原声"}</h2><p>获取与分析可能需要几分钟。请保留此页面，完成后将自动展示结果。</p></section>}
      <footer><span>Review Lens <b>·</b> 从评论到洞察</span><span><ShieldCheck size={13}/> 原文是证据，AI 是辅助，判断由你完成</span></footer>
    </main>
    <dialog ref={dialogRef} onCancel={() => setDrawer(null)} onClose={() => setDrawer(null)} onClick={e => {if (e.target === e.currentTarget) setDrawer(null);}} aria-labelledby="evidence-title"><div className="drawer-head"><div><span className="eyebrow">REVIEW EVIDENCE</span><h2 id="evidence-title">{drawer?.name}</h2><p>{selectedIds.size} 条关联评论 · 原文与中文翻译</p></div><button className="icon-button" onClick={() => setDrawer(null)} aria-label="关闭证据"><X size={20}/></button></div><div className="drawer-body">{report?.reviews.filter(r => selectedIds.has(r.id)).map(r => <ReviewCard key={r.id} review={r} quotes={drawer?.evidence.filter(e => e.review_id === r.id).map(e => e.quote)}/>)}</div></dialog>
  </>;
}
