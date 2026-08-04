import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InfoTip, TooltipProvider } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Message, MessageScroller, SendButton } from "@/components/ai/chat";
import { Loader2 } from "lucide-react";
import { useStreamChat } from "@/hooks/useStreamChat";
import { applyToolResult, type ViewPatch } from "@/lib/stream";

// ──────────────────────────────── types ────────────────────────────────
type Stage = "opening" | "ticker_clarify" | "extracted" | "menu" | "confirm_card" | "confirmed";
interface Evidence { url: string; excerpt: string; }
interface Cond { id: string; layer: "mirror" | "redline"; text: string; threshold?: any; template?: string | null; source_type?: string; }
interface Assumption { id: string; text: string; }
interface ManualItem { id: string; text: string; reason: string; cadence: string; }
interface Anchor { anchor_type: string; anchor_value: number | null; note: string; }
interface NextVerdict { event: string; date: string | null; source_note: string; }
interface Source { form: string; date: string; url: string; note: string; }
interface OpenQ { field: string; reason: string; text?: string; }
interface Coverage { total: number; excluded: number; reasons: string[]; excluded_items: { mirror_text: string; reasons: string[] }[]; }
interface CardT {
  card_id: string; ticker: string; filer_type: string; holding_reason_raw: string;
  key_assumptions: Assumption[]; broken_conditions: Cond[]; manual_check_items: ManualItem[];
  entry_anchor: Anchor | null; next_verdict: NextVerdict | null; position_cap_tier: string | null;
  holding_horizon: string | null;
  confirmation: { confirmed_by_user: boolean };
}
interface MenuT { assumptions: string[]; mirrors: { assumption: string; mirror_text: string }[]; coverage?: Coverage; }
interface View {
  stage: Stage; assistant: string; card: CardT | null; menu: MenuT | null;
  open_questions: OpenQ[]; ticker: string; ticker_title?: string | null; sources?: Source[]; error: string | null;
  metrics?: { turns: number; clarification_rounds: number; converged: boolean };
  session_id?: string;
}
interface Msg { id: number; role: "user" | "assistant"; text: string; streaming?: boolean; streamed?: boolean; }

const UNDECIDED = ["无法确定", "说不清", "说不上", "不清楚", "不知道", "菜单", "候选", "给选项", "给候选", "不知道破什么", "想不出来"];
const isUndecided = (t: string) => UNDECIDED.some((h) => (t || "").includes(h));
const esc = (s: unknown) => String(s ?? "");
let _mid = 0;
const nextMid = () => ++_mid;

const ANCHOR_TYPES = ["ttm_gaap_pe", "forward_non_gaap_pe", "normalized_pe", "normalized_operating_pe",
  "normalized_fwd_gaap_pe", "p_fcf", "p_tbv", "operating_multiple_2col", "other"];
const ANCHOR_CN: Record<string, string> = {
  ttm_gaap_pe: "TTM GAAP 市盈率", forward_non_gaap_pe: "Forward non-GAAP 市盈率", normalized_pe: "归一化市盈率",
  normalized_operating_pe: "归一化营业利润市盈率", normalized_fwd_gaap_pe: "归一化 Forward GAAP 市盈率",
  p_fcf: "市现率（P/FCF）", p_tbv: "市有形净资产（P/TBV，银行股）", operating_multiple_2col: "巴菲特两栏法运营倍数", other: "其他",
};
const TIER_NOTE = "仓位上限档按 ticker 规则查表（Skill v4 档位），不由模型猜。硬thesis ~40% / 中 ~25% / 软 ~10% / 宽基ETF ~50% / trinket 只减不加。";

// ──────────────────────────── 打字机（验收点 8） ────────────────────────────
function Typewriter({ text, onDone }: { text: string; onDone?: () => void }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    if (!text) { onDone?.(); return; }
    let i = 0;
    const id = setInterval(() => {
      i += 2;
      setN(i);
      if (i >= text.length) { clearInterval(id); onDone?.(); }
    }, 24);
    return () => clearInterval(id);
  }, [text]);
  return <span>{text.slice(0, n)}{n < text.length ? <span className="opacity-40">▋</span> : null}</span>;
}

// ──────────────────────────── 流式文本（SSE token 逐 chunk 追加） ────────────────────────────
// 与 Typewriter 区分：Typewriter 拿到整段后逐字动画（fetch 回退路径用）；
// LiveText 直接渲染已收到的 token（流由后端驱动），streaming 时光标呼吸。
// 用 streamed 标记避免流结束切回 Typewriter 时整段重播（streamed=true 永远走 LiveText）。
function LiveText({ text, streaming }: { text: string; streaming?: boolean }) {
  return <span>{text}{streaming ? <span className="opacity-40 animate-pulse">▋</span> : null}</span>;
}

// 三阶段进度行已删（F2：进度改由卡片字段逐格点亮表达，不再单独呈现）

// ──────────────────────────── 拒判降级橙边卡（验收点 4） ────────────────────────────
function RefusalCard({ items }: { items: ManualItem[] }) {
  if (!items.length) return null;
  return (
    <div className="border-l-4 border-amber bg-amber-soft rounded-r-md p-3 my-2 text-sm">
      <div className="font-medium text-amber mb-1">这几条接不了自动核对</div>
      {items.map((m, i) => (
        <div key={i} className="mb-2">
          <div className="text-foreground">「{m.text}」是价格图形型——系统不接行情，没法每天自动盯。</div>
          <div className="text-muted-foreground">记到 <b>人工自查项</b>（不会从你的卡里消失）。</div>
          <div className="text-muted-foreground">每月 1 号提醒你自己看一眼。</div>
        </div>
      ))}
    </div>
  );
}

// ──────────────────────────── 抽屉字段（验收点 3/5/6，F2 三态） ────────────────────────────
type FieldState = "done" | "in-progress" | "pending";
function DrawerField({ label, hint, justFilled, state = "done", action, children }: { label: string; hint?: string; justFilled?: boolean; state?: FieldState; action?: string; children: ReactNode }) {
  if (state === "in-progress") {
    return (
      <div className="relative py-2 pl-3 pr-2 border-b border-border/60 bg-muted/40 rounded">
        <div className="absolute left-0 top-2 bottom-2 w-0.5 bg-foreground rounded" />
        <div className="text-xs font-medium text-foreground mb-1.5 flex items-center gap-1.5">
          {label}<Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
        </div>
        {action ? <div className="text-[11px] text-muted-foreground mb-1.5">{action}</div> : null}
        <div className="space-y-1.5">
          <div className="h-3 rounded bg-muted-foreground/15 w-full" />
          <div className="h-3 rounded bg-muted-foreground/15 w-2/3" />
        </div>
      </div>
    );
  }
  if (state === "pending") {
    return (
      <div className="py-2 border-b border-border/60 opacity-35">
        <div className="text-xs text-muted-foreground mb-1 flex items-center">
          {label}{hint ? <InfoTip text={hint} /> : null}
        </div>
        <div className="text-sm text-muted-foreground">待生成</div>
      </div>
    );
  }
  return (
    <div className={`py-2 border-b border-border/60 ${justFilled ? "just-filled -mx-2 px-2 rounded" : ""}`}>
      <div className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
        <span className="text-success">✓</span>
        {label}{hint ? <InfoTip text={hint} /> : null}
        {justFilled ? <Badge variant="softblue" className="ml-auto">刚填入</Badge> : null}
      </div>
      {children}
    </div>
  );
}
const inputCls = "w-full border border-border rounded-md px-2 py-1 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring";

// SSE 启用方式（URL 参数；默认无参数 = 走现有 fetch JSON，行为不变）：
//   ?sse=mock —— MockEventSource 本地模拟，验证丝滑感（后端 SSE 未就绪时用）；
//   ?sse=real —— 真 EventSource 连 /api/stream，连不上自动回退 fetch。
const SSE_MODE =
  typeof URLSearchParams !== "undefined"
    ? new URLSearchParams(location.search).get("sse")
    : null;

// 空 card 骨架：SSE resolve_ticker 先到、card 还没建时，给 drawer 一个可点亮的壳。
function emptyCard(): CardT {
  return {
    card_id: "", ticker: "", filer_type: "other", holding_reason_raw: "",
    key_assumptions: [], broken_conditions: [], manual_check_items: [],
    entry_anchor: null, next_verdict: null, position_cap_tier: null,
    holding_horizon: null, confirmation: { confirmed_by_user: false },
  };
}

// ──────────────────────────── App ────────────────────────────
export default function App() {
  const [sid, setSid] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("opening");
  const [conv, setConv] = useState<Msg[]>([]);
  const [card, setCard] = useState<CardT | null>(null);
  const [menu, setMenu] = useState<MenuT | null>(null);
  const [openQs, setOpenQs] = useState<OpenQ[]>([]);
  const [tickerTitle, setTickerTitle] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [justFilled, setJustFilled] = useState<Set<string>>(new Set());
  const [picks, setPicks] = useState<{ a: number[]; b: number[] }>({ a: [], b: [] });
  const [edits, setEdits] = useState<Record<string, any>>({});
  const { streaming, toolStatus, start: startStream } = useStreamChat();
  const liveIdRef = useRef<number | null>(null);
  // 自动滚动由 MessageScroller 接管（stick-to-bottom + ResizeObserver，防流式跳动）

  // SSE tool_result → view patch → 状态。port 后端 _apply_tool_output（仅显示字段）。
  // 注意：generate_menu 的 tool_result 形状（candidate_assumptions/candidate_mirrors）与
  // App MenuT（assumptions/mirrors）不同——mock 不触发它，真后端联调时在此映射。
  function applyStreamPatch(p: ViewPatch) {
    if (p.ticker !== undefined) setCard((c) => ({ ...(c ?? emptyCard()), ticker: p.ticker! }));
    if (p.tickerTitle !== undefined) setTickerTitle(p.tickerTitle);
    if (p.card) setCard((c) => ({ ...p.card!, ticker: p.card!.ticker || c?.ticker || "" } as CardT));
    if (p.menu !== undefined) setMenu(p.menu as MenuT | null);
    if (p.openQuestions !== undefined) setOpenQs(p.openQuestions as OpenQ[]);
    if (p.sources !== undefined) setSources(p.sources as Source[]);
    if (p.stage !== undefined) setStage(p.stage as Stage);
  }

  function applyView(v: View, opts?: { newUserMsg?: Msg }) {
    setStage(v.stage);
    if (opts?.newUserMsg) setConv((c) => [...c, opts.newUserMsg!]);
    if (v.assistant) setConv((c) => [...c, { id: nextMid(), role: "assistant", text: v.assistant }]);
    setCard(v.card);
    setMenu(v.menu);
    setOpenQs(v.open_questions || []);
    setTickerTitle(v.ticker_title ?? null);
    setSources(v.sources ?? []);
    setError(v.error ? "⚠️ " + v.error : "");
    const byStage: Record<string, string> = {
      extracted: "抽取完成 · 确认或回「无法确定」要候选菜单",
      menu: "候选就绪 · 勾选后提交",
      confirm_card: "卡片已渲染 · 可点改字段，确认后入库",
      confirmed: "已落库 · 命中会单独邮件，未命中合并进简报",
    };
    setStatus(byStage[v.stage] || "");
    if (v.card && (v.stage === "extracted" || v.stage === "confirm_card")) {
      const jf = new Set<string>();
      if (v.card.holding_reason_raw) jf.add("holding_reason_raw");
      if (v.card.entry_anchor) jf.add("entry_anchor");
      if (v.card.next_verdict) jf.add("next_verdict");
      v.card.key_assumptions.forEach((a) => jf.add("assumption_" + a.id));
      v.card.broken_conditions.forEach((c) => jf.add("cond_" + c.id));
      setJustFilled(jf);
      setTimeout(() => setJustFilled(new Set()), 3000);
    }
  }

  async function start() {
    const text = (document.getElementById("f-input") as HTMLTextAreaElement).value.trim();
    if (!text) { setError("说一句标的 + 理由"); return; }
    const um: Msg = { id: nextMid(), role: "user", text };
    setConv((c) => [...c, um]);
    setError("");
    if (SSE_MODE) { startStreamed(text, "start"); return; }
    await startFetch(text);
  }

  async function startFetch(text: string) {
    setStatus("正在抽取…（5–45s）");
    try {
      const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: "beta1", text }) });
      const v: View = await r.json();
      if (!r.ok) { setError(`(${r.status}) ${v.error || JSON.stringify(v)}`); return; }
      setSid(v.session_id ?? null);
      applyView(v);
    } catch (e) { setError(String(e)); }
  }

  async function postTurn(payload: any, preStatus: string) {
    setStatus(preStatus); setError("");
    try {
      const r = await fetch(`/api/session/${sid}/turn`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const v: View = await r.json();
      if (!r.ok) { setError(`(${r.status}) ${v.error || JSON.stringify(v)}`); return; }
      applyView(v);
    } catch (e) { setError(String(e)); }
  }

  async function send() {
    const el = document.getElementById("f-msg") as HTMLTextAreaElement;
    const text = el.value.trim();
    if (!text) return;
    if (!SSE_MODE && !sid) return;
    el.value = "";
    const um: Msg = { id: nextMid(), role: "user", text };
    setConv((c) => [...c, um]);
    if (SSE_MODE) { startStreamed(text, "send"); return; }
    const pre = isUndecided(text) ? "正在生成候选…（5–45s）" : "处理中…";
    await postTurn({ text }, pre);
  }

  async function submitPicks() {
    if (!picks.a.length && !picks.b.length) { setError("至少勾一条"); return; }
    const um: Msg = { id: nextMid(), role: "user", text: `勾选 A${JSON.stringify(picks.a)} B${JSON.stringify(picks.b)}` };
    setConv((c) => [...c, um]);
    setPicks({ a: [], b: [] });
    await postTurn({ picks: { assumptions: picks.a, mirrors: picks.b } }, "正在渲染卡片…");
  }

  async function confirm() {
    if (!SSE_MODE && !sid) return;
    if (SSE_MODE) { startStreamed("", "confirm"); return; }
    await confirmFetch();
  }

  async function confirmFetch() {
    setStatus("正在入库…"); setError("");
    try {
      const r = await fetch(`/api/session/${sid}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits }) });
      const v: View = await r.json();
      if (!r.ok) { setError(`(${r.status}) ${v.error || JSON.stringify(v)}`); return; }
      setEdits({});
      applyView(v);
    } catch (e) { setError(String(e)); }
  }

  // SSE 流式：推一个空 assistant 流式气泡，逐 token 追加；tool_result 重建 card/menu/ticker；
  // done 收尾。连不上（无后端）→ onFallback 回退对应 fetch 路径（移除空气泡避免重复）。
  function startStreamed(text: string, kind: "start" | "send" | "confirm") {
    const aid = nextMid();
    liveIdRef.current = aid;
    setConv((c) => [...c, { id: aid, role: "assistant", text: "", streaming: true, streamed: true }]);
    setStatus(kind === "start" ? "正在抽取…" : kind === "confirm" ? "正在入库…" : "处理中…");
    startStream({
      userText: text, sid, kind,
      onToken: (t) => setConv((c) => c.map((m) => (m.id === aid ? { ...m, text: m.text + t } : m))),
      onToolCall: () => { /* toolStatus 由 hook 管，状态行渲染 */ },
      onToolResult: (tool, result) => applyStreamPatch(applyToolResult(tool, result)),
      onDone: () => {
        setConv((c) => c.map((m) => (m.id === aid ? { ...m, streaming: false } : m)));
        setStatus("");
        liveIdRef.current = null;
        if (kind === "confirm") setEdits({});
      },
      onFallback: () => {
        setConv((c) => c.filter((m) => m.id !== aid));
        liveIdRef.current = null;
        if (kind === "start") void startFetch(text);
        else if (kind === "send") void postTurn({ text }, isUndecided(text) ? "正在生成候选…（5–45s）" : "处理中…");
        else void confirmFetch();
      },
    });
  }

  function setEdit(path: string, val: any) { setEdits((e) => ({ ...e, [path]: val })); }
  function togglePick(kind: "a" | "b", i: number) {
    setPicks((p) => {
      const cur = p[kind];
      return { ...p, [kind]: cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i] };
    });
  }

  const drawerOpen = true;
  const confirmed = stage === "confirmed";
  const showStart = stage === "opening";

  // F2：字段逐格点亮。working=fetch 进行中→全字段 in-progress；否则 populated→done、空→pending。
  // SSE 流式时 working=false：字段随 tool_result 实时点亮（不再全格骨架），状态由 toolStatus 行表达。
  const working = !streaming && !!status && (status.includes("正在") || status.includes("处理中"));
  const rejectedAssumptions = openQs.filter((q) => q.field === "key_assumptions");
  const populated = card ? {
    ticker: !!card.ticker,
    holding_reason: !!card.holding_reason_raw,
    assumptions: card.key_assumptions.length > 0 || rejectedAssumptions.length > 0,
    broken: card.broken_conditions.length > 0,
    manual: (card.manual_check_items?.length ?? 0) > 0,
    anchor: !!card.entry_anchor,
    next_verdict: !!card.next_verdict,
    position_cap: !!card.position_cap_tier,
    horizon: !!card.holding_horizon,
  } : null;
  const doneCount = populated ? (Object.values(populated) as boolean[]).filter(Boolean).length : 0;
  const nDone = working ? 0 : doneCount;
  const actionText = working ? status : "";
  const fst = (p: boolean): FieldState => (working ? "in-progress" : p ? "done" : "pending");

  return (
    <TooltipProvider>
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="max-w-conv mx-auto px-4 py-2 flex items-baseline gap-3">
          <h1 className="text-base font-semibold">Thesis Watch</h1>
          <span className="text-xs text-muted-foreground">持仓条件核对 Agent · 录入（判断权永远归你）</span>
        </div>
      </header>

      <div className="flex">
        {/* 对话主流（居中单栏 ~680px） */}
        <main className={`flex-1 flex justify-center px-4 ${drawerOpen ? "pr-[360px]" : ""}`}>
          <div className="w-full max-w-conv py-4 flex flex-col" style={{ height: "calc(100vh - 49px)" }}>
            {showStart ? (
              <div className="flex-1 flex flex-col justify-center max-w-[620px] mx-auto w-full">
                <h2 className="text-xl font-semibold text-foreground mb-2">说说你为什么持有它</h2>
                <p className="text-sm text-muted-foreground mb-6 leading-relaxed">用一句话讲清楚买入逻辑，我会把它拆成可被财报击中的条件，以后每次披露更新，逐条替你核对是否还成立。</p>
                <div className="grid grid-cols-3 gap-3 mb-6">
                  {[{ n: 1, t: "你口述", d: "一句话，不用工整" }, { n: 2, t: "我追问", d: "补齐说不清的地方" }, { n: 3, t: "你确认", d: "右侧卡片逐格核对" }].map((s) => (
                    <div key={s.n} className="text-sm">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-5 h-5 rounded-full bg-foreground text-background text-xs flex items-center justify-center font-medium">{s.n}</span>
                        <span className="font-medium text-foreground">{s.t}</span>
                      </div>
                      <div className="text-xs text-muted-foreground pl-7">{s.d}</div>
                    </div>
                  ))}
                </div>
                <div className="text-xs text-muted-foreground mb-2">从一个例子开始</div>
                <div className="space-y-2 mb-6">
                  {[{ tag: "基本面", text: "我持有 MCO，因为评级双寡头的 moat 被 AI 恐慌错杀" }, { tag: "周期", text: "我持有 SK 海力士，AI 时代需要大量计算，计算需要存储" }, { tag: "价格形态", text: "HSBC 跌破 200 日线我就走" }].map((ex, i) => (
                    <button key={i} type="button" onClick={() => { const el = document.getElementById("f-input") as HTMLTextAreaElement; if (el) { el.value = ex.text; el.focus(); } }}
                      className="w-full text-left rounded-md border border-border bg-card px-3 py-2 hover:bg-muted transition">
                      <span className="text-[10px] text-muted-foreground mr-2">[{ex.tag}]</span>
                      <span className="text-sm text-foreground">{ex.text}</span>
                    </button>
                  ))}
                </div>
                <div className="relative">
                  <textarea id="f-input" placeholder="一句话说标的 + 理由" rows={3} className={`${inputCls} pr-12 resize-none`} />
                  <SendButton onClick={start} />
                </div>
                <div className="text-right text-[11px] text-muted-foreground/70 mt-1">Enter 发送 · Shift+Enter 换行</div>
                <div className="mt-6 pl-3 border-l-2 border-border/60">
                  <div className="text-xs text-muted-foreground leading-relaxed">不给买卖建议，不预测价格。</div>
                  <div className="text-xs text-muted-foreground leading-relaxed">所有结论必须附一手披露链接，查不到就说查不到。</div>
                </div>
              </div>
            ) : (
              <>
                <MessageScroller dep={conv} className="flex-1">
                  {conv.map((m) => (
                    <Message key={m.id} role={m.role === "assistant" ? "system" : "user"} sender={m.role === "assistant" ? "Thesis Watch" : undefined}>
                      {m.role === "assistant"
                        ? m.streamed
                          ? <LiveText text={m.text} streaming={m.streaming} />
                          : <Typewriter text={m.text} />
                        : m.text}
                    </Message>
                  ))}
                  {/* 流式状态：tool_call → "正在查询…"；token 流中 → "正在输入…" */}
                  {(streaming || toolStatus) && (
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground pl-1">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      {toolStatus ?? "正在输入…"}
                    </div>
                  )}
                  {/* 拒判降级橙边卡（验收点 4） */}
                  {card?.manual_check_items?.length ? <RefusalCard items={card.manual_check_items} /> : null}
                  {/* 菜单 option 卡（验收点 1） */}
                  {stage === "menu" && menu ? (
                    <div className="space-y-2 my-2">
                      <div className="text-xs text-muted-foreground">A 你信什么（点 tag 选中，可多选）</div>
                      <div className="flex flex-wrap gap-2">
                        {menu.assumptions.map((a, i) => (
                          <button key={i} type="button" onClick={() => togglePick("a", i)}
                            className={`rounded-full border px-3 py-1 text-sm transition ${picks.a.includes(i) ? "border-foreground bg-foreground text-background" : "border-border bg-card text-foreground hover:bg-muted"}`}>
                            {a}
                          </button>
                        ))}
                      </div>
                      <div className="text-xs text-muted-foreground mt-2">B 破的条件（点 tag 选中，每条我能从公告核对）</div>
                      <div className="flex flex-wrap gap-2">
                        {menu.mirrors.map((b, i) => (
                          <button key={i} type="button" onClick={() => togglePick("b", i)}
                            className={`rounded-full border px-3 py-1 text-sm text-left transition ${picks.b.includes(i) ? "border-foreground bg-foreground text-background" : "border-border bg-card text-foreground hover:bg-muted"}`}>
                            <span>{b.mirror_text}</span>
                            <span className="block text-xs opacity-70">对应：{b.assumption}</span>
                          </button>
                        ))}
                      </div>
                      <Button size="sm" onClick={submitPicks}>提交勾选</Button>
                      {menu.coverage?.excluded ? (
                        <div className="text-[11px] text-muted-foreground border-t border-border/40 pt-2 mt-2 space-y-0.5">
                          <div>已排除 {menu.coverage.excluded} 个方向（共 {menu.coverage.total}）：</div>
                          {menu.coverage.excluded_items?.map((it, i) => (
                            <div key={i}>· {it.mirror_text} — {it.reasons?.join("、")}</div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {sources.length ? (
                    <div className="my-2 rounded-md border border-border bg-card px-3 py-2 text-xs">
                      <div className="border-b border-border/40 pb-1 mb-1 text-[11px] text-muted-foreground">来源</div>
                      {sources.map((s, i) => (
                        <a key={i} href={s.url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 py-0.5 hover:underline">
                          <span className="w-1.5 h-1.5 rounded-full bg-success shrink-0" />
                          <span className="text-muted-foreground">{s.form} · {s.date}</span>
                          {s.note ? <span className="text-muted-foreground/70">— {s.note}</span> : null}
                        </a>
                      ))}
                    </div>
                  ) : null}
                </MessageScroller>

                {error ? <div className="text-xs text-red-600 py-1">{error}</div> : null}

                <div className="border-t border-border pt-3">
                  <div className="relative">
                    <textarea id="f-msg" placeholder='回复（如「确认」或「无法确定」要候选菜单）' rows={2}
                      className={`${inputCls} pr-12 resize-none`}
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
                    <SendButton onClick={send} disabled={stage !== "extracted" && stage !== "confirm_card"} />
                  </div>
                  <div className="text-right text-[11px] text-muted-foreground/70 mt-1">Enter 发送 · Shift+Enter 换行</div>
                </div>
              </>
            )}
          </div>
        </main>

        {/* 确认卡抽屉（右侧 ~340px，滑入/滑出，验收点 3） */}
        <aside className={`fixed right-0 top-[49px] h-[calc(100vh-49px)] w-full max-w-drawer bg-card border-l border-border shadow-lg transition-drawer ${drawerOpen ? "drawer-enter" : "drawer-exit"} overflow-y-auto`}>
          <div className="p-4">
            <div className="flex items-center mb-2">
              <h2 className="text-sm font-semibold text-muted-foreground">确认卡 <span className="text-xs font-normal">（字段可点改）</span></h2>
              <div className="ml-auto flex items-center gap-2">
                <span className="text-xs text-muted-foreground tabular-nums">{nDone} / 9 字段</span>
                <div className="h-1 w-[76px] rounded-full bg-muted overflow-hidden">
                  <div className="h-full bg-foreground transition-all" style={{ width: `${(nDone / 9) * 100}%` }} />
                </div>
              </div>
            </div>
            {card ? (
              <>
                <DrawerField label="标的（ticker）" hint="抽错了在这里改，确认时按新 ticker 重查 filer_type / 仓位档" state={fst(populated.ticker)} action={actionText}>
                  <div className="space-y-1">
                    <input className={inputCls} defaultValue={card.ticker} onChange={(e) => setEdit("ticker", e.target.value)} />
                    <div className="flex items-center gap-2">
                      {tickerTitle ? <span className="text-xs text-muted-foreground truncate">{tickerTitle}</span> : <span className="text-xs text-muted-foreground/60">（公司全名待 resolve）</span>}
                      <Badge variant="success" className="shrink-0 ml-auto">✓ 一手核对</Badge>
                    </div>
                  </div>
                </DrawerField>
                <DrawerField label="买入逻辑（原话）" justFilled={justFilled.has("holding_reason_raw")} state={fst(populated.holding_reason)} action={actionText}>
                  <textarea className={inputCls} rows={3} defaultValue={card.holding_reason_raw}
                    onChange={(e) => setEdit("holding_reason_raw", e.target.value)} />
                </DrawerField>

                <DrawerField label="关键假设" state={fst(populated.assumptions)} action={actionText}>
                  <div className="text-sm space-y-1.5">
                    {card.key_assumptions.map((a) => (
                      <textarea key={a.id} rows={2} placeholder="假设文本"
                        className={`${inputCls} resize-none ${justFilled.has("assumption_" + a.id) ? "just-filled" : ""}`}
                        defaultValue={a.text}
                        onChange={(e) => setEdit("assumption." + a.id + ".text", e.target.value)} />
                    ))}
                  </div>
                  {rejectedAssumptions.length ? (
                    <div className="mt-2 text-[11px] text-muted-foreground border-t border-border/40 pt-1.5 space-y-0.5">
                      <div>{rejectedAssumptions.length} 条候选未通过：</div>
                      {rejectedAssumptions.map((q, i) => (
                        <div key={i}>「{q.text || "—"}」→ {q.reason}</div>
                      ))}
                    </div>
                  ) : null}
                </DrawerField>

                <DrawerField label="破局条件（两层）" state={fst(populated.broken)} action={actionText}>
                  <div className="text-sm space-y-2">
                    {card.broken_conditions.map((c) => {
                      const thr = c.threshold || {};
                      const thrKeys = Object.keys(thr);
                      return (
                        <div key={c.id} className={justFilled.has("cond_" + c.id) ? "just-filled rounded px-1" : ""}>
                          <div className="flex items-start gap-1.5">
                            <Badge variant={c.layer === "mirror" ? "softblue" : "amber"} className="shrink-0 mt-1">{c.layer === "mirror" ? "M" : "R"}</Badge>
                            <textarea rows={2} className={`${inputCls} resize-none flex-1`} defaultValue={c.text}
                              onChange={(e) => setEdit("cond." + c.id + ".text", e.target.value)} />
                          </div>
                          {thrKeys.length ? (
                            <div className="mt-1 flex items-center gap-1.5 flex-wrap pl-5">
                              <span className="text-[11px] text-muted-foreground">阈值</span>
                              {thrKeys.map((k) => (
                                <label key={k} className="flex items-center gap-0.5">
                                  <span className="text-[10px] text-muted-foreground/70">{k}</span>
                                  <input className={`${inputCls} py-0.5 px-1 text-xs w-24`} defaultValue={String(thr[k] ?? "")}
                                    onChange={(e) => setEdit("cond." + c.id + ".threshold." + k, e.target.value)} />
                                </label>
                              ))}
                            </div>
                          ) : null}
                          <div className="mt-1 flex items-center gap-1.5 pl-5">
                            <span className="text-[11px] text-muted-foreground shrink-0">数据源</span>
                            <input className={`${inputCls} py-0.5 px-1 text-xs`} defaultValue={c.source_type || ""}
                              onChange={(e) => setEdit("cond." + c.id + ".source_type", e.target.value)} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </DrawerField>

                {card.manual_check_items?.length ? (
                  <DrawerField label="人工自查项（每月）" state={fst(populated.manual)} action={actionText}>
                    <div className="text-sm">{card.manual_check_items.map((m) => <div key={m.id}>• {m.text}</div>)}</div>
                  </DrawerField>
                ) : null}

                <DrawerField label="录入估值锚" hint="锚型是估值口径（怎么算这个倍数的）；有数据必须显示，无数据显示未检出" justFilled={justFilled.has("entry_anchor")} state={fst(populated.anchor)} action={actionText}>
                  {card.entry_anchor ? (
                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">
                        方法：<b>{ANCHOR_CN[card.entry_anchor.anchor_type] || card.entry_anchor.anchor_type || "—"}</b>
                        {card.entry_anchor.anchor_value != null ? <>　当前读数：<b>{card.entry_anchor.anchor_value}</b>{card.entry_anchor.note ? <span className="text-muted-foreground">（{card.entry_anchor.note}）</span> : null}</> : null}
                      </div>
                      <div className="flex gap-1 flex-wrap">
                        <select className={inputCls} defaultValue={card.entry_anchor.anchor_type} onChange={(e) => setEdit("entry_anchor.anchor_type", e.target.value)}>
                          {ANCHOR_TYPES.map((t) => <option key={t} value={t}>{ANCHOR_CN[t] || t}</option>)}
                        </select>
                        <input type="number" step="0.1" className={`${inputCls} w-20`} defaultValue={card.entry_anchor.anchor_value ?? ""} placeholder="倍数" onChange={(e) => setEdit("entry_anchor.anchor_value", e.target.value ? parseFloat(e.target.value) : null)} />
                        <input className={inputCls} defaultValue={card.entry_anchor.note} placeholder="补充" onChange={(e) => setEdit("entry_anchor.note", e.target.value)} />
                      </div>
                      {/* history 折叠（v0.1 单读数；多时点 history 见 schema §5，待后端落地） */}
                      <details className="text-xs text-muted-foreground">
                        <summary>历史读数</summary>
                        <div className="pl-3">（v0.1 仅当前读数；多时点 history 见 schema §5，待后端落地）</div>
                      </details>
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">未检出（文本含加仓价 / 安全边际时自动抽取）</div>
                  )}
                </DrawerField>

                {card.next_verdict ? (
                  <DrawerField label="下次裁判日" hint="下一个能证伪 thesis 的事件（不等于复盘日）" justFilled={justFilled.has("next_verdict")} state={fst(!!card.next_verdict)} action={actionText}>
                    <div className="flex gap-1">
                      <input className={inputCls} defaultValue={card.next_verdict.event} placeholder="事件" onChange={(e) => setEdit("next_verdict.event", e.target.value)} />
                      <input className={inputCls} defaultValue={card.next_verdict.date ?? ""} placeholder="YYYY-MM" onChange={(e) => setEdit("next_verdict.date", e.target.value)} />
                    </div>
                  </DrawerField>
                ) : null}

                <DrawerField label="仓位上限档" hint={TIER_NOTE} state={fst(!!card.position_cap_tier)} action={actionText}>
                  <div className="text-sm font-semibold">{card.position_cap_tier || "—（查表无，待确认）"}{card.position_cap_tier ? <span className="text-xs text-muted-foreground ml-1">（柔性上限）</span> : null}</div>
                </DrawerField>

                <DrawerField label="持仓周期" hint="必须由你确认（不模型猜）；影响 mirror 阈值时间尺度：long→季频 / mid→季报 / trade→日频或 trailing stop" state={fst(populated.horizon)} action={actionText}>
                  <select className={inputCls} defaultValue={card.holding_horizon ?? ""} onChange={(e) => setEdit("holding_horizon", e.target.value)}>
                    <option value="">— 待你确认 —</option>
                    <option value="long">long（≥3y，noise 阈值最高）</option>
                    <option value="mid">mid（3m-3y，看 thesis + 季报，不止损）</option>
                    <option value="trade">trade（≤3m，可用 trailing stop）</option>
                  </select>
                </DrawerField>

                {openQs.length ? <div className="text-xs text-amber bg-amber-soft rounded p-2 my-2">⚠️ {openQs.map((q) => q.reason).join(" / ")}</div> : null}

                <div className="pt-3">
                  {confirmed ? (
                    <Badge variant="success" className="text-sm px-3 py-1">✓ 已入库</Badge>
                  ) : stage === "confirm_card" || stage === "extracted" ? (
                    <Button onClick={confirm} className="w-full">确认入库</Button>
                  ) : null}
                </div>
              </>
            ) : (
              <>
                <DrawerField label="标的（ticker）" state="pending" />
                <DrawerField label="买入逻辑（原话）" state="pending" />
                <DrawerField label="关键假设" state="pending" />
                <DrawerField label="破局条件（两层）" state="pending" />
                <DrawerField label="人工自查项（每月）" state="pending" />
                <DrawerField label="录入估值锚" state="pending" />
                <DrawerField label="下次裁判日" state="pending" />
                <DrawerField label="仓位上限档" state="pending" />
                <DrawerField label="持仓周期" state="pending" />
                <div className="text-xs text-muted-foreground mt-3">卡片会随对话逐格填充，确认后才入库</div>
                <div className="pt-3">
                  <Button className="w-full" disabled>确认入库</Button>
                </div>
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
    </TooltipProvider>
  );
}
