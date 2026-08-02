"""跑 classify_condition 在 13(+2) 只持仓的全部破局条件上，输出分段列表 → docs/condition-classification.md。

v0.3（2026-08-02）：_split_conditions 改进（剥离结构行+condition_tier+续行合并）；
classify_condition multi-label；不截断（输出全文）；分段列表；NOW「下滱」[sic]。
作者人工确认后才固化（进 GT）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from thesis_watch.condition_classify import (  # noqa: E402
    _split_conditions,
    classify_condition,
    is_v1_auto,
    v1_gap_reasons,
)

THESIS_DIR = ROOT / "assets" / "notion" / "thesis"
TICKERS = ["NVDA", "VEEV", "MCO", "GOOGL", "CGNX", "NOW", "NFLX", "CRM",
           "FIS", "FDS", "HSBC", "BRK.B", "QQQ", "SPGI", "GDXU"]


def load_break_conditions(ticker: str) -> str:
    p = THESIS_DIR / f"{ticker}.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
    else:
        schema = THESIS_DIR / "00_schema_and_small_rows.md"
        if not schema.exists():
            return ""
        s = schema.read_text(encoding="utf-8")
        i = s.find(f"## {ticker}")
        if i < 0:
            return ""
        j = s.find("\n## ", i + 3)
        text = s[i: j if j > 0 else len(s)]
    h = "## Thesis 破的条件"
    i = text.find(h)
    if i < 0:
        return ""
    start = i + len(h)
    j = text.find("\n## ", start)
    return text[start: j if j > 0 else len(text)].strip()


def main() -> None:
    lines = [
        "# 破局条件分类表（v0.3，**待作者人工确认后固化**）",
        "",
        "> 由 `condition_classify.classify_condition`（multi-label）+ `_split_conditions`（剥离结构行+condition_tier+续行合并）跑。",
        "> **不截断**（输出全文）——作者逐条确认对象必须是完整原文。",
        "> 确认后：v1 可自动（`xbrl_structured` / `press_release_text`）→ 不进 manual_items；其余 → manual_items。",
        "> 分类错 → 改 `src/thesis_watch/condition_classify.py` 规则后重跑本表。",
        "",
    ]
    total = 0
    auto_n = 0
    for t in TICKERS:
        bc = load_break_conditions(t)
        lines.append(f"## {t}")
        if not bc:
            lines.append("（台账无破条件）\n")
            continue
        conds = _split_conditions(bc)
        if not conds:
            lines.append(f"（切分为空，作者手查。原文前 200 字：{bc[:200]}）\n")
            continue
        for cond, tier in conds:
            total += 1
            labels = classify_condition(cond)
            auto = is_v1_auto(labels)
            if auto:
                auto_n += 1
            reasons = v1_gap_reasons(labels) if not auto else []
            # [sic] 标注台账错字
            sic = " [sic: 台账原文「下滱」疑为「下滑」]" if "下滱" in cond else ""
            label_str = ", ".join(l.value for l in labels) if labels else "(negation 跳过)"
            lines.append(f"- **[{tier or '—'}]** {cond}{sic}")
            lines.append(f"  - 分类: {label_str} | v1 可自动: {auto}" + (f" | 缺口: {'; '.join(reasons)}" if reasons else ""))
            lines.append("")
    lines.insert(8, f"> **统计**: {total} 条件, v1 可自动 {auto_n}/{total} = {auto_n/total:.0%}" if total else "")
    out_path = ROOT / "docs" / "condition-classification.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({total} 条件, v1 auto {auto_n}/{total})")


if __name__ == "__main__":
    main()
