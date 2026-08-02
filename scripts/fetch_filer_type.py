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
           "FIS", "FDS", "HSBC", "BRK.B", "QQQ", "SPGI", "GDXU"]
# EDGAR 查不到独立申报主体的已知 ETF/ETN → 直接标 etf_fund + note（不留空）
ETF_FALLBACK = {
    "GDXU": "杠杆 ETN（MicroSectors Gold Miners 3X），申报主体为发行商，v1 不支持自动核对",
}
def _load_dotenv() -> None:
    """用标准库解析仓库根 .env（不引入 python-dotenv）；仅补未设的环境变量。"""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()
UA = os.environ.get("SEC_USER_AGENT")  # 真实「姓名 邮箱」；未设 → main() 报错退出（不硬编码，R9 脱敏）
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"} if UA else {}
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
    if not UA:
        sys.exit("❌ 未设 SEC_USER_AGENT 环境变量。SEC EDGAR 要求真实「姓名 邮箱」作 User-Agent，"
                 "占位符会被限流/403。设 SEC_USER_AGENT='YourName your@email.com' 后重试。"
                 "（不要把真实邮箱硬编码进仓库——R9 脱敏）")
    print(f"拉 company_tickers.json ...")
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
            if t in ETF_FALLBACK:
                out["tickers"][t] = {"cik": None, "filer_type": "etf_fund", "forms": [],
                                     "note": f"EDGAR 无 CIK（{ETF_FALLBACK[t]}）"}
                print(f"  {t}: 无 CIK → etf_fund（{ETF_FALLBACK[t]}）")
            else:
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
