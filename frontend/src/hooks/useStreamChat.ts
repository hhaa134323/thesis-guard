// 流式对话 hook（Phase 3）：把 lib/stream 的 SSE 消费接进 React 状态。
//
// streaming  —— 当前是否在流式输出（驱动"正在输入"指示器 + LiveText 光标）；
// toolStatus —— 当前 tool_call 的中文状态（"正在查询 resolve_ticker…"），tool_result 后清空；
// start(opts) —— 开流。opts 里塞 onToken/onToolResult/onDone/onFallback 回调，App 用它们更新
//                conv（逐 token 追加）与 card/menu/ticker（tool_result 重建）。
// stop()      —— 主动断流（切话题 / unmount）。
//
// SSE 启用方式（URL 参数）：
//   ?sse=mock —— MockEventSource 本地模拟（验证丝滑感；后端 SSE 未就绪时用这个）；
//   ?sse=real —— 真 EventSource 连 /api/stream（连不上自动 onFallback 回退 fetch）；
//   无参数    —— App 不调本 hook，直接走现有 fetch JSON（默认，行为不变）。
import { useCallback, useRef, useState } from "react";
import {
  buildMockScript,
  connectStream,
  FetchStreamSource,
  MockEventSource,
  type StreamSource,
} from "@/lib/stream";

export interface StreamStartOpts {
  userText: string;
  sid: string | null;
  kind: "start" | "send" | "confirm";
  onToken: (text: string) => void;
  onToolCall: (tool: string, args: Record<string, unknown>) => void;
  onToolResult: (tool: string, result: Record<string, unknown>) => void;
  onDone: () => void;
  /** 后端 stream 异常（event: error）→ App 亮错误条。 */
  onError?: (message: string) => void;
  /** SSE 连不上（无后端）→ App 回退 fetch。 */
  onFallback: () => void;
}

export function useStreamChat() {
  const [streaming, setStreaming] = useState(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const closeRef = useRef<(() => void) | null>(null);

  const start = useCallback((opts: StreamStartOpts) => {
    // 关掉上一次（切话题 / 重复点发送）
    closeRef.current?.();

    const mode =
      typeof URLSearchParams !== "undefined"
        ? new URLSearchParams(location.search).get("sse")
        : null;

    // real 模式无 sid：session 尚未建（App 的 start 走 fetch 建 session），stream 无的放矢
    // → 直接回退，让 App 走对应 fetch 路径。send 时 sid 已就位、不会进这里。
    if (mode !== "mock" && !opts.sid) {
      opts.onFallback();
      return;
    }

    setStreaming(true);
    setToolStatus(null);

    let source: StreamSource;
    if (mode === "mock") {
      source = new MockEventSource(buildMockScript(opts.userText, opts.sid, opts.kind));
    } else {
      // ?sse=real：POST /api/session/{sid}/stream（后端 endpoint 是 POST；EventSource 只能
      // GET，故走 FetchStreamSource = fetch + ReadableStream 读 SSE 帧再按 event 名派发）。
      // 后端 stream_run 只吃 {text}（非 edits），故 real 模式 confirm 不走这里（App 走 /confirm）。
      const url = `/api/session/${encodeURIComponent(opts.sid!)}/stream`;
      source = new FetchStreamSource(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: opts.userText }),
      });
    }

    const close = connectStream(source, {
      onToken: opts.onToken,
      onToolCall: (tool, args) => {
        setToolStatus(`正在查询 ${tool}…`);
        opts.onToolCall(tool, args);
      },
      onToolResult: (tool, result) => {
        setToolStatus(null);
        opts.onToolResult(tool, result);
      },
      onError: (msg) => opts.onError?.(msg),
      onDone: () => {
        setStreaming(false);
        setToolStatus(null);
        opts.onDone();
      },
      onFallback: (reason) => {
        setStreaming(false);
        setToolStatus(null);
        opts.onFallback();
      },
    });
    closeRef.current = close;
  }, []);

  const stop = useCallback(() => {
    closeRef.current?.();
    closeRef.current = null;
    setStreaming(false);
    setToolStatus(null);
  }, []);

  return { streaming, toolStatus, start, stop };
}
