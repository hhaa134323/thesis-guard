import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { InfoTip, TooltipProvider } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";

// ──────────────────────────────── types ────────────────────────────────
type Stage = "opening" | "extracted" | "menu" | "confirm_card" | "confirmed";
interface Evidence { url: string; excerpt: string; }
interface Cond { id: string; layer: "mirror" | "redline"; text: string; threshold?: any; template?: string | null; }
interface Assumption { id: string; text: string; }
interface ManualItem { id: string; text: string; reason: string; cadence: string; }
interface Anchor { anchor_type: string; anchor_value: number | null; note: string; }
interface NextVerdict { event: string; date: string | null; source_note: string; }
interface CardT {
  card_id: string; ticker: string; filer_type: string; holding_reason_raw: string;
  key_assumptions: Assumption[]; broken_conditions: Cond[]; manual_check_items: ManualItem[];
  entry_anchor: Anchor | null; next_verdict: NextVerdict | null; position_cap_tier: string | null;
  confirmation: { confirmed_by_user: boolean };
}
interface MenuT { assumptions: string[]; mirrors: { assumption: string; mirror_text: string }[]; }
interface View {
  stage: Stage; assistant: string; card: CardT | null; menu: MenuT | null;
  open_questions: { field: string; reason: string }[]; ticker: string; error: string | null;
  metrics?: { turns: number; clarification_rounds: number; converged: boolean };
  session_id?: string;
}
interface Msg { id: number; role: "user" | "assistant"; text: string; }

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

// ──────────────────────────── 三阶段进度行（验收点 2） ────────────────────────────
function ProgressRow({ status }: { status: string }) {
  const stages = [
    { key: "extract", label: "已抽取", dot: "bg-muted-foreground/40" },
    { key: "menu", label: "正在生成候选", dot: "bg-primary" },
    { key: "render", label: "正在更新卡片", dot: "bg-primary" },
  ];
  const active = status.includes("抽取") ? 0 : status.includes("生成候选") ? 1 : status.includes("渲染") || status.includes("更新") ? 2 : -1;
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground py-1">
      {stages.map((s, i) => (
        <span key={s.key} className="flex items-center gap-1">
          <span className={`inline-block w-2 h-2 rounded-full ${i <= active && active >= 0 ? s.dot : "bg-muted-foreground/20"}`} />
          {s.label}{i < stages.length - 1 ? <span className="mx-1 opacity-40">→</span> : null}
        </span>
      ))}
    </div>
  );
}

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

// ──────────────────────────── 抽屉字段（验收点 3/5/6） ────────────────────────────
function DrawerField({ label, hint, justFilled, children }: { label: string; hint?: string; justFilled?: boolean; children: ReactNode }) {
  return (
    <div className={`py-2 border-b border-border/60 ${justFilled ? "just-filled -mx-2 px-2 rounded" : ""}`}>
      <div className="text-xs text-muted-foreground mb-1 flex items-center">
        {label}{hint ? <InfoTip text={hint} /> : null}
        {justFilled ? <Badge variant="softblue" className="ml-auto">刚填入</Badge> : null}
      </div>
      {children}
    </div>
  );
}
const inputCls = "w-full border border-border rounded-md px-2 py-1 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring";

// ──────────────────────────── App ────────────────────────────
export default function App() {
  const [sid, setSid] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("opening");
  const [conv, setConv] = useState<Msg[]>([]);
  const [card, setCard] = useState<CardT | null>(null);
  const [menu, setMenu] = useState<MenuT | null>(null);
  const [openQs, setOpenQs] = useState<{ field: string; reason: string }[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [justFilled, setJustFilled] = useState<Set<string>>(new Set());
  const [picks, setPicks] = useState<{ a: number[]; b: number[] }>({ a: [], b: [] });
  const [edits, setEdits] = useState<Record<string, any>>({});
  const convRef = useRef<HTMLDivElement>(null);

  // 自动滚到底
  useEffect(() => { convRef.current?.scrollTo({ top: convRef.current.scrollHeight, behavior: "smooth" }); }, [conv]);

  function applyView(v: View, opts?: { newUserMsg?: Msg }) {
    setStage(v.stage);
    if (opts?.newUserMsg) setConv((c) => [...c, opts.newUserMsg!]);
    if (v.assistant) setConv((c) => [...c, { id: nextMid(), role: "assistant", text: v.assistant }]);
    setCard(v.card);
    setMenu(v.menu);
    setOpenQs(v.open_questions || []);
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
    setStatus("正在抽取…（5–45s）");
    setError("");
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
    if (!text || !sid) return;
    el.value = "";
    const um: Msg = { id: nextMid(), role: "user", text };
    setConv((c) => [...c, um]);
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
    if (!sid) return;
    setStatus("正在入库…"); setError("");
    try {
      const r = await fetch(`/api/session/${sid}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits }) });
      const v: View = await r.json();
      if (!r.ok) { setError(`(${r.status}) ${v.error || JSON.stringify(v)}`); return; }
      setEdits({});
      applyView(v);
    } catch (e) { setError(String(e)); }
  }

  function setEdit(path: string, val: any) { setEdits((e) => ({ ...e, [path]: val })); }
  function togglePick(kind: "a" | "b", i: number) {
    setPicks((p) => {
      const cur = p[kind];
      return { ...p, [kind]: cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i] };
    });
  }

  const drawerOpen = !!card && stage !== "opening";
  const confirmed = stage === "confirmed";
  const showStart = stage === "opening";

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
            <div ref={convRef} className="flex-1 overflow-y-auto space-y-3 pr-1">
              {conv.map((m) => (
                <div key={m.id} className={`rounded-lg px-3 py-2 max-w-[92%] whitespace-pre-wrap break-words text-sm ${m.role === "user" ? "bg-softblue ml-auto" : "bg-muted mr-auto"}`}>
                  {m.role === "assistant" ? <Typewriter text={m.text} /> : m.text}
                </div>
              ))}
              {/* 拒判降级橙边卡（验收点 4） */}
              {card?.manual_check_items?.length ? <RefusalCard items={card.manual_check_items} /> : null}
              {/* 菜单 option 卡（验收点 1） */}
              {stage === "menu" && menu ? (
                <div className="space-y-2 my-2">
                  <div className="text-xs text-muted-foreground">A 你信什么（可多选，勾选实时同步右侧抽屉）</div>
                  {menu.assumptions.map((a, i) => (
                    <label key={i} className={`flex items-start gap-2 p-2 rounded-md border cursor-pointer ${picks.a.includes(i) ? "border-primary bg-softblue" : "border-border"}`}>
                      <Checkbox checked={picks.a.includes(i)} onCheckedChange={() => togglePick("a", i)} className="mt-0.5" />
                      <span className="text-sm">{a}</span>
                    </label>
                  ))}
                  <div className="text-xs text-muted-foreground mt-2">B 破的条件（勾几条，每条我能从公告核对）</div>
                  {menu.mirrors.map((b, i) => (
                    <label key={i} className={`flex items-start gap-2 p-2 rounded-md border cursor-pointer ${picks.b.includes(i) ? "border-primary bg-softblue" : "border-border"}`}>
                      <Checkbox checked={picks.b.includes(i)} onCheckedChange={() => togglePick("b", i)} className="mt-0.5" />
                      <span className="text-sm"><span>{b.mirror_text}</span><span className="block text-xs text-muted-foreground">对应：{b.assumption}</span></span>
                    </label>
                  ))}
                  <Button size="sm" onClick={submitPicks}>提交勾选</Button>
                </div>
              ) : null}
            </div>

            <ProgressRow status={status} />
            {error ? <div className="text-xs text-red-600 py-1">{error}</div> : null}

            {showStart ? (
              <div className="space-y-2 border-t border-border pt-3">
                <textarea id="f-input" placeholder={'一句话说标的 + 理由，如「我持有 MCO，因为评级双寡头的 moat 被 AI 恐慌错杀」'} rows={3} className={inputCls} />
                <Button onClick={start}>开始录入</Button>
              </div>
            ) : (
              <div className="space-y-2 border-t border-border pt-3 flex gap-2">
                <textarea id="f-msg" placeholder='回复（如「确认」或「无法确定」要候选菜单）' rows={2} className={inputCls} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
                <Button onClick={send} disabled={stage !== "extracted" && stage !== "confirm_card"}>发送</Button>
              </div>
            )}
          </div>
        </main>

        {/* 确认卡抽屉（右侧 ~340px，滑入/滑出，验收点 3） */}
        <aside className={`fixed right-0 top-[49px] h-[calc(100vh-49px)] w-full max-w-drawer bg-card border-l border-border shadow-lg transition-drawer ${drawerOpen ? "drawer-enter" : "drawer-exit"} overflow-y-auto`}>
          <div className="p-4">
            <h2 className="text-sm font-semibold mb-2 text-muted-foreground">确认卡 <span className="text-xs">（字段可点改）</span></h2>
            {card ? (
              <>
                <DrawerField label="标的（ticker）" hint="抽错了在这里改，确认时按新 ticker 重查 filer_type / 仓位档">
                  <input className={inputCls} defaultValue={card.ticker} onChange={(e) => setEdit("ticker", e.target.value)} />
                </DrawerField>
                <DrawerField label="买入逻辑（原话）" justFilled={justFilled.has("holding_reason_raw")}>
                  <textarea className={inputCls} rows={3} defaultValue={card.holding_reason_raw}
                    onChange={(e) => setEdit("holding_reason_raw", e.target.value)} />
                </DrawerField>

                <DrawerField label="关键假设">
                  <div className="text-sm space-y-1">
                    {card.key_assumptions.map((a) => <div key={a.id} className={justFilled.has("assumption_" + a.id) ? "just-filled rounded px-1" : ""}>{a.text}</div>)}
                  </div>
                </DrawerField>

                <DrawerField label="破局条件（两层）">
                  <div className="text-sm space-y-1">
                    {card.broken_conditions.map((c) => (
                      <div key={c.id} className={justFilled.has("cond_" + c.id) ? "just-filled rounded px-1" : ""}>
                        <Badge variant={c.layer === "mirror" ? "softblue" : "amber"}>{c.layer === "mirror" ? "镜像" : "红线"}</Badge> {c.text}
                        {c.threshold?.amount_usd ? <span className="text-xs text-muted-foreground">（≥ {c.threshold.amount_usd} 美元）</span> : null}
                      </div>
                    ))}
                  </div>
                </DrawerField>

                {card.manual_check_items?.length ? (
                  <DrawerField label="人工自查项（每月）">
                    <div className="text-sm">{card.manual_check_items.map((m) => <div key={m.id}>• {m.text}</div>)}</div>
                  </DrawerField>
                ) : null}

                {card.entry_anchor ? (
                  <DrawerField label="录入估值锚" hint="锚型是估值口径（怎么算这个倍数的）" justFilled={justFilled.has("entry_anchor")}>
                    <div className="flex gap-1 flex-wrap">
                      <select className={inputCls} defaultValue={card.entry_anchor.anchor_type} onChange={(e) => setEdit("entry_anchor.anchor_type", e.target.value)}>
                        {ANCHOR_TYPES.map((t) => <option key={t} value={t}>{ANCHOR_CN[t] || t}</option>)}
                      </select>
                      <input type="number" step="0.1" className={`${inputCls} w-20`} defaultValue={card.entry_anchor.anchor_value ?? ""} placeholder="倍数" onChange={(e) => setEdit("entry_anchor.anchor_value", e.target.value ? parseFloat(e.target.value) : null)} />
                      <input className={inputCls} defaultValue={card.entry_anchor.note} placeholder="补充" onChange={(e) => setEdit("entry_anchor.note", e.target.value)} />
                    </div>
                  </DrawerField>
                ) : null}

                {card.next_verdict ? (
                  <DrawerField label="下次裁判日" hint="下一个能证伪 thesis 的事件（不等于复盘日）" justFilled={justFilled.has("next_verdict")}>
                    <div className="flex gap-1">
                      <input className={inputCls} defaultValue={card.next_verdict.event} placeholder="事件" onChange={(e) => setEdit("next_verdict.event", e.target.value)} />
                      <input className={inputCls} defaultValue={card.next_verdict.date ?? ""} placeholder="YYYY-MM" onChange={(e) => setEdit("next_verdict.date", e.target.value)} />
                    </div>
                  </DrawerField>
                ) : null}

                <DrawerField label="仓位上限档" hint={TIER_NOTE}>
                  <div className="text-sm font-semibold">{card.position_cap_tier || "—（查表无，待确认）"}{card.position_cap_tier ? <span className="text-xs text-muted-foreground ml-1">（柔性上限）</span> : null}</div>
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
              <div className="text-sm text-muted-foreground mt-8 text-center">（开始录入后这里实时渲染确认卡）</div>
            )}
          </div>
        </aside>
      </div>
    </div>
    </TooltipProvider>
  );
}
