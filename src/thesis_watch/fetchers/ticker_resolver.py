"""SEC 官方 ticker 解析器（确定性，不经过 LLM）。

数据源：SEC 官方 company_tickers.json
（https://www.sec.gov/files/company_tickers.json，全量 US 上市公司 ticker+CIK+title）。
首次拉取缓存到本地 data/company_tickers.json，超过 TTL（默认 30 天）再拉；
远程失败回退陈旧缓存（好过空）。SEC fair-access：User-Agent 须含真实联系邮箱，
复用 sec_edgar.USER_AGENT（env THESIS_SEC_USER_AGENT）。

resolve(query) 一档（调用方据档决定：1→用 / 0→问用户，不允许猜）：
- 精确 ticker：整串 == 某 ticker（含点如 BRK.B）→ 1 条
- 无匹配：空列表

Phase 2 重构（2026-08-03）：删 fuzzy 子串 + 公司名模糊匹配（Bug #3 根因——MCO
mid-word 误命中 EMCOR/Amcor/Kimco）。中文公司名 / 英文公司名翻译由 agent loop 的
LLM 处理（汇丰→HSBC），resolver 只认整串精确英文 ticker。token 词扫描已在 v0.0.14 删。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 复用 sec_edgar 的 UA env（THESIS_SEC_USER_AGENT）——同一 fetcher 族、同一 SEC fair-access 约定。
from .sec_edgar import USER_AGENT

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_DEFAULT_CACHE = str(Path(__file__).resolve().parents[3] / "data" / "company_tickers.json")
_CACHE_TTL_DAYS = 30


def _cache_path() -> Path:
    """缓存路径（调用时读 env，便于测试 monkeypatch 与部署中立覆盖）。"""
    return Path(os.environ.get("THESIS_TICKER_CACHE", _DEFAULT_CACHE))


def _cache_url() -> str:
    return os.environ.get("THESIS_TICKER_URL", COMPANY_TICKERS_URL)


def _cache_ttl_days() -> int:
    try:
        return int(os.environ.get("THESIS_TICKER_CACHE_TTL_DAYS", str(_CACHE_TTL_DAYS)))
    except ValueError:
        return _CACHE_TTL_DAYS


@dataclass
class TickerMatch:
    ticker: str
    title: str
    cik: str  # 零填充 10 位

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "title": self.title, "cik": self.cik}


# 进程内库缓存（首次 resolve 加载；reset() 清空供测试/强刷用）。
_DB: list[dict] | None = None  # [{"ticker","title","cik"}]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_fresh() -> bool:
    p = _cache_path()
    if not p.exists():
        return False
    age = _now() - datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
    return age.days < _cache_ttl_days()


def _parse(data: Any) -> list[dict]:
    """SEC company_tickers.json（{"0":{cik_str,ticker,title},...}）→ [{"ticker","title","cik"}]。"""
    out: list[dict] = []
    if not isinstance(data, dict):
        return out
    for v in data.values():
        if not isinstance(v, dict):
            continue
        t = (v.get("ticker") or "").strip().upper()
        title = (v.get("title") or "").strip()
        cik = v.get("cik_str")
        if t and cik is not None:
            out.append({"ticker": t, "title": title, "cik": str(cik).zfill(10)})
    return out


def _fetch_remote() -> list[dict] | None:
    import requests

    try:
        resp = requests.get(_cache_url(), headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    rows = _parse(data)
    if not rows:
        return None
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # 缓存写入失败不阻断——内存已加载
    return rows


def _load_db() -> list[dict]:
    """加载 ticker 库：新鲜缓存优先 → 远程拉取 → 陈旧缓存兜底 → 空（调用方问用户）。"""
    global _DB
    if _DB is not None:
        return _DB
    p = _cache_path()
    rows: list[dict] | None = None
    if _cache_fresh():
        try:
            rows = _parse(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            rows = None
    if not rows:
        rows = _fetch_remote()
    if not rows and p.exists():  # 远程失败 → 回退陈旧缓存
        try:
            rows = _parse(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            rows = None
    _DB = rows or []
    return _DB


def reset() -> None:
    """清进程内库缓存（测试 / 强制重读缓存文件用）。"""
    global _DB
    _DB = None


def _by_ticker(ticker: str) -> dict | None:
    for r in _load_db():
        if r["ticker"] == ticker:
            return r
    return None


def resolve(query: str) -> list[TickerMatch]:
    """把用户输入解析为 ticker 候选（**精确整串匹配 only**）。

    - 整串 == 某 ticker（含点如 BRK.B）→ 1 条
    - 无匹配 → []（调用方必须问用户，不允许猜）

    Phase 2：删 fuzzy 子串/公司名匹配（Bug #3 根因）。中文公司名 / 英文公司名
    由 agent loop 的 LLM 翻译成英文 ticker 后再调本函数（resolver 只认整串精确 ticker）。
    不做句中 ticker 词扫描——论据里的英文词（AI/HBM/capex…）凑巧匹配真 ticker 会误命中。
    """
    q = (query or "").strip()
    if not q:
        return []
    if not _load_db():
        return []  # 无库（无网络 + 无缓存）→ 问用户，不猜
    r = _by_ticker(q.upper())
    if r:
        return [TickerMatch(r["ticker"], r["title"], r["cik"])]
    return []


__all__ = ["TickerMatch", "resolve", "reset"]
