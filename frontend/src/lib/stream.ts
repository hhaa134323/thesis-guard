// SSE 流式消费（Phase 3）。
//
// 事件格式（作者给定，待后端联调）：
//   event: token        data: {"text": "..."}
//   event: tool_call    data: {"tool": "resolve_ticker", "args": {...}}
//   event: tool_result  data: {"tool": "resolve_ticker", "result": {...}}
//   event: done         data: {}
//
// 后端 SSE endpoint 尚未落地（serve.py 仍为同步 JSON）。本模块提供：
//   1) connectStream()    —— 真 EventSource 消费（?sse=real 启用；连不上自动回退 fetch）；
//   2) MockEventSource    —— 本地模拟事件流（?sse=mock 启用；验证丝滑感。
//        frontend-design §8 明确允许「客户端逐字渲染，本地模拟即可，SSE 亦可」）；
//   3) applyToolResult()  —— 客户端从 tool_result 重建 view 字段
//        （port 后端 entry_loop.EntrySession._apply_tool_output，仅显示可派生字段）。
//
// 默认（无 ?sse= 参数）App 走现有 fetch JSON 路径，行为不变。

// ────────────────────────────── 事件类型 ──────────────────────────────
export type StreamEvent =
  | { type: "token"; text: string }
  | { type: "tool_call"; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; tool: string; result: Record<string, unknown> }
  | { type: "done" };

export interface StreamCallbacks {
  onToken: (text: string) => void;
  onToolCall: (tool: string, args: Record<string, unknown>) => void;
  onToolResult: (tool: string, result: Record<string, unknown>) => void;
  onDone: () => void;
  /** 后端 stream_run 异常（event: error）→ 透出消息，App 亮错误条；后端紧接 done。 */
  onError?: (message: string) => void;
  /** 连接从未建起来（404 / 无后端）→ 调用方可回退 fetch。mid-stream 中断不触发。 */
  onFallback: (reason: string) => void;
}

// ──────────────────────────── StreamSource 抽象 ────────────────────────────
// 真 EventSource 与 MockEventSource 都满足此接口，connectStream 不区分。
export interface StreamSource {
  addEventListener(type: string, listener: (ev: { data: string | null }) => void): void;
  close(): void;
  onerror?: ((ev: Event) => void) | null;
}

function parseData(raw: string | null): Record<string, any> {
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Record<string, any>;
  } catch {
    return { raw };
  }
}

const KNOWN = ["token", "tool_call", "tool_result", "done", "error"];

/**
 * 把一个已连接的 source 接到 callbacks。返回 close()。
 * 命名事件（event: token / tool_call / tool_result / done）优先；无名 message 事件
 * 按 data.type 派发（兼容把所有事件塞 message 的后端）。连接未建立即 onerror → onFallback。
 */
export function connectStream(source: StreamSource, cb: StreamCallbacks): () => void {
  let received = false;
  let closed = false;

  const close = () => {
    if (closed) return;
    closed = true;
    try {
      source.close();
    } catch {
      /* noop */
    }
  };

  const handle = (name: string, data: Record<string, any>) => {
    if (closed) return;
    received = true;
    switch (name) {
      case "token":
        cb.onToken(String(data?.text ?? ""));
        break;
      case "tool_call":
        cb.onToolCall(String(data?.tool ?? ""), (data?.args as Record<string, unknown>) || {});
        break;
      case "tool_result":
        cb.onToolResult(
          String(data?.tool ?? ""),
          (data?.result as Record<string, unknown>) || {},
        );
        break;
      case "error":
        cb.onError?.(String(data?.message ?? "后端出错"));
        break;
      case "done":
        cb.onDone();
        close();
        break;
      default:
        break;
    }
  };

  for (const name of KNOWN) {
    source.addEventListener(name, (ev) => handle(name, parseData(ev.data)));
  }
  // 兜底：无名 message 事件按 data.type 派发；缺省视为 token（部分后端只流文本）
  source.addEventListener("message", (ev) => {
    const d = parseData(ev.data);
    const t = typeof d?.type === "string" && KNOWN.includes(d.type) ? d.type : "token";
    handle(t, d);
  });

  source.onerror = () => {
    if (!received) cb.onFallback("sse_connect_failed");
    close();
  };

  return close;
}

// ──────────────────────────── MockEventSource ────────────────────────────
// 本地模拟：按 script 依次在 delayMs 后 emit (event, data)。验证丝滑感用，不连后端。
export interface MockItem {
  event: "token" | "tool_call" | "tool_result" | "done";
  data: Record<string, any>;
  delayMs: number;
}

type MockListener = (ev: { data: string }) => void;

export class MockEventSource implements StreamSource {
  private listeners: Record<string, MockListener[]> = {};
  private timers: ReturnType<typeof setTimeout>[] = [];
  private closed = false;
  public onerror: ((ev: Event) => void) | null = null;
  public readonly readyState = 1; // OPEN

  constructor(script: MockItem[]) {
    // 延迟一拍开始 emit，确保调用方 new 之后同步挂的 listener 已就位
    let t = 30;
    for (const item of script) {
      t += item.delayMs;
      const id = setTimeout(() => {
        if (this.closed) return;
        this.emit(item.event, item.data);
      }, t);
      this.timers.push(id);
    }
  }

  private emit(name: string, data: Record<string, any>) {
    const json = JSON.stringify(data);
    const ev = { data: json };
    for (const cb of this.listeners[name] || []) cb(ev);
    // 命名事件不触发 message；message 仅给无名后端兜底，mock 不走
    if (name === "done") {
      // done 后自然结束，不动 close（connectStream 的 onDone 会 close）
    }
  }

  addEventListener(type: string, cb: MockListener): void {
    (this.listeners[type] ||= []).push(cb);
  }

  removeEventListener(type: string, cb: MockListener): void {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== cb);
  }

  close(): void {
    this.closed = true;
    for (const id of this.timers) clearTimeout(id);
    this.timers = [];
  }
}

// ──────────────────────────── FetchStreamSource ────────────────────────────
// 真 SSE 消费：后端 /api/session/{sid}/stream 是 POST（EventSource 只能 GET），
// 故用 fetch + ReadableStream 读 SSE 帧，按 event: 名派发到 listener（与 EventSource 等价）。
// 首帧前 fetch 失败（404 / 网络错 / 无后端）→ onerror → connectStream 走 onFallback 回退 fetch；
// mid-stream 中断也 onerror，但 received 已 true → 不回退，仅 close（与 EventSource 一致）。
export class FetchStreamSource implements StreamSource {
  private listeners: Record<string, MockListener[]> = {};
  private controller: AbortController | null = null;
  private closed = false;
  private doneSeen = false; // 后端是否发过 event: done
  private anyFrame = false; // 是否收过任一帧（区分「连不上」vs「mid-stream 断」）
  public onerror: ((ev: Event) => void) | null = null;

  constructor(url: string, init: RequestInit) {
    // 异步起跑：构造同步返回，确保 connectStream 挂好 listener 后才发首帧。
    void this._start(url, init);
  }

  private async _start(url: string, init: RequestInit): Promise<void> {
    this.controller = new AbortController();
    try {
      const res = await fetch(url, { ...init, signal: this.controller.signal });
      if (!res.ok || !res.body) {
        if (!this.closed) this.onerror?.(new Event("error"));
        return;
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          this._dispatch(frame);
        }
      }
      if (buf.trim()) this._dispatch(buf);
      this._finish();
    } catch {
      this._finish();
    }
  }

  /** 解析一帧 SSE：event: <name> + data: <json>（多行 data 拼接），按名派发到 listener。 */
  private _dispatch(frame: string): void {
    let event = "message";
    const dataLines: string[] = [];
    for (const raw of frame.split("\n")) {
      const line = raw.replace(/^﻿/, "");
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    const data = dataLines.join("\n");
    if (event === "done") this.doneSeen = true;
    this.anyFrame = true;
    for (const cb of this.listeners[event] || []) cb({ data });
  }

  addEventListener(type: string, cb: MockListener): void {
    (this.listeners[type] ||= []).push(cb);
  }

  removeEventListener(type: string, cb: MockListener): void {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== cb);
  }

  /** 流结束/中断但没收到 done 帧（后端 mid-stream 崩溃 / 连接断）→ 透 error+done 给
   * connectStream 清 streaming + 亮错误条。一帧没收的失败（fetch 错 / !res.ok）→ 走
   * onerror，由 connectStream 触发 onFallback 回退 fetch（task item 1「不稳定」处理）。 */
  private _finish(): void {
    if (this.closed || this.doneSeen) return;
    if (!this.anyFrame) {
      if (!this.closed) this.onerror?.(new Event("error"));
      return;
    }
    this.doneSeen = true;
    for (const cb of this.listeners["error"] || [])
      cb({ data: JSON.stringify({ message: "流式中断（后端未正常结束）" }) });
    for (const cb of this.listeners["done"] || []) cb({ data: "{}" });
  }

  close(): void {
    this.closed = true;
    try {
      this.controller?.abort();
    } catch {
      /* noop */
    }
  }
}

// ─────────────────────── tool_result → view patch（port _apply_tool_output） ───────────────────────
// 后端 entry_loop._apply_tool_output 从 tool 输出派生 view 字段；SSE 下客户端重建。
// 仅派生显示可定的字段（ticker/title/card 草稿/menu/sources/stored/stage）。
// 注意：extract_card 的 tool_result 是原始抽取（非 build_card_draft 后的完整卡，
// 缺 redline 默认包 / 仓位档 / tier），故 buildDisplayCard 只建显示骨架，redline 默认包
// 等后端侧逻辑不复制。联调时若后端 SSE 发更 rich 的 result 或 done 带 view，可再补。
export interface ViewPatch {
  ticker?: string;
  tickerTitle?: string | null;
  card?: Record<string, any> | null;
  menu?: Record<string, any> | null;
  openQuestions?: any[];
  sources?: any[];
  stored?: boolean;
  cardId?: string;
  stage?: string;
}

export function applyToolResult(
  tool: string,
  result: Record<string, any>,
): ViewPatch {
  const patch: ViewPatch = {};
  if (tool === "resolve_ticker") {
    if (result?.found) {
      if (result.ticker) patch.ticker = String(result.ticker);
      patch.tickerTitle = result.title ? String(result.title) : null;
      patch.stage = "extracted";
    }
  } else if (tool === "extract_card") {
    if (result?.ok === false) return patch;
    patch.card = buildDisplayCard(result);
    patch.openQuestions = Array.isArray(result?.open_questions)
      ? result.open_questions
      : [];
    patch.stage = "extracted";
  } else if (tool === "generate_menu") {
    if (result?.ok === false) return patch;
    patch.menu = result;
    patch.stage = "menu";
  } else if (tool === "save_card") {
    if (result?.saved) {
      patch.stored = true;
      patch.cardId = result.card_id ? String(result.card_id) : undefined;
      patch.stage = "confirmed";
    }
  } else if (tool === "check_filing") {
    if (result?.found) {
      patch.sources = [
        {
          form: result.form_type,
          date: result.filed_at,
          url: result.url,
          note: result.note || "",
        },
      ];
    }
  }
  return patch;
}

/** extract_card 原始抽取 → 显示用 CardT 骨架（与 App CardT 同构；ticker 由 App 合并保留）。 */
function buildDisplayCard(ext: Record<string, any>): Record<string, any> {
  const kas = Array.isArray(ext?.key_assumptions) ? ext.key_assumptions : [];
  const mirrors = Array.isArray(ext?.mirrors) ? ext.mirrors : [];
  const manual = Array.isArray(ext?.manual_items) ? ext.manual_items : [];
  return {
    card_id: "",
    ticker: "", // App.applyStreamPatch 会合并进已 resolve 的 ticker
    filer_type: "other",
    holding_reason_raw: String(ext?.holding_reason_raw ?? ""),
    key_assumptions: kas.map((a: any, i: number) => ({
      id: String(a?.id || `a${i}`),
      text: String(a?.text ?? ""),
    })),
    broken_conditions: mirrors.map((m: any, i: number) => ({
      id: String(m?.id || `c${i}`),
      layer: "mirror",
      text: String(m?.mirror_text ?? ""),
      threshold: m?.threshold ?? {},
      template: null,
      source_type: String(m?.source_type ?? ""),
    })),
    manual_check_items: manual.map((mi: any, i: number) => ({
      id: String(mi?.id || `m${i}`),
      text: String(mi?.text ?? ""),
      reason: String(mi?.reason ?? "价格图形型"),
      cadence: String(mi?.cadence ?? "monthly"),
    })),
    entry_anchor: null,
    next_verdict: null,
    position_cap_tier: null,
    holding_horizon: null,
    confirmation: { confirmed_by_user: false },
  };
}

// ──────────────────────────── Mock 脚本（MCO 演示） ────────────────────────────
// ?sse=mock 时跑这个脚本，验证：tool_call 状态提示 + tool_result 卡片更新 + token 打字机。
export function buildMockScript(
  userText: string,
  _sid: string | null,
  kind: "start" | "send" | "confirm",
): MockItem[] {
  // 开场（录入一只票）走完整演示：resolve_ticker → extract_card → 文本流
  if (kind === "start") {
    const reply =
      "我找到 Moody's Corporation（MCO）。你的核心假设我拆成两条：评级业双寡头形成壁垒、AI 恐慌错杀定价。" +
      "镜像破局条件我列在右侧卡里了——全球债券发行规模同比跌破 -10%，或营业利润率跌破 45%，任一出现就说明 thesis 动摇。" +
      "你看看对不对，对的话我们接着聊估值和周期。";
    return [
      { event: "tool_call", data: { tool: "resolve_ticker", args: { query: "MCO" } }, delayMs: 200 },
      { event: "tool_result", data: { tool: "resolve_ticker", result: { found: true, ticker: "MCO", title: "Moody's Corporation", cik: "0001059556" } }, delayMs: 700 },
      { event: "tool_call", data: { tool: "extract_card", args: { text: userText, ticker: "MCO" } }, delayMs: 300 },
      {
        event: "tool_result",
        data: {
          tool: "extract_card",
          result: {
            ok: true,
            holding_reason_raw: userText,
            key_assumptions: [
              { text: "评级业双寡头（Moody's + S&P）形成进入壁垒，竞品难蚕食份额", judgeable: true },
              { text: "AI 恐慌错杀了 Moody's 定价，当前估值未反映 bond issuance volume 韧性", judgeable: true },
            ],
            mirrors: [
              { assumption_text: "评级业双寡头（Moody's + S&P）形成进入壁垒，竞品难蚕食份额", mirror_text: "全球债券发行规模同比跌破 -10%", threshold: { metric: "global_bond_issuance_yoy", operator: "<=", value: -10, unit: "%" }, source_type: "sec_filing_field" },
              { assumption_text: "AI 恐慌错杀了 Moody's 定价，当前估值未反映 bond issuance volume 韧性", mirror_text: "Moody's 营业利润率跌破 45%", threshold: { metric: "operating_margin", operator: "<", value: 45, unit: "%" }, source_type: "sec_filing_field" },
            ],
            open_questions: [],
            manual_items: [],
          },
        },
        delayMs: 900,
      },
      // 文本逐 chunk 流（~3 字/chunk × 30ms → 丝滑打字机感）
      ...chunkReply(reply, 3, 30),
      { event: "done", data: {}, delayMs: 120 },
    ];
  }
  // send：短文本流，演示打字机 + done（无 tool）
  if (kind === "send") {
    const reply = "收到。我把这条补进右侧卡了，你再看一眼有没有要改的。";
    return [...chunkReply(reply, 3, 30), { event: "done", data: {}, delayMs: 120 }];
  }
  // confirm：save_card tool_result（→ confirmed）+ 入库文案，演示落库态
  const reply = "已入库。命中会单独邮件提醒你，未命中合并进开盘前简报。";
  return [
    { event: "tool_call", data: { tool: "save_card", args: {} }, delayMs: 200 },
    { event: "tool_result", data: { tool: "save_card", result: { saved: true, card_id: "mock-card-0001", ticker: "MCO" } }, delayMs: 600 },
    ...chunkReply(reply, 3, 30),
    { event: "done", data: {}, delayMs: 120 },
  ];
}

/** 把整段回复切成 n 字一块，每块 delayEach ms——模拟 token 流。 */
function chunkReply(text: string, n: number, delayEach: number): MockItem[] {
  const out: MockItem[] = [];
  for (let i = 0; i < text.length; i += n) {
    out.push({ event: "token", data: { text: text.slice(i, i + n) }, delayMs: delayEach });
  }
  return out;
}
