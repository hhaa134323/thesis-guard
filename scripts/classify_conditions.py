"""跑 classify_condition 在 13 只真实持仓的全部破局条件上，输出分类表 → docs/condition-classification.md。

作者人工确认后才固化（进 GT）。分类错则改 condition_classify.py 规则后重跑。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from thesis_watch.condition_classify import (  # noqa: E402
    classify_condition,
    is_v1_auto,
    v1_gap_reason,
)

THESIS_DIR = ROOT / "assets" / "notion" / "thesis"
TICKERS = ["NVDA", "VEEV", "MCO", "GOOGL", "CGNX", "NOW", "NFLX", "CRM",
           "FIS", "FDS", "HSBC", "BRK.B", "QQQ"]


def load_break_conditions(ticker: str) -> str:
    p = THESIS_DIR / f"{ticker}.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
    else:
        schema = THESIS_DIR / "00_schema_and_small_rows.md"
        text = schema.read_text(encoding="utf-8")
        i = text.find(f"## {ticker}")
        if i < 0:
            return ""
        j = text.find("\n## ", i + 3)
        text = text[i: j if j > 0 else len(text)]
    h = "## Thesis 破的条件"
    i = text.find(h)
    if i < 0:
        return ""
    start = i + len(h)
    j = text.find("\n## ", start)
    return text[start: j if j > 0 else len(text)].strip()


def split_conditions(text: str) -> list[str]:
    """粗粒度切分（①②③④⑤ • ； \n）。切分不完美，作者复核时合并/拆分。"""
    if not text:
        return []
    parts = re.split(r"[①②③④⑤⑥⑦⑧⑨⑩•；;\n]", text)
    out = []
    for p in parts:
        p = p.strip(" -—·：:（）()，,。 \t")
        if len(p) > 4:
            out.append(p)
    return out


def main() -> None:
    rows: list[tuple] = []
    for t in TICKERS:
        bc = load_break_conditions(t)
        if not bc:
            rows.append((t, "(台账无破条件)", "—", None, "无"))
            continue
        conds = split_conditions(bc)
        if not conds:
            rows.append((t, bc[:80], "—", None, "切分为空（作者手查）"))
            continue
        for cond in conds:
            info = classify_condition(cond)
            auto = is_v1_auto(info) if info else False
            if info is None:
                reason = "否定从句，跳过分类"
            elif auto:
                reason = "v1 可自动核对"
            else:
                reason = v1_gap_reason(info)
            rows.append((t, cond[:90], info.value if info else "(negation)", auto, reason))

    lines = [
        "# 破局条件分类表（v0.2 规则近似，**待作者人工确认后固化**）",
        "",
        "> 由 `condition_classify.classify_condition` 跑 13 只真实持仓的全部破局条件。",
        "> 规则近似（关键词优先级），**必须作者逐条人工确认**后才进 GT。",
        "> 确认后：v1 可自动（`xbrl_structured` / `press_release_text`）→ 不进 manual_items；其余 → manual_items。",
        "> 分类错 → 改 `src/thesis_watch/condition_classify.py` 规则后重跑本表（`scripts/classify_conditions.py`）。",
        "",
        "| ticker | 条件原文（截断 90 字） | 分类 InfoType | v1 可自动 | 理由 |",
        "|---|---|---|---|---|",
    ]
    for t, cond, info, auto, reason in rows:
        lines.append(f"| {t} | {cond} | {info} | {auto} | {reason} |")

    out_path = ROOT / "docs" / "condition-classification.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(rows)} 条件)")
    # 控制台摘要：各 InfoType 计数 + v1 auto 占比
    from collections import Counter
    cnt = Counter(r[2] for r in rows)
    auto_n = sum(1 for r in rows if r[3])
    print(f"分类分布: {dict(cnt)}")
    print(f"v1 可自动: {auto_n}/{len(rows)} = {auto_n/len(rows):.0%}")


if __name__ == "__main__":
    main()
