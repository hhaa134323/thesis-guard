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
from .dialogue import (build_dialogue_agent, generate_dialogue,
                       classify_confirm_intent, is_factual_fetchable)
from .agent import build_card_from_extraction
from .tier_map import lookup_tier
from .conditions import is_price_pattern
from .fetchers.ticker_resolver import resolve as resolve_ticker
from . import redline
from .models import ThesisCard, to_dict

# 阶段
S_OPENING = "opening"
S_EXTRACTED = "extracted"      # 已抽，呈现 + 问（确认 or 无法确定→菜单）
S_MENU = "menu"                # 给候选菜单，等用户勾选
S_CONFIRM = "confirm_card"     # 复述确认卡（右侧实时），等用户点改/确认
S_CONFIRMED = "confirmed"
S_TICKER_CLARIFY = "ticker_clarify"  # 标的识别不出 → 追问代码（单输入框兜底，2026-08-02）

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
    _dialogue_agent: Any = None
    _filer: Any = None
    _filer_src: str | None = None
    _ticker_candidates: Any = None  # P0：resolve 返回 >1 候选时暂存，供澄清文案列出
    _excluded_mirrors: Any = None  # P4：可执行性过滤剔除的 B 候选，覆盖率显式呈现用

    def _agents(self) -> tuple[Any, Any, Any]:
        if self._extract_agent is None:
            self._extract_agent, _, _ = build_agent(self.cfg)
        if self._menu_agent is None:
            self._menu_agent, _, _ = build_menu_agent(self.cfg)
        if self._dialogue_agent is None:
            self._dialogue_agent, _, _ = build_dialogue_agent(self.cfg)
        return self._extract_agent, self._menu_agent, self._dialogue_agent

    def _resolve_filer(self, ext):
        """filer_type 确定性查表（filer_type_lookup.yaml）→ 无则 pending。

        P0 schema 审计：filer_type 是事实（SEC 申报方类型），不经 LLM——
        查表命中→用；查表无→pending（open_question 问用户），不模型兜底。
        返回 (models.FilerType | None, src: 'lookup'|'pending')。
        """
        from .models import FilerType as ModelFilerType
        lookup = _load_filer_lookup()
        ft_str = lookup.get(self.ticker)
        if ft_str:
            try:
                return ModelFilerType(ft_str), "lookup"
            except ValueError:
                pass
        return None, "pending"

    def _filer_open_question(self, src: str) -> None:
        if src == "pending":
            self.open_questions.append({"field": "filer_type",
                "reason": f"filer_type 待确认（查表无 {self.ticker}）"})

    # ------------------------------------------------------------------ #
    # 对话入口
    # ------------------------------------------------------------------ #
    def start(self, text: str, ticker_override: str | None = None) -> dict:
        self.conversation.append({"role": "user", "text": text})
        self.metrics["turns"] += 1
        ea, _, da = self._agents()
        res = extract(ea, text, self.cfg, mode="A")  # §6.8 暂只 mode A；W2 eval 改收敛后测
        self.ext = res["extraction"]
        if self.ext is None:
            self.error = f"{res.get('status')}: {res.get('error', '')[:200]}"
            a = redline.guard(f"抽取失败（{res.get('status')}）。可重试，或在右侧确认卡里手填。")
            self.conversation.append({"role": "assistant", "text": a})
            return self._view(assistant=a)
        # P0：ticker 确定性解析（SEC 官方表，不经 LLM）。
        # ticker_override = W2 eval 传 GT ticker（信任，不查）；否则 resolve(user text)。
        # 1 命中 → 用；>1 / 0 → S_TICKER_CLARIFY（多候选列出，零候选追问），不猜。
        if ticker_override:
            self.ticker = ticker_override.strip().upper()
            return self._after_ticker_resolved(is_price_pattern(text))
        matches = resolve_ticker(text)
        if len(matches) == 1:
            self.ticker = matches[0].ticker
            return self._after_ticker_resolved(is_price_pattern(text))
        self._ticker_candidates = matches
        self.stage = S_TICKER_CLARIFY
        dlg = generate_dialogue(da, self._ctx_ticker_clarify(), self.cfg)
        a = dlg["text"] if dlg["ok"] and dlg["text"].strip() else self._ticker_clarify_text()
        a = redline.guard(a)
        self.conversation.append({"role": "assistant", "text": a})
        return self._view(assistant=a)

    def _after_ticker_resolved(self, price_hit: bool) -> dict:
        """ticker 解析后：建卡 + 复述呈现（start 与 S_TICKER_CLARIFY turn 共用）。"""
        self.stage = S_EXTRACTED
        self._filer, self._filer_src = self._resolve_filer(self.ext)
        self.card_draft, _rejected_mirrors = build_card_from_extraction(
            self.ext, user_id=self.user_id, ticker=self.ticker,
            tier=lookup_tier(self.ticker), filer_type=self._filer)
        for r in _rejected_mirrors:  # P3：缺 threshold/source_type 的镜像 → open_question
            self.open_questions.append(r)
        self._filer_open_question(self._filer_src)
        self._apply_key_assumption_rejection()  # P2：四关拒绝规则
        # P5：holding_horizon 必须问用户（不模型猜）→ 未填则 open_question 提示
        if not (self.card_draft and self.card_draft.holding_horizon):
            self.open_questions.append({"field": "holding_horizon",
                "reason": "持仓周期待你确认：long(≥3y) / mid(3m-3y) / trade(≤3m)——影响 mirror 阈值时间尺度"})
        _, _, da = self._agents()
        dlg = generate_dialogue(da, self._ctx_extracted(price_hit), self.cfg)
        a = dlg["text"] if dlg["ok"] and dlg["text"].strip() else self._present_extraction(price_hit)
        a = redline.guard(a)
        self.conversation.append({"role": "assistant", "text": a})
        return self._view(assistant=a)

    def _apply_key_assumption_rejection(self) -> None:
        """P2：key_assumptions 合格判定落地（四条，缺一不合格→open_question，宁缺勿凑）。

        1) LLM 抽取时已自判四关、不过的改写进 ext.open_questions → 合并进 session.open_questions。
        2) 条件3（同义复述）确定性 backstop：与原话高度相似的剔出（is_paraphrase）。
        3) 条件4（不可证伪）确定性 backstop：classify_condition 判非 auto 的假设剔出
           ——其镜像必也非 auto（同主题），无可判定阈值→不可证伪→转 open_question。
           与菜单路径（P4 filter_executable_mirrors）同款 condition_classify，两路径对齐。
        条件 1/2 是纯语义判断，由 LLM 抽取时自判（进 ext.open_questions）。
        """
        if self.ext is not None:
            for oq in (self.ext.open_questions or []):
                self.open_questions.append(
                    {"field": oq.field, "reason": oq.reason, "text": oq.text})
        if self.card_draft is None or self.ext is None:
            return
        from .conditions import is_paraphrase
        from .condition_classify import classify_condition, is_v1_auto, v1_gap_reasons
        raw = (self.ext.holding_reason_raw or "")
        # 条件3：同义复述
        after_c3: list = []
        for a in self.card_draft.key_assumptions:
            if is_paraphrase(a.text, raw):
                self.open_questions.append({
                    "field": "key_assumptions",
                    "reason": "违反条件3（同义复述）：与原话高度相似，疑未多出信息",
                    "text": a.text})
            else:
                after_c3.append(a)
        # 条件4：不可证伪（classify 非 auto → 镜像必也非 auto，无可判定阈值）
        kept: list = []
        for a in after_c3:
            labels = classify_condition(a.text)
            if is_v1_auto(labels):
                kept.append(a)
            else:
                self.open_questions.append({
                    "field": "key_assumptions",
                    "reason": "违反条件4（不可证伪）："
                              + "；".join(v1_gap_reasons(labels) or ["v1 不可自动核对"])
                              + "——改写成能被一手披露击中的可判定事件再填",
                    "text": a.text})
        self.card_draft.key_assumptions = kept

    def turn(self, payload: dict) -> dict:
        text = (payload.get("text") or "").strip()
        self.metrics["turns"] += 1
        if self.stage == S_TICKER_CLARIFY:
            # P0：用户回的话过 SEC 确定性解析；1→用，>1→列候选再问，0→追问，不猜
            self.conversation.append({"role": "user", "text": text})
            matches = resolve_ticker(text or "")
            if len(matches) == 1:
                self.ticker = matches[0].ticker
                return self._after_ticker_resolved(
                    is_price_pattern(self.conversation[0]["text"] if self.conversation else ""))
            self._ticker_candidates = matches
            a = redline.guard(self._ticker_clarify_text())
            return self._view(assistant=a)
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
                # 结构化编辑（右侧确认卡点改，前端发 edits 字段）
                self._apply_edits(edits)
                self.conversation.append({"role": "user", "text": f"（编辑字段：{list(edits)}）"})
                a = redline.guard("（已按修改更新右侧确认卡。点「确认入库」即落库。）")
                self.conversation.append({"role": "assistant", "text": a})
                return self._view(assistant=a)
            # P1：文本输入按 intent 分流（确认→模板逐字保真 / 修改→引导点改 / 提问→应答+拉回确认）
            self.conversation.append({"role": "user", "text": text})
            intent = classify_confirm_intent(text)
            if intent == "confirm":
                a = "好，按上面的做成确认卡（右侧）。可直接点改字段，确认后入库。"
            elif intent == "modify":
                a = self._modify_guide_text()
            else:  # question
                a = self._answer_confirm_question(text)
            a = redline.guard(a)
            self.conversation.append({"role": "assistant", "text": a})
            return self._view(assistant=a)
        return self._view(assistant=redline.guard("（当前阶段无动作。）"))

    def _modify_guide_text(self) -> str:
        """P1：modify 类文本 → 引导用右侧确认卡点改（字段可点改是既定修改流程）。
        自由文本→结构化 edits 的语义解析后置（v0.0.12 不做，避免误改字段）。"""
        return ("要改字段请在右侧确认卡点改（可改：ticker / holding_reason_raw / "
                "entry_anchor / next_verdict / position_cap_tier）。改完点「确认入库」即落库。")

    def _answer_confirm_question(self, text: str) -> str:
        """P1：confirm 阶段提问类应答。

        - 一手披露可得的事实（财报/filing 日）→ fetchers/sec_edgar 实取 + 一手链接（R5）；
          取不到明说「查不到」，不用模型记忆答。
        - 其余 → dialogue LLM 应答（基于卡内容，不编造、不预测、不给建议）。
        答完附复述确认段（模板保真）把用户拉回确认态。
        """
        suffix = "\n\n（确认卡见右侧，点「确认入库」即落库。）"
        if is_factual_fetchable(text):
            from .fetchers.sec_edgar import fetch_latest_filing
            # 财报类问题取最近一份定期/重大事项 filing（10-K/10-Q/20-F/6-K + 修订）
            f = fetch_latest_filing(self.ticker,
                                    form_types=["10-K", "10-Q", "20-F", "6-K",
                                                "10-K/A", "10-Q/A", "20-F/A", "6-K/A"])
            if f is not None:
                return (f"最近一份 SEC filing：{f.form_type}，{f.filed_at.strftime('%Y-%m-%d')}。"
                        f"一手链接：{f.url}\n（下次财报日期 SEC 不预披露，需关注公司 8-K 公告。）" + suffix)
            return (f"查不到 {self.ticker or '该标的'} 的 SEC 财报 filing"
                    f"（CIK 未在 filer_type_lookup，或网络失败）。" + suffix)
        # 非一手披露事实 → dialogue LLM 应答
        _, _, da = self._agents()
        ctx = {
            "stage": "confirm_question", "ticker": self.ticker,
            "user_question": text,
            "card": to_dict(self.card_draft) if self.card_draft else None,
            "instruction": "用户在确认阶段问了一个问题（非确认非修改）。基于已抽取卡内容回答；"
            "不编造、不预测、不给买卖/仓位建议；一手披露事实（财报日等）由系统另路取数，你别猜；"
            "答完不再追问，末尾把用户拉回确认（点确认入库）。",
        }
        dlg = generate_dialogue(da, ctx, self.cfg)
        if dlg["ok"] and dlg["text"].strip():
            return dlg["text"].strip() + suffix
        return "（这条我没法确定。可在右侧确认卡手填，或点「确认入库」。）" + suffix

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
        _, ma, da = self._agents()
        reason = self.conversation[0]["text"] if self.conversation else ""
        r = generate_menu(ma, self.ticker, reason, self.cfg)
        if not r["ok"] or r["menu"] is None:
            self.error = f"{r.get('status')}: {r.get('error','')[:200]}"
            self.stage = S_CONFIRM  # 失败也放行到手填
            a = redline.guard(f"候选菜单生成失败（{r.get('status')}）。可直接在右侧确认卡手填假设/破条件。")
            self.conversation.append({"role": "assistant", "text": a})
            return self._view(assistant=a)
        self.menu = r["menu"]
        # P4：可执行性过滤——不呈现无法自动核对的 B 候选；覆盖率显式告知（PRD §4-A 不静默跳过）
        from .menu import filter_executable_mirrors
        kept_b, self._excluded_mirrors = filter_executable_mirrors(self.menu.candidate_mirrors)
        self.menu.candidate_mirrors = kept_b
        self.stage = S_MENU
        dlg = generate_dialogue(da, self._ctx_menu(), self.cfg)
        a = dlg["text"] if dlg["ok"] and dlg["text"].strip() else self._present_menu()
        a = redline.guard(a)
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
            mirrors=[MirrorSpec(assumption_text=b.assumption, mirror_text=b.mirror_text,
                                threshold=b.threshold, source_type=b.source_type) for b in chosen_b],
            manual_items=self.ext.manual_items if self.ext else [],
            filer_type=self.ext.filer_type if self.ext else None,
            next_verdict=self.ext.next_verdict if self.ext else None,
            entry_anchor=self.ext.entry_anchor if self.ext else None,
        )
        self.ext = new_ext
        self.card_draft, _rejected_mirrors = build_card_from_extraction(
            new_ext, user_id=self.user_id, ticker=self.ticker,
            tier=lookup_tier(self.ticker), filer_type=self._filer)
        for r in _rejected_mirrors:  # P3：缺 threshold/source_type 的镜像 → open_question
            self.open_questions.append(r)
        self._consistency_check(chosen_a, chosen_b)
        self.stage = S_CONFIRM
        _, _, da = self._agents()
        dlg = generate_dialogue(da, self._ctx_confirm(chosen_a, chosen_b), self.cfg)
        fallback = ("做成了确认卡（右侧）。" + (f"⚠️ 一致性存疑：{self.open_questions[-1]['reason']}。" if self.open_questions else "") + "可点改字段，确认后入库。")
        a = dlg["text"] if dlg["ok"] and dlg["text"].strip() else fallback
        a = redline.guard(a)
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
        if "ticker" in edits:
            nt = (edits["ticker"] or "").strip().upper()
            if nt and nt != c.ticker:
                c.ticker = nt
                from .models import FilerType as ModelFilerType
                lookup = _load_filer_lookup()
                ft_str = lookup.get(nt)
                if ft_str:
                    try:
                        c.filer_type = ModelFilerType(ft_str)
                    except ValueError:
                        pass
                t = lookup_tier(nt)
                c.position_cap_tier = t.value if t else None
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
        if "holding_horizon" in edits:
            raw_hh = edits["holding_horizon"]
            hh = (raw_hh or "").strip().lower() if isinstance(raw_hh, str) else ""
            if hh in ("long", "mid", "trade"):
                c.holding_horizon = hh
            elif hh:
                self.open_questions.append({"field": "holding_horizon",
                    "reason": f"holding_horizon 非法值「{hh}」，须 long/mid/trade"})

    def _ticker_clarify_text(self) -> str:
        """S_TICKER_CLARIFY 兜底文案（dialogue LLM 调用失败时用）。
        多候选列出 ticker+全名让用户挑或直接打代码；零候选追问。"""
        cands = self._ticker_candidates or []
        if len(cands) > 1:
            lines = ["没唯一命中，候选（说哪个，或直接打代码）："]
            for i, c in enumerate(cands, 1):
                lines.append(f"  {i}) {c.ticker} — {c.title}")
            return "\n".join(lines)
        return "你持有的是哪只？说代码（如 HSBC/SKHY）或公司名。"

    def _ctx_ticker_clarify(self) -> dict:
        return {
            "stage": "ticker_clarify",
            "ticker": self.ticker or None,
            "candidates": [{"ticker": c.ticker, "title": c.title, "cik": c.cik}
                           for c in (self._ticker_candidates or [])],
            "instruction": "用户说的标的 SEC 官方表无唯一命中。多候选→列 ticker+全名让用户挑；"
                           "零候选→追问代码/公司名。不要替猜（ticker 是事实，P0）。",
        }

    def _ctx_extracted(self, price_hit: bool) -> dict:
        ext = self.ext
        return {
            "stage": "extracted", "ticker": self.ticker,
            "holding_reason_raw": ext.holding_reason_raw,
            "key_assumptions": [a.text for a in (ext.key_assumptions or [])],
            "mirrors": [m.mirror_text for m in (ext.mirrors or [])],
            "entry_anchor": ({"type": ext.entry_anchor.anchor_type, "value": ext.entry_anchor.anchor_value, "note": ext.entry_anchor.note} if ext.entry_anchor else None),
            "next_verdict": ({"event": ext.next_verdict.event, "date": ext.next_verdict.date} if ext.next_verdict else None),
            "manual_items": [{"text": m.text, "reason": m.reason} for m in (ext.manual_items or [])],
            "price_pattern": price_hit,
            "instruction": "复述买入逻辑原话 + 抽到的假设/镜像 + 估值锚/裁判日；价格图形型说透为什么核不了、能改成什么样才核得了；问用户确认或回「无法确定」要候选菜单",
        }

    def _ctx_menu(self) -> dict:
        m = self.menu
        excl = getattr(self, "_excluded_mirrors", []) or []
        return {
            "stage": "menu", "ticker": self.ticker,
            "candidates_A_assumptions": list(m.candidate_assumptions),
            "candidates_B_mirrors": [{"assumption": b.assumption, "mirror_text": b.mirror_text} for b in m.candidate_mirrors],
            "excluded_count": len(excl),
            "excluded_reasons": sorted({r for x in excl for r in x.get("reasons", [])}),
            "instruction": "介绍候选菜单（A 你信什么 / B 破什么，每条我能从公告核对）；"
            "若 excluded_count>0，**必须先说透**「原本 N 个破条件方向，M 个当前系统无法自动核对，已排除（原因）」"
            "——覆盖率显式呈现（PRD §4-A），不静默跳过。让用户在右侧勾选后提交",
        }

    def _ctx_confirm(self, chosen_a, chosen_b) -> dict:
        return {
            "stage": "confirm_card", "ticker": self.ticker,
            "picked_assumptions": chosen_a,
            "picked_mirrors": [{"assumption": b.assumption, "mirror_text": b.mirror_text} for b in chosen_b],
            "open_questions": self.open_questions,
            "instruction": "告知做成确认卡（右侧可点改）；若信的假设与勾的破条件不对应，说透为什么这是一致性存疑（但默认处理仍执行）",
        }

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
        lines = ["给你候选，挑就行（选一次填两槽）："]
        excl = getattr(self, "_excluded_mirrors", None) or []
        if excl:
            n_excl = len(excl)
            n_total = n_excl + len(m.candidate_mirrors)
            reasons = " / ".join(sorted({r for x in excl for r in x.get("reasons", [])}))
            lines.append(f"⚠️ 原本 {n_total} 个破条件方向，其中 {n_excl} 个当前系统无法自动核对，"
                         f"已排除（{reasons}）。剩下的可勾选。")
        lines.append("A. 你信什么（右侧可多选）：")
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


def new_session(user_id: str, cfg: dict) -> EntrySession:
    return EntrySession(user_id=user_id, ticker="", cfg=cfg)  # ticker 由 start 从一句话抽取/override 解析


__all__ = ["EntrySession", "new_session", "S_CONFIRMED"]
