"""拉 SEC EDGAR submissions → evals/filer_type_lookup.yaml（CIK + form 列表 + filer_type + 抓取时间）。

R8（修订）：filer_type GT 来源 = SEC EDGAR submissions API（外部权威数据），不手标。
用户只手填 entry_anchor。next_verdict 机械提取。manual_items 规则推导（classify_condition）。

坑：SEC 强制 User-Agent「姓名 邮箱」否则 403。设 env SEC_USER_AGENT。
限速 0.15s/请求，不并发。可复用 pre-market-briefing/src/fetchers/sec_edgar.py（待 clone, B1）。

输出 evals/filer_type_lookup.yaml，harness 读它做 filer_type GT（不从 ground_truth.yaml 手标）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals" / "filer_type_lookup.yaml"
TICKERS = ["NVDA", "VEEV", "MCO", "GOOGL", "CGNX", "NOW", "NFLX", "CRM",
           "FIS", "FDS", "HSBC", "BRK.B", "QQQ"]
UA = os.environ.get("SEC_USER_AGENT", "Thesis-Watch thesis-guard@example.com")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
FUND_FORMS = {"N-CSR", "N-PORT", "N-CEN", "NSAR", "485", "497", "24F-2"}


def fetch_cik_map() -> dict:
    r = httpx.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()  # {0: {cik_str, ticker, title}, ...}
    return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}


def fetch_forms(cik: int) -> list[str]:
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = httpx.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = list(recent.get("form", []))
    return forms


def classify(forms: list[str]) -> str | None:
    fs = set(forms)
    if "10-K" in fs:
        return "domestic_10k"
    if "20-F" in fs or "6-K" in fs:
        return "foreign_issuer_20f_6k"
    if fs & FUND_FORMS and not ("10-K" in fs or "20-F" in fs):
        return "etf_fund"
    if not forms:
        return None
    return None  # unclear


def main() -> int:
    if not os.environ.get("SEC_USER_AGENT"):
        print("⚠️ 未设 SEC_USER_AGENT（格式「姓名 邮箱」），用默认——SEC 可能 403")
    print("拉 company_tickers.json ...")
    try:
        cik_map = fetch_cik_map()
    except Exception as e:  # noqa: BLE001
        print(f"❌ 拉 CIK map 失败（SEC 不可达？B1）：{type(e).__name__}: {e}")
        return 1

    out = {"fetched_at": "2026-08-02", "user_agent": UA, "source": "SEC EDGAR submissions API", "tickers": {}}
    for t in TICKERS:
        candidates = [t, t.replace(".", "-")] if "." in t else [t]
        cik = None
        for c in candidates:
            cik = cik_map.get(c.upper())
            if cik:
                break
        if not cik:
            out["tickers"][t] = {"cik": None, "filer_type": None, "forms": [],
                                 "note": f"ticker 未在 company_tickers.json（试 {'/'.join(candidates)}）"}
            print(f"  {t}: CIK 未找到")
            continue
        try:
            forms = fetch_forms(cik)
            ft = classify(forms)
            out["tickers"][t] = {"cik": cik, "filer_type": ft,
                                 "forms": sorted(set(forms))[:20],
                                 "note": "" if ft else "form 列表不明确，待人工确认"}
            print(f"  {t}: CIK={cik} filer_type={ft} (forms: {sorted(set(forms))[:5]}...)")
        except Exception as e:  # noqa: BLE001
            out["tickers"][t] = {"cik": cik, "filer_type": None, "forms": [],
                                 "note": f"submissions 拉取失败: {type(e).__name__}: {e}"}
            print(f"  {t}: submissions 失败 {type(e).__name__}: {e}")
        time.sleep(0.15)
    OUT.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
