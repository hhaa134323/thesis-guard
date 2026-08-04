"""录入 loop 承载层（Phase 2 重构：state machine → agent loop 委托）。

serve.py 的 3 个 endpoint 调本模块的 EntrySession。EntrySession 持对话历史，把用户消息
转发给 orchestrator.agent（OpenAI Agents SDK + DeepSeek V4-Flash），agent loop 自己管 5 步
讨论流程；本模块只做 session 管理 + view 序列化（把 agent 输出 + tool 调用结果格式化给前端）。

guardrail 层零改动：G3（is_paraphrase/is_v1_auto）在 orchestrator._extract_card_impl；
save_card G1/G4/G2 在 orchestrator._save_card_impl；本模块只消费 tool 输出，不重复校验。

保留 EntrySession / new_session / S_CONFIRMED 等 surface 供 serve.py + evals/run_w2.py
（W2 eval 是 state-machine-era，Phase 5 重做 agent-loop 版）import 不挂。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .agent import build_card_from_extraction
from .models import (
    Assumption,
    EntryAnchorData,
    FilerType,
    ThesisCard,
    to_dict,
)
from .orchestrator import agent as _thesis_agent, build_thesis_guard_agent
from .schema import Assumption as ExtAssumption, EntryExtraction, MirrorSpec
from .tier_map import lookup_tier

# 阶段（view.stage 给前端用；agent loop 无硬状态机，stage 由本轮 tool 调用派生）
S_OPENING = "opening"
S_EXTRACTED = "extracted"        # resolve_ticker + extract_card 后
S_MENU = "menu"                  # generate_menu 后
S_CONFIRM = "confirm_card"
S_CONFIRMED = "confirmed"        # save_card 后
S_TICKER_CLARIFY = "ticker_clarify"

_MAX_TURNS = 8


def _parse_tool_output(s: str) -> Any:
    """SDK 把 tool 返回（dict）序列化成字符串存进 ToolCallOutputItem.raw['output']。
    实测为 Python repr（单引号 / True）而非 JSON（双引号 / true）——两种都试，稳健。"""
    import ast
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(s)
        except Exception:
            continue
    return {"raw": s}


def _sse(event: str, data: dict) -> str:
    """格式化一个 SSE 事件字符串（event: <name> + data: <json> + 空行结束）。"""
    nl = chr(10)
    return f"event: {event}{nl}data: {json.dumps(data, ensure_ascii=False)}{nl}{nl}"


@dataclass
class EntrySession:
    user_id: str
    ticker: str
    cfg: dict
    model_name: str | None = None  # Stage 2：按会话选模型；None 走 orchestrator.agent 单例（行为不变）
    stage: str = S_OPENING
    history: list = field(default_factory=list)  # agent input items（Runner.to_input_list 累积）
    card_draft: Any = None        # models.ThesisCard（extract_card 后建草稿；save_card 落库）
    menu: Any = None              # generate_menu 输出 dict
    open_questions: list = field(default_factory=list)
    ticker_title: str | None = None
    sources: list = field(default_factory=list)
    stored: bool = False
    card_id: str | None = None
    error: str | None = None
    metrics: dict = field(default_factory=lambda: {"turns": 0, "clarification_rounds": 0, "converged": False})
    _agent: Any = field(default=None, init=False, repr=False)  # 按需构建的 agent（model_name=None → 单例）

    def __post_init__(self) -> None:
        """Stage 2：model_name 非空 → 按会话 build_thesis_guard_agent；None → 模块级单例（行为不变）。"""
        self._agent = (_thesis_agent if not self.model_name
                       else build_thesis_guard_agent(self.cfg, model_name=self.model_name))

    # ------------------------------------------------------------------ #
    # 对话入口（serve.py / evals/run_w2.py 调）
    # ------------------------------------------------------------------ #
    def start(self, text: str, ticker_override: str | None = None) -> dict:
        if ticker_override:
            # W2 eval 传 GT ticker——预置提示让 agent 直接确认（agent 仍会 resolve_ticker 核验）
            text = f"（标的已知：{ticker_override.strip().upper()}）{text}"
        return self._run(text)

    def turn(self, payload: dict) -> dict:
        text = (payload.get("text") or "").strip()
        if not text:
            picks = payload.get("picks") or {}
            edits = payload.get("edits") or {}
            if payload.get("request_menu") or picks:
                text = "无法确定，给我候选菜单" + (
                    f"，选 A{picks.get('assumptions')} B{picks.get('mirrors')}" if picks else "")
            elif edits:
                text = "请按以下修改确认卡：" + ", ".join(f"{k}={v}" for k, v in edits.items())
            else:
                text = "（空输入）"
        return self._run(text)

    def confirm(self, edits: dict | None = None) -> dict:
        text = "确认入库" if not edits else (
            "请按以下修改后入库：" + ", ".join(f"{k}={v}" for k, v in edits.items()))
        return self._run(text)

    # ------------------------------------------------------------------ #
    # agent loop 委托
    # ------------------------------------------------------------------ #
    def _run(self, user_text: str) -> dict:
        from agents import Runner

        self.metrics["turns"] += 1
        input_items = (user_text if not self.history
                       else self.history + [{"role": "user", "content": user_text}])
        try:
            result = Runner.run_sync(self._agent, input_items, max_turns=_MAX_TURNS)
        except Exception as e:  # noqa: BLE001 —— guardrail trip / MaxTurns / 网络都兜底，不崩
            ename = type(e).__name__
            self.error = f"{ename}: {str(e)[:200]}"
            msg = ("（你的输入触发了安全拦截，请换种说法。）" if "Tripwire" in ename
                   else f"出错：{ename}：{str(e)[:160]}")
            return self._view(assistant=msg)
        self.history = result.to_input_list()
        self._mine(result.new_items)
        reply = result.final_output if isinstance(result.final_output, str) else str(result.final_output or "")
        return self._view(assistant=reply)

    async def stream_run(self, user_text: str):
        """SSE 流式跑一轮：yield SSE 事件字符串（token/tool_call/tool_result/done/error）。
        token = response.output_text.delta；tool_call/tool_result = RunItem tool_called/tool_output。
        流完更新 history + _mine（与 _run 一致，供后续 /turn 或 view 用）。现有 JSON /turn 不动。"""
        from agents import Runner

        self.metrics["turns"] += 1
        input_items = (user_text if not self.history
                       else self.history + [{"role": "user", "content": user_text}])
        try:
            result = Runner.run_streamed(self._agent, input_items, max_turns=_MAX_TURNS)
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {str(e)[:200]}"
            yield _sse("error", {"message": f"出错：{type(e).__name__}"})
            yield _sse("done", {})
            return
        last_tool: str | None = None
        try:
            async for ev in result.stream_events():
                tname = type(ev).__name__
                if tname == "RawResponsesStreamEvent":
                    d = ev.data
                    if getattr(d, "type", None) == "response.output_text.delta":
                        delta = getattr(d, "delta", "")
                        if delta:
                            yield _sse("token", {"text": delta})
                elif tname == "RunItemStreamEvent":
                    if ev.name == "tool_called":
                        raw = getattr(ev.item, "raw_item", None)
                        name = (getattr(raw, "name", None)
                                or (raw.get("name") if isinstance(raw, dict) else None))
                        args = getattr(raw, "arguments", None)
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        if name:
                            last_tool = name
                            yield _sse("tool_call", {"tool": name, "args": args})
                    elif ev.name == "tool_output":
                        raw = getattr(ev.item, "raw_item", None)
                        out = (raw.get("output") if isinstance(raw, dict)
                               else getattr(raw, "output", None))
                        parsed = _parse_tool_output(out) if isinstance(out, str) else out
                        yield _sse("tool_result", {"tool": last_tool, "result": parsed})
                        last_tool = None
        except Exception as e:  # noqa: BLE001 — 流式中途出错（网络/guardrail/SDK）兜底，发 error+done 不断连
            self.error = f"{type(e).__name__}: {str(e)[:200]}"
            yield _sse("error", {"message": f"出错：{type(e).__name__}"})
            yield _sse("done", {})
            return
        # 流完：更新 history + mine（保持与 _run 一致的 view 状态）
        self.history = result.to_input_list()
        self._mine(result.new_items)
        yield _sse("done", {})

    def _mine(self, items) -> None:
        """从本轮 tool 调用结果派生 view 字段（stage/card/menu/ticker/sources）。
        ToolCallItem（带 name）与紧随的 ToolCallOutputItem（带 output）按序配对。"""
        last_tool: str | None = None
        for it in items:
            tname = type(it).__name__
            raw = getattr(it, "raw_item", None)
            if tname == "ToolCallItem":
                last_tool = self._tool_name(raw)
            elif tname == "ToolCallOutputItem":
                out = self._tool_output(raw)
                if last_tool and out is not None:
                    self._apply_tool_output(last_tool, out)
                last_tool = None

    def _apply_tool_output(self, name: str, out: Any) -> None:
        if isinstance(out, str):
            out = _parse_tool_output(out)
        if not isinstance(out, dict):
            return
        if name == "resolve_ticker":
            if out.get("found"):
                self.ticker = out.get("ticker", self.ticker)
                self.ticker_title = out.get("title")
                if self.stage == S_OPENING:
                    self.stage = S_EXTRACTED
        elif name == "extract_card":
            if out.get("ok") is False:
                return
            self._build_card_draft(out)
            self.open_questions = list(out.get("open_questions") or [])
            if self.stage in (S_OPENING, S_TICKER_CLARIFY):
                self.stage = S_EXTRACTED
        elif name == "generate_menu":
            if out.get("ok") is False:
                return
            self.menu = out
            self.stage = S_MENU
            self.metrics["clarification_rounds"] += 1
        elif name == "save_card":
            if out.get("saved"):
                self.stored = True
                self.card_id = out.get("card_id")
                self.stage = S_CONFIRMED
                self.metrics["converged"] = True
        elif name == "check_filing":
            if out.get("found"):
                self.sources = [{"form": out.get("form_type"), "date": out.get("filed_at"),
                                 "url": out.get("url"), "note": out.get("note", "")}]

    @staticmethod
    def _tool_name(raw) -> str | None:
        for n in ("name", "tool_name"):
            v = getattr(raw, n, None)
            if v:
                return v
        if isinstance(raw, dict):
            return raw.get("name") or raw.get("tool_name")
        return None

    @staticmethod
    def _tool_output(raw) -> Any:
        for o in ("output", "result", "content"):
            v = getattr(raw, o, None)
            if v is not None:
                return v
        if isinstance(raw, dict):
            return raw.get("output") or raw.get("content")
        return None

    def _build_card_draft(self, ext_out: dict) -> None:
        """extract_card 输出（dict）→ ThesisCard 草稿（复用 build_card_from_extraction）。
        key_assumptions/mirrors 已过 G3（orchestrator._extract_card_impl 过滤过）；
        build_card_from_extraction 再做 make_mirror + redline 默认包（不重复 G3）。"""
        raw = ext_out.get("holding_reason_raw", "") or ""
        assumptions = [
            Assumption(text=(a.get("text") if isinstance(a, dict) else str(a)),
                       judgeable=(a.get("judgeable", True) if isinstance(a, dict) else True))
            for a in (ext_out.get("key_assumptions") or [])
        ]
        ext = EntryExtraction(
            holding_reason_raw=raw,
            key_assumptions=[ExtAssumption(text=a.text, judgeable=a.judgeable) for a in assumptions],
            mirrors=[MirrorSpec(assumption_text=m.get("assumption_text", ""),
                                mirror_text=m.get("mirror_text", ""),
                                threshold=m.get("threshold"),
                                source_type=m.get("source_type", ""))
                     for m in (ext_out.get("mirrors") or [])],
            # dict（非 models.ManualCheckItem dataclass 实例）——Pydantic 才能把它 coerce
            # 成 schema.ManualCheckItem；传 dataclass 实例会 ValidationError（Bug 修 2026-08-04）
            manual_items=[{"text": mi.get("text", ""),
                            "reason": mi.get("reason", "价格图形型"),
                            "cadence": mi.get("cadence", "monthly")}
                           for mi in (ext_out.get("manual_items") or [])],
        )
        card, _rejected = build_card_from_extraction(
            ext, user_id=self.user_id, ticker=(self.ticker or ""),
            tier=lookup_tier(self.ticker) if self.ticker else None,
            filer_type=FilerType.OTHER)
        # carry over 已讨论的 entry_anchor / holding_horizon（旧草稿里有则保留）
        if self.card_draft is not None:
            if self.card_draft.entry_anchor is not None:
                card.entry_anchor = self.card_draft.entry_anchor
            if self.card_draft.holding_horizon:
                card.holding_horizon = self.card_draft.holding_horizon
        self.card_draft = card

    # ------------------------------------------------------------------ #
    # 视图（给 serve.py 序列化回前端）
    # ------------------------------------------------------------------ #
    def _view(self, assistant: str) -> dict:
        card_json = to_dict(self.card_draft) if self.card_draft is not None else None
        menu_json = None
        if self.menu is not None and self.stage == S_MENU:
            menu_json = self.menu
        return {
            "stage": self.stage,
            "assistant": assistant,
            "card": card_json,
            "menu": menu_json,
            "open_questions": list(self.open_questions),
            "ticker": self.ticker,
            "ticker_title": self.ticker_title,
            "sources": list(self.sources),
            "error": self.error,
            "metrics": dict(self.metrics),
            "stored": self.stored,
            "card_id": self.card_id,
        }


def new_session(user_id: str, cfg: dict, model_name: str | None = None) -> EntrySession:
    return EntrySession(user_id=user_id, ticker="", cfg=cfg, model_name=model_name)


__all__ = ["EntrySession", "new_session",
           "S_OPENING", "S_EXTRACTED", "S_MENU", "S_CONFIRM", "S_CONFIRMED", "S_TICKER_CLARIFY"]
