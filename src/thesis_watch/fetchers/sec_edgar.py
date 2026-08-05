"""SEC EDGAR filings fetcher（从 pre-market-briefing src/fetchers/sec_edgar.py 搬 + 适配 thesis-guard）。

按 filer_type 路由 form types：外国发行人（20-F/6-K）主渠道 6-K，**不沿用本土「6-K 降级」**。
FilingEvent 含 ticker/form_type/item/title/url/filed_at。8-K 按 item 拆（5.02=高管离职 / 4.02=重述 / 2.02=财报）。

SEC fair-access：User-Agent 走 env THESIS_SEC_USER_AGENT（须含真实联系邮箱）。
依赖 requests。SEC 限速 10 req/s，本模块 sleep 150ms/请求。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from .base import BaseFetcher, FetcherRegistry

# SEC fair-access 要求描述性 UA + 联系邮箱；env 覆盖（公开部署前换 generic/作者邮箱）
USER_AGENT = os.environ.get("THESIS_SEC_USER_AGENT", "ThesisWatch/0.0 2248789162@qq.com")
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
REQUEST_DELAY_SEC = 0.15

FORM_TYPE_LABELS: dict[str, str] = {
    "8-K": "8-K 重大事项", "10-K": "10-K 年报", "10-K/A": "10-K/A 年报修订",
    "10-Q": "10-Q 季报", "10-Q/A": "10-Q/A 季报修订", "4": "Form 4 内部人交易",
    "20-F": "20-F 外国发行人年报", "20-F/A": "20-F/A 修订",
    "6-K": "6-K 外国发行人重大事项", "6-K/A": "6-K/A 修订",
}


def forms_for_filer(filer_type) -> tuple[str, ...]:
    """按申报方类型路由 SEC 表单。外国发行人以 6-K 为主渠道（不沿用本土 6-K 降级）。

    etf_fund：v1 无公司层面 SEC 自动核对（无 10-K/20-F）→ 全 manual（PRD §9 / data-sources）。
    """
    ft = filer_type.value if hasattr(filer_type, "value") else str(filer_type)
    if ft == "foreign_issuer_20f_6k":
        return ("8-K", "6-K", "6-K/A", "20-F", "20-F/A", "4")
    if ft == "domestic_10k":
        return ("8-K", "10-K", "10-K/A", "10-Q", "10-Q/A", "4")
    if ft == "etf_fund":
        return ()  # ETF v1 全 manual，不自动核对
    return ("8-K", "10-K", "10-Q", "4")  # other / 兜底


@dataclass
class FilingEvent:
    ticker: str
    form_type: str
    item: str | None
    title: str
    url: str
    filed_at: datetime


_ticker_to_cik_cache: dict[str, str] | None = None


def _load_ticker_map(user_agent: str) -> dict[str, str]:
    """ticker → CIK（零填充 10 位）。

    CIK 主源 filer_type_lookup.yaml（`scripts/fetch_filer_type.py` 已从 SEC 拉取缓存，
    含每 ticker 的 cik）；YAML 缺失的 ticker 用 SEC 全量 company_tickers.json 补齐
    （一次 fetch，进程内缓存；fetch 失败 → 只用 YAML，需先跑 fetch_filer_type 入表）。
    路径 env THESIS_FILER_LOOKUP 覆盖（与 entry_loop 同一变量）。
    """
    global _ticker_to_cik_cache
    if _ticker_to_cik_cache is not None:
        return _ticker_to_cik_cache
    import yaml
    from pathlib import Path

    default_path = Path(__file__).resolve().parents[3] / "evals" / "filer_type_lookup.yaml"
    p = Path(os.environ.get("THESIS_FILER_LOOKUP", str(default_path)))
    mapping: dict[str, str] = {}
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for t, v in (data.get("tickers") or {}).items():
                cik = (v or {}).get("cik") if isinstance(v, dict) else None
                if cik:
                    mapping[str(t).upper()] = str(cik).zfill(10)
        except Exception:
            pass  # lookup 损坏 → 空映射（所有 ticker 跳过）

    # Fallback: SEC 官方全量 ticker→CIK（company_tickers.json）
    # YAML 缺某 ticker 时用全量表补齐（一次 fetch，进程内缓存；fetch 失败 → 只用 YAML，当前行为）
    try:
        time.sleep(REQUEST_DELAY_SEC)
        resp = requests.get(COMPANY_TICKERS_URL, headers={"User-Agent": user_agent}, timeout=15)
        resp.raise_for_status()
        for _, info in (resp.json() or {}).items():
            t = (info.get("ticker") or "").upper()
            c = str(info.get("cik_str", "")).zfill(10)
            if t and c and t not in mapping:
                mapping[t] = c
    except Exception:
        pass  # fallback fetch 失败 → 只用 YAML（当前行为）
    _ticker_to_cik_cache = mapping
    return mapping


def _submissions_url(cik_padded: str) -> str:
    return "https://data.sec.gov/submissions/CIK" + cik_padded + ".json"


def _filing_index_url(cik_padded: str, accession_no: str) -> str:
    """canonical filing-index URL（string-concat，避占位符）。"""
    cik_int = str(int(cik_padded))
    acc_no_dash = accession_no.replace("-", "")
    return ("https://www.sec.gov/Archives/edgar/data/"
            + cik_int + "/" + acc_no_dash + "/" + accession_no + "-index.htm")


def _parse_filing_time(acceptance_dt: str, filing_date: str) -> datetime | None:
    if acceptance_dt:
        try:
            dt = datetime.fromisoformat(acceptance_dt.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    if filing_date:
        try:
            return datetime.strptime(filing_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _build_title(form_type: str, desc: str) -> str:
    label = FORM_TYPE_LABELS.get(form_type, form_type)
    desc = (desc or "").strip()
    return label + " · " + desc if desc else label


def fetch_filings(tickers: list[str], lookback_hours: int,
                  user_agent: str | None = None,
                  form_types: list[str] | tuple[str, ...] | None = None) -> list[FilingEvent]:
    """拉给定 tickers 在 lookback_hours 窗口内的 SEC filings。

    per-ticker 失败静默跳过（降级）；仅初始 ticker-map 拉取失败抛错（无它啥都干不了）。
    """
    if not tickers:
        return []
    ua = user_agent or USER_AGENT
    wanted = set(form_types) if form_types is not None else {"8-K", "10-K", "10-Q", "4"}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    try:
        ticker_map = _load_ticker_map(ua)
    except Exception as e:
        raise RuntimeError("SEC ticker map fetch failed: " + str(e)) from e

    events: list[FilingEvent] = []
    for ticker in tickers:
        ticker_u = ticker.upper()
        cik = ticker_map.get(ticker_u)
        if cik is None:
            continue
        try:
            time.sleep(REQUEST_DELAY_SEC)
            resp = requests.get(_submissions_url(cik), headers={"User-Agent": ua}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue  # per-ticker 降级
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accs = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        acceptances = recent.get("acceptanceDateTime", [])
        descs = recent.get("primaryDocDescription", [])
        items_list = recent.get("items", [])
        for i, form in enumerate(forms):
            if form not in wanted:
                continue
            acc_no = accs[i] if i < len(accs) else ""
            filed_date = dates[i] if i < len(dates) else ""
            acc_time = acceptances[i] if i < len(acceptances) else ""
            desc = descs[i] if i < len(descs) else ""
            items_raw = items_list[i] if i < len(items_list) else ""
            filed_at = _parse_filing_time(acc_time, filed_date)
            if filed_at is None or filed_at < cutoff:
                continue
            url = _filing_index_url(cik, acc_no)
            title = _build_title(form, desc)
            if form == "8-K":
                items = [s.strip() for s in str(items_raw).split(",") if s.strip()] or [None]
                for item in items:
                    events.append(FilingEvent(ticker_u, form, item, title, url, filed_at))
            else:
                events.append(FilingEvent(ticker_u, form, None, title, url, filed_at))
    events.sort(key=lambda e: e.filed_at, reverse=True)
    return events


def fetch_latest_filing(ticker: str, user_agent: str | None = None,
                        form_types: list[str] | tuple[str, ...] | None = None
                        ) -> FilingEvent | None:
    """取某 ticker 最近一份 SEC filing（P1：confirm 阶段一手事实问答用，R5 附一手链接）。

    命中 filer_type_lookup 的 CIK → 拉 submissions recent → 取 form_types 内最新一条
    （不限 lookback；recent 本身倒序）。form_types=None → 任意表单。
    无 CIK / 网络失败 → None（调用方须明说「查不到」，不猜，R5）。
    """
    if not ticker:
        return None
    ua = user_agent or USER_AGENT
    wanted = set(form_types) if form_types is not None else None
    try:
        ticker_map = _load_ticker_map(ua)
    except Exception:
        return None
    cik = ticker_map.get(ticker.upper())
    if cik is None:
        return None
    try:
        resp = requests.get(_submissions_url(cik), headers={"User-Agent": ua}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    descs = recent.get("primaryDocDescription", [])
    best: FilingEvent | None = None
    for i, form in enumerate(forms):
        if wanted is not None and form not in wanted:
            continue
        filed_date = dates[i] if i < len(dates) else ""
        acc_no = accs[i] if i < len(accs) else ""
        desc = descs[i] if i < len(descs) else ""
        filed_at = _parse_filing_time("", filed_date)  # 用 filingDate（acceptance 无精确到时）
        if filed_at is None:
            continue
        if best is None or filed_at > best.filed_at:
            url = _filing_index_url(cik, acc_no)
            title = _build_title(form, desc)
            best = FilingEvent(ticker.upper(), form, None, title, url, filed_at)
    return best


def fetch_filing_history(ticker: str, form_type: str | None = None,
                         count: int = 10, user_agent: str | None = None) -> list[FilingEvent]:
    """取某 ticker 最近 N 份 SEC filing（不限 lookback 窗口）。

    与 fetch_latest_filing 区别：返回多条，不限时间窗口。用于 agent 查历史 filing
    （如估值基线需要的 2 年前 10-K）。form_type=None → 任意表单；按 filed_at 倒序取前 N。
    无 CIK / 网络失败 / 空结果 → []（R5 不编造，调用方须明说「查不到」）。
    """
    if not ticker:
        return []
    n = 10 if count is None else count
    if n <= 0:
        return []
    ua = user_agent or USER_AGENT
    try:
        ticker_map = _load_ticker_map(ua)
    except Exception:
        return []
    cik = ticker_map.get(ticker.upper())
    if cik is None:
        return []
    try:
        resp = requests.get(_submissions_url(cik), headers={"User-Agent": ua}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    descs = recent.get("primaryDocDescription", [])
    events: list[FilingEvent] = []
    for i, form in enumerate(forms):
        if form_type is not None and form != form_type:
            continue
        filed_date = dates[i] if i < len(dates) else ""
        acc_no = accs[i] if i < len(accs) else ""
        desc = descs[i] if i < len(descs) else ""
        filed_at = _parse_filing_time("", filed_date)  # 用 filingDate（与 fetch_latest_filing 一致）
        if filed_at is None:
            continue
        url = _filing_index_url(cik, acc_no)
        title = _build_title(form, desc)
        events.append(FilingEvent(ticker.upper(), form, None, title, url, filed_at))
    events.sort(key=lambda e: e.filed_at, reverse=True)
    return events[:n]


# --- BaseFetcher subclass + 注册（Stage 2 数据源抽象层；base.py 定义接口/注册表） ---
def _filing_event_to_dict(ev: "FilingEvent") -> dict:
    """FilingEvent -> plain dict（BaseFetcher.fetch 统一返回 list[dict]；字段/值与
    orchestrator 旧 check_filing 内联构造一致，行为不变）。"""
    return {
        "ticker": ev.ticker,
        "form_type": ev.form_type,
        "filed_at": ev.filed_at.date().isoformat() if hasattr(ev.filed_at, "date") else str(ev.filed_at),
        "url": ev.url,
        "title": ev.title,
    }


class SecFetcher(BaseFetcher):
    """SEC EDGAR fetcher（BaseFetcher subclass，注册名 "sec"）。

    包装 sec_edgar 现有确定性逻辑（forms_for_filer / fetch_filings / fetch_latest_filing），
    不重写取数。fetch() 返回 list[dict]（空 = 查不到，R5 不编造）；首条 = 最近一份。
    orchestrator.check_filing 经 FetcherRegistry.get("sec") 取此实例，行为不变（与
    form_type 过滤兼容）。Stage 2 接行情 / Yahoo RSS 等新数据源时，写新 subclass +
    FetcherRegistry.register 即可。
    """

    name = "sec"

    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        """取 ticker 最近一份 SEC filing（可选 form_type 过滤）。

        kwargs:
            form_type: str | None —— 按表单类型筛（如 "10-K"/"10-Q"/"20-F"/"6-K"/"8-K"）；
                       不传 → 任意表单最近一份（行为不变，与 check_filing 不传 form_type 一致）。
        返回 list[dict]：空 = 查不到；非空首条 = 最近一份
            [{ticker, form_type, filed_at, url, title}]。
        """
        form_type = kwargs.get("form_type")
        form_types = [form_type] if form_type else None
        ev = fetch_latest_filing(ticker, form_types=form_types)
        if ev is None:
            return []
        return [_filing_event_to_dict(ev)]

    def fetch_history(self, ticker: str, form_type: str | None = None,
                      count: int = 10) -> list[dict]:
        """取 ticker 最近 N 份 SEC filing（可选 form_type 过滤），返回 list[dict]。

        与 fetch() 区别：返回多条（不限 lookback / 不限最近一份），供 agent 查历史 filing
        （如 2 年前 10-K）。kwargs 同 fetch() + count；空 = 查不到（R5 不编造）。
        """
        events = fetch_filing_history(ticker, form_type=form_type, count=count)
        return [_filing_event_to_dict(ev) for ev in events]

    # --- 透传 sec_edgar 现有能力（Stage 2 路由扩展用；check_filing 仅用 fetch） ---
    @staticmethod
    def forms_for_filer(filer_type) -> tuple[str, ...]:
        return forms_for_filer(filer_type)

    @staticmethod
    def fetch_filings(tickers, lookback_hours, user_agent=None, form_types=None) -> list[FilingEvent]:
        return fetch_filings(tickers, lookback_hours, user_agent=user_agent, form_types=form_types)


FetcherRegistry.register("sec", SecFetcher)


__all__ = ["FilingEvent", "fetch_filings", "fetch_latest_filing", "fetch_filing_history",
           "forms_for_filer", "FORM_TYPE_LABELS", "USER_AGENT", "SecFetcher"]
