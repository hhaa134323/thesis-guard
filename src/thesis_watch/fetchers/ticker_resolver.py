"""SEC 官方 ticker / 公司名解析器（确定性，不经过 LLM）。

数据源：SEC 官方 company_tickers.json
（https://www.sec.gov/files/company_tickers.json，全量 US 上市公司 ticker+CIK+title）。
首次拉取缓存到本地 data/company_tickers.json，超过 TTL（默认 30 天）再拉；
远程失败回退陈旧缓存（好过空）。SEC fair-access：User-Agent 须含真实联系邮箱，
复用 sec_edgar.USER_AGENT（env THESIS_SEC_USER_AGENT）。

resolve(query) 两档（调用方据档决定：1→用 / >1→问选 / 0→问，不允许猜）：
- 精确 ticker：整串 == 某 ticker（含点如 BRK.B）
- 公司名模糊匹配：difflib top 3（带 ticker / 全名 / CIK）
- 无匹配：空列表

设计理由（P0 schema 审计）：ticker 是「有唯一正确答案的事实」，
不该交给 LLM 猜——glm 把「SK海力士」猜成 SKHCF（Sonic Healthcare，澳洲 OTC），
正确是 SKHY（SK Hynix ADR，CIK 2120882）。改为查 SEC 官方表；查不到就问用户，宁缺勿猜。

**不做句中 ticker 词扫描**——论据里的英文词（AI / HBM / capex / FCF…）凑巧匹配真实
SEC ticker 会误命中（实测「我持有SK海力士，因为 AI 算力…HBM 需求…」被误判成
AI / HBM 候选让用户选）。故只认整串精确 + 英文公司名模糊；中文公司名查不到 SEC 英文 title → [] → 问用户。
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

# CJK 表意字符范围（_clean_fuzzy_query 去首尾 CJK 用，让嵌在中文句里的英文公司名露出来）。
_CJK_IDEO_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))


@dataclass
class TickerMatch:
    ticker: str
    title: str
    cik: str  # 零填充 10 位

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "title": self.title, "cik": self.cik}


# 进程内库缓存（首次 resolve 加载；reset() 清空供测试/强刷用）。
_DB: list[dict] | None = None  # [{"ticker","title","cik"}]


def _is_cjk_ideo(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CJK_IDEO_RANGES)


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


def _fuzzy(query_lc: str, limit: int = 3, threshold: float = 0.5) -> list[dict]:
    from difflib import SequenceMatcher

    scored: list[tuple[float, dict]] = []
    for r in _load_db():
        title_lc = r["title"].lower()
        if not title_lc:
            continue
        if query_lc in title_lc or title_lc in query_lc:
            score = 0.9
        else:
            score = SequenceMatcher(None, query_lc, title_lc).ratio()
        if score >= threshold:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def _clean_fuzzy_query(query: str) -> str:
    """去首尾 CJK 表意字符，让嵌在中文句里的英文公司名露出来（如「我持有Apple，看好」→Apple）。"""
    s = query
    while s and _is_cjk_ideo(s[0]):
        s = s[1:]
    while s and _is_cjk_ideo(s[-1]):
        s = s[:-1]
    return s.strip().lower()


def resolve(query: str) -> list[TickerMatch]:
    """把用户输入解析为 ticker 候选。

    - 整串 == 某 ticker（含点如 BRK.B）→ 1 条
    - 公司名模糊（英文）→ top 3
    - 无匹配 → []（调用方必须问用户，不允许猜）

    不做句中 ticker 词扫描——论据里的英文词（AI/HBM/capex…）凑巧匹配真实 ticker 会误命中。
    """
    q = (query or "").strip()
    if not q:
        return []
    if not _load_db():
        return []  # 无库（无网络 + 无缓存）→ 问用户，不猜

    # 1) 整串精确 ticker
    r = _by_ticker(q.upper())
    if r:
        return [TickerMatch(r["ticker"], r["title"], r["cik"])]

    # 2) 公司名模糊（英文；中文公司名查不到 SEC 英文 title → []，问用户）
    fq = _clean_fuzzy_query(q)
    if len(fq) >= 3:  # ≥3 防「SK海力士」清出 "sk" 误模糊命中含 sk 的 title
        hits = _fuzzy(fq)
        if hits:
            return [TickerMatch(h["ticker"], h["title"], h["cik"]) for h in hits]

    return []


__all__ = ["TickerMatch", "resolve", "reset"]
