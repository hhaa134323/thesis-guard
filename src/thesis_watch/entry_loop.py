"""录入对话 loop 状态机（spec §1 八步 → 对话环节；承载层 = serve.py FastAPI localhost 单页）。

单次 extract()（entry_agent）产 EntryExtraction；「无法确定」时单次 generate_menu()（menu）产候选；
规则驱动可判定性追问 / 一致性校验（spec §11.1）/ 价格图形型降 manual；
build_card_from_extraction 落 ThesisCard；confirmed_by_user=True 后由 serve.py 入 SQLite。

可用性验收（spec §10）：单票 ≤5min、阻断式澄清 ≤3 次（本 loop 阻断仅可判定性一处）。
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import EntryExtraction
from .entry_agent import build_agent, extract
from .menu import build_menu_agent, generate_menu
from .agent import build_card_from_extraction
from .tier_map import lookup_tier
from .conditions import is_price_pattern
from . import redline
from .models import ThesisCard, to_dict

# 阶段
S_OPENING = "opening"
S_EXTRACTED = "extracted"      # 已抽，呈现 + 问（确认 or 无法确定→菜单）
S_MENU = "menu"                # 给候选菜单，等用户勾选
S_CONFIRM = "confirm_card"     # 复述确认卡（右侧实时），等用户点改/确认
S_CONFIRMED = "confirmed"

# 用户「无法确定」的口语触发词
UNDECIDED_HINTS = (
    "无法确定", "说不清", "说不上", "说不出来", "不清楚", "不知道",
    "菜单", "候选", "给选项", "给候选", "不知道破什么", "想不出来",
)


_FILER_LOOKUP: dict[str, str] | None = None


def _load_filer_lookup() -> dict[str, str]:
    """载 filer_type_lookup.yaml（与核对侧/eval 复用同一份；SEC EDGAR 拉取，确定性）。
    路径可被 THESIS_FILER_LOOKUP 覆盖（部署中立）；缺省 evals/filer_type_lookup.yaml。"""
    global _FILER_LOOKUP
    if _FILER_LOOKUP is None:
        import yaml
        default_path = Path(__file__).resolve().parents[2] / "evals" / "filer_type_lookup.yaml"
        p = Path(os.environ.get("THESIS_FILER_LOOKUP", str(default_path)))
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            _FILER_LOOKUP = {t: (v.get("filer_type") if isinstance(v, dict) else None)
                             for t, v in (data.get("tickers") or {}).items()}
        else:
            _FILER_LOOKUP = {}
    return _FILER_LOOKUP


@dataclass
class EntrySession:
    user_id: str
    ticker: str
    cfg: dict
    stage: str = S_OPENING
    conversation: list[dict] = field(default_factory=list)  # {role, text}
    ext: Any = None                # schema.EntryExtraction
    menu: Any = None               # menu.MenuCandidates
    card_draft: Any = None         # models.ThesisCard
    open_questions: list[dict] = field(default_factory=list)
    blocking_clarifications: int = 0
    metrics: dict = field(default_factory=lambda: {"turns": 0, "clarification_rounds": 0, "converged": False})
    error: str | None = None
    _extract_agent: Any = None
    _menu_agent: Any = None
    _filer: Any = None
    _filer_src: str | None = None

    def _agents(self) -> tuple[Any, Any]:
        if self._extract_agent is None:
            self._extract_agent, _, _ = build_agent(self.cfg)
        if self._menu_agent is None:
            self._menu_agent, _, _ = build_menu_agent(self.cfg)
        return self._extract_agent, self._menu_agent

    def _resolve_filer(self, ext):
        """filer_type 确定性查表（filer_type_lookup.yaml）→ 模型兜底 → 待确认。
        返回 (models.FilerType | None, src: 'lookup'|'model_fallback'|'pending')。"""
        from .models import FilerType as ModelFilerType
        lookup = _load_filer_lookup()
        ft_str = lookup.get(self.ticker)
        if ft_str:
            try:
                return ModelFilerType(ft_str), "lookup"
            except ValueError:
                pass
        if ext is not None and ext.filer_type and ext.filer_type.value != "other":
            return ModelFilerType(ext.filer_type.value), "model_fallback"
        return None, "pending"

    def _filer_open_question(self, src: str) -> None:
        if src == "model_fallback":
            self.open_questions.append({"field": "filer_type",
                "reason": f"filer_type 模型兜底（查表无 {self.ticker}），建议复核"})
        elif src == "pending":
            self.open_questions.append({"field": "filer_type",
                "reason": f"filer_type 待确认（查表无 {self.ticker} + 模型未给确定性类型）"})

    # ------------------------------------------------------------------ #
    # 对话入口
    # ------------------------------------------------------------------ #
    def start(self, reason: str) -> dict:
        self.conversation.append({"role": "user", "text": reason})
        self.metrics["turns"] += 1
        ea, _ = self._agents()
        res = extract(ea, reason, self.cfg, mode="A")  # §6.8 暂只 mode A；W2 eval 改收敛后测
        self.ext = res["extraction"]
        if self.ext is None:
            self.error = f"{res.get('status')}: {res.get('error', '')[:200]}"
            a = redline.guard(f"抽取失败（{res.get('status')}）。可重试，或在右侧确认卡里手填。")
            self.conversation.append({"role": "assistant", "text": a})
            return self._view(assistant=a)
        self.stage = S_EXTRACTED
        self._filer, self._filer_src = self._resolve_filer(self.ext)
        self.card_draft = build_card_from_extraction(
            self.ext, user_id=self.user_id, ticker=self.ticker,
            tier=lookup_tier(self.ticker), filer_type=self._filer)
        self._filer_open_question(self._filer_src)
        price_hit = is_price_pattern(reason)
        a = redline.guard(self._present_extraction(price_hit))
        self.conversation.append({"role": "assistant", "text": a})
        return self._view(assistant=a)

    def turn(self, payload: dict) -> dict:
        text = (payload.get("text") or "").strip()
        self.metrics["turns"] += 1
        if self.stage == S_EXTRACTED:
            if any(h in text for h in UNDECIDED_HINTS) or payload.get("request_menu"):
                self.conversation.append({"role": "user", "text": text or "无法确定"})
                return self._do_menu()
            # 否则视为确认 ext → 进确认卡
            self.conversation.append({"role": "user", "text": text or "确认"})
            self.stage = S_CONFIRM
            a = redline.guard("好，按上面的做成确认卡（右侧）。可直接点改字段，确认后入库。")
            self.conversation.append({"role": "assistant", "text": a})
            return self._view(assistant=a)
        if self.stage == S_MENU:
            picks = payload.get("picks") or {}
            if not (picks.get("assumptions") or picks.get("mirrors")):
                a = redline.guard("请在右侧勾选 A（信什么）和 B（破什么）后提交。")
                return self._view(assistant=a)
            self.conversation.append({"role": "user", "text": f"勾选 A{picks.get('assumptions')} B{picks.get('mirrors')}"})
            return self._apply_picks(picks)
        if self.stage == S_CONFIRM:
            edits = payload.get("edits") or {}
            if edits:
                self._apply_edits(edits)
            return self._view(assistant=redline.guard("（在右侧点「确认入库」即落库。）"))
        return self._view(assistant=redline.guard("（当前阶段无动作。）"))

    def confirm(self, edits: dict | None = None) -> dict:
        if self.card_draft is None:
            return self._view(assistant=redline.guard("无卡片可入库。"))
        if edits:
            self._apply_edits(edits)
        self.card_draft.confirmation.confirmed_by_user = True
        import datetime
        self.card_draft.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        self.stage = S_CONFIRMED
        self.metrics["converged"] = True
        a = redline.guard(
            f"✓ 已落库（{self.ticker} · status=有 thesis）。判断权归你——命中会单独邮件，未命中合并进简报。")
        self.conversation.append({"role": "assistant", "text": a})
        return self._view(assistant=a)

    # ------------------------------------------------------------------ #
    # 内部：菜单 / 勾选 / 一致性 / 编辑
    # ------------------------------------------------------------------ #
    def _do_menu(self) -> dict:
        self.metrics["clarification_rounds"] += 1
        _, ma = self._agents()
        reason = self.conversation[0]["text"] if self.conversation else ""
        r = generate_menu(ma, self.ticker, reason, self.cfg)
        if not r["ok"] or r["menu"] is None:
            self.error = f"{r.get('status')}: {r.get('error','')[:200]}"
            self.stage = S_CONFIRM  # 失败也放行到手填
            a = redline.guard(f"候选菜单生成失败（{r.get('status')}）。可直接在右侧确认卡手填假设/破条件。")
            self.conversation.append({"role": "assistant", "text": a})
            return self._view(assistant=a)
        self.menu = r["menu"]
        self.stage = S_MENU
        a = redline.guard(self._present_menu())
        self.conversation.append({"role": "assistant", "text": a})
        return self._view(assistant=a)

    def _apply_picks(self, picks: dict) -> dict:
        from .schema import Assumption, MirrorSpec

        a_idx = picks.get("assumptions") or []
        m_idx = picks.get("mirrors") or []
        cand_a = self.menu.candidate_assumptions
        cand_b = self.menu.candidate_mirrors
        chosen_a = [cand_a[i] for i in a_idx if 0 <= i < len(cand_a)]
        chosen_b = [cand_b[i] for i in m_idx if 0 <= i < len(cand_b)]

        new_ext = EntryExtraction(
            holding_reason_raw=self.ext.holding_reason_raw if self.ext else "",
            key_assumptions=[Assumption(text=x) for x in chosen_a],
            mirrors=[MirrorSpec(assumption_text=b.assumption, mirror_text=b.mirror_text) for b in chosen_b],
            manual_items=self.ext.manual_items if self.ext else [],
            filer_type=self.ext.filer_type if self.ext else None,
            next_verdict=self.ext.next_verdict if self.ext else None,
            entry_anchor=self.ext.entry_anchor if self.ext else None,
        )
        self.ext = new_ext
        self.card_draft = build_card_from_extraction(
            new_ext, user_id=self.user_id, ticker=self.ticker,
            tier=lookup_tier(self.ticker), filer_type=self._filer)
        self._consistency_check(chosen_a, chosen_b)
        self.stage = S_CONFIRM
        note = f"⚠️ 一致性存疑：{self.open_questions[-1]['reason']}。" if self.open_questions else ""
        a = redline.guard(f"做成了确认卡（右侧）。{note}可点改字段，确认后入库。")
        self.conversation.append({"role": "assistant", "text": a})
        return self._view(assistant=a)

    def _consistency_check(self, assumptions: list[str], mirrors: list) -> None:
        """屏 5：信的假设与勾的破条件不对应 → open_question（记录式，不阻断，spec §11.1）。"""
        aset = set(assumptions)
        for b in mirrors:
            if b.assumption not in aset:
                self.open_questions.append({
                    "field": "mirrors",
                    "reason": f"信的假设({assumptions})与勾的破条件「{b.mirror_text}」(对应「{b.assumption}」)不对应",
                })
                return

    def _apply_edits(self, edits: dict) -> None:
        c: ThesisCard | None = self.card_draft
        if c is None:
            return
        if "holding_reason_raw" in edits:
            c.holding_reason_raw = edits["holding_reason_raw"]
        if "entry_anchor" in edits and c.entry_anchor is not None:
            ea = edits["entry_anchor"] or {}
            if "anchor_type" in ea:
                c.entry_anchor.anchor_type = ea["anchor_type"]
            if "anchor_value" in ea:
                c.entry_anchor.anchor_value = ea["anchor_value"]
            if "note" in ea:
                c.entry_anchor.note = ea["note"]
        if "next_verdict" in edits and c.next_verdict is not None:
            nv = edits["next_verdict"] or {}
            if "event" in nv:
                c.next_verdict.event = nv["event"]
            if "date" in nv:
                c.next_verdict.date = nv["date"]
            if "source_note" in nv:
                c.next_verdict.source_note = nv["source_note"]
        if "position_cap_tier" in edits:
            c.position_cap_tier = edits["position_cap_tier"]

    # ------------------------------------------------------------------ #
    # 呈现（系统输出，过 redline.guard）
    # ------------------------------------------------------------------ #
    def _present_extraction(self, price_hit: bool) -> str:
        ext = self.ext
        lines = [f"✓ 记下 {self.ticker}。把你说的复述一遍：",
                 f"  买入逻辑（原话）：「{ext.holding_reason_raw}」"]
        if ext.key_assumptions:
            lines.append("  我抽到的关键假设：")
            for i, a in enumerate(ext.key_assumptions, 1):
                lines.append(f"    {i}) {a.text}")
        if ext.mirrors:
            lines.append("  对应的镜像破条件：")
            for i, m in enumerate(ext.mirrors, 1):
                lines.append(f"    {i}) {m.mirror_text}")
        if price_hit:
            lines.append("  ⚠️ 你的理由含价格图形——记成「人工自查项」（每月提醒），不进自动核对。")
        if ext.entry_anchor:
            ea = ext.entry_anchor
            lines.append(f"  录入估值锚：{ea.anchor_type} = {ea.anchor_value}（{ea.note}）")
        if ext.next_verdict:
            lines.append(f"  下次裁判日：{ext.next_verdict.event}（{ext.next_verdict.date}）")
        lines.append("这些对吗？确认就做成卡片；说不清破什么就回「无法确定」，我给候选菜单。")
        return "\n".join(lines)

    def _present_menu(self) -> str:
        m = self.menu
        lines = ["给你候选，挑就行（选一次填两槽）：", "A. 你信什么（右侧可多选）："]
        for i, a in enumerate(m.candidate_assumptions, 1):
            lines.append(f"  A{i} {a}")
        lines.append("B. 破的条件（右侧勾几条，每条我能从公告核对）：")
        for i, b in enumerate(m.candidate_mirrors, 1):
            lines.append(f"  B{i} {b.mirror_text}（对应 {b.assumption}）")
        lines.append("在右侧勾选 A 和 B，提交后做成确认卡。")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 视图（给 serve.py 序列化回前端）
    # ------------------------------------------------------------------ #
    def _view(self, assistant: str) -> dict:
        card_json = to_dict(self.card_draft) if self.card_draft is not None else None
        menu_json = None
        if self.menu is not None and self.stage == S_MENU:
            menu_json = {
                "assumptions": list(self.menu.candidate_assumptions),
                "mirrors": [{"assumption": b.assumption, "mirror_text": b.mirror_text}
                            for b in self.menu.candidate_mirrors],
            }
        return {
            "stage": self.stage,
            "assistant": assistant,
            "card": card_json,
            "menu": menu_json,
            "open_questions": list(self.open_questions),
            "ticker": self.ticker,
            "error": self.error,
            "metrics": dict(self.metrics),
        }


def new_session(user_id: str, ticker: str, cfg: dict) -> EntrySession:
    return EntrySession(user_id=user_id, ticker=(ticker or "").strip().upper(), cfg=cfg)


__all__ = ["EntrySession", "new_session", "S_CONFIRMED"]
