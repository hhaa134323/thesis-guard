import * as React from "react";
import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";

// 录入对话 chat 组件（手写 shadcn 风格，不引 ai-sdk / Vercel AI SDK）。
// F1：气泡样式 + 发送键 + 自动滚动。来源标注块（R5）挂起并进 F3，不做。

// ─────────────────────────────── Bubble ───────────────────────────────
// 用户：深底白字、右对齐、右下角小圆角
// 系统：白底 + 1px 边框、左对齐、左下角小圆角、上方浅色发送者标签
export interface BubbleProps extends React.HTMLAttributes<HTMLDivElement> {
  role: "user" | "system";
  sender?: string;
}
export function Bubble({ role, sender, className, children, ...props }: BubbleProps) {
  if (role === "user") {
    return (
      <div
        className={cn(
          "max-w-[85%] rounded-2xl rounded-br-sm bg-foreground text-background px-3 py-2 text-sm whitespace-pre-wrap break-words",
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
  return (
    <div className="max-w-[85%]">
      {sender ? <div className="text-[11px] text-muted-foreground mb-1 px-1">{sender}</div> : null}
      <div
        className={cn(
          "rounded-2xl rounded-bl-sm border border-border bg-card text-foreground px-3 py-2 text-sm whitespace-pre-wrap break-words",
          className
        )}
        {...props}
      >
        {children}
      </div>
    </div>
  );
}

// ─────────────────────────────── Message ──────────────────────────────
// 行容器：按 role 决定左右对齐，内含一个 Bubble
export interface MessageProps extends React.HTMLAttributes<HTMLDivElement> {
  role: "user" | "system";
  sender?: string;
}
export function Message({ role, sender, className, children, ...props }: MessageProps) {
  return (
    <div className={cn("flex", role === "user" ? "justify-end" : "justify-start", className)} {...props}>
      <Bubble role={role} sender={sender}>
        {children}
      </Bubble>
    </div>
  );
}

// ──────────────────────────── MessageScroller ─────────────────────────
// 自动滚到底，但仅在用户已贴底时跟随（用户上滚阅读时不抢滚动）；
// ResizeObserver 跟随打字机逐字增长；behavior:auto（非 smooth）防流式跳动。
export interface MessageScrollerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 依赖项变化（如 messages 数组）触发贴底滚动 */
  dep?: unknown;
}
export function MessageScroller({ dep, className, children, ...props }: MessageScrollerProps) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const contentRef = React.useRef<HTMLDivElement>(null);
  const stick = React.useRef(true);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  // 内容高度变化（含打字机逐字增长）→ 若贴底则跟到底
  React.useEffect(() => {
    const el = scrollRef.current;
    const c = contentRef.current;
    if (!el || !c) return;
    const ro = new ResizeObserver(() => {
      if (stick.current) el.scrollTop = el.scrollHeight;
    });
    ro.observe(c);
    return () => ro.disconnect();
  }, []);

  // 新消息进入 → 若贴底则跟到底
  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stick.current) el.scrollTop = el.scrollHeight;
  }, [dep]);

  return (
    <div ref={scrollRef} onScroll={onScroll} className={cn("overflow-y-auto", className)} {...props}>
      <div ref={contentRef} className="space-y-3 pr-1">
        {children}
      </div>
    </div>
  );
}

// ─────────────────────────────── SendButton ───────────────────────────
// Notion 式：输入框内右下 30×30 深色圆角方钮 + 向上箭头
export interface SendButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}
export const SendButton = React.forwardRef<HTMLButtonElement, SendButtonProps>(
  ({ className, ...props }, ref) => (
    <button
      type="button"
      ref={ref}
      className={cn(
        "absolute right-2 bottom-2 inline-flex items-center justify-center w-[30px] h-[30px] rounded-lg bg-foreground text-background",
        "hover:opacity-90 active:scale-95 transition disabled:pointer-events-none disabled:opacity-40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
      {...props}
    >
      <ArrowUp size={16} strokeWidth={2.5} />
    </button>
  )
);
SendButton.displayName = "SendButton";
