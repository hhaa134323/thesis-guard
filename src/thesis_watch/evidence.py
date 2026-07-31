"""证据引用自检契约（v0.1）。

对应 docs/harness-design.md §5。每条 triggered/watch 结论必须满足：
- 一手原文链接（SEC filing / 新闻原文，非聚合页）
- 原文摘录，且摘录能在 fetched 原文中定位到

self_check 回放：fetch url → 断言 excerpt 子串存在。
- 通过：evidence.checked_ok = True
- 失败：按原因码降级（E1/E2/E3），核对 Agent 将结论降为 watch 并记录

实际 fetch 依赖网络（B1 解除后生效）；为可测，fetcher 可注入。
"""
from __future__ import annotations

import dataclasses
import typing

Fetcher = typing.Callable[[str], "str | None"]  # url -> body text；失败返 None


@dataclasses.dataclass
class EvidenceCheckResult:
    ok: bool
    reason: str | None        # None | E1_FETCH_FAIL | E2_NO_PRIMARY_SOURCE | E3_EVIDENCE_MISMATCH
    detail: str = ""


def self_check(url: str, excerpt: str,
              fetcher: Fetcher | None = None) -> EvidenceCheckResult:
    """校验 (url, excerpt)。

    - url 为空 → E2（无一手源）
    - excerpt 为空 → E3（摘录缺失）
    - 给定 fetcher：fetch url 失败 → E1；excerpt 不在 fetched body → E3
    - 未给 fetcher：跳过网络，返回 ok（仅做结构校验，供离线测试）
    """
    if not url:
        return EvidenceCheckResult(False, "E2_NO_PRIMARY_SOURCE", "empty url")
    if not excerpt:
        return EvidenceCheckResult(False, "E3_EVIDENCE_MISMATCH", "empty excerpt")
    if fetcher is None:
        return EvidenceCheckResult(True, None, "skipped (no fetcher)")
    try:
        body = fetcher(url)
    except Exception as e:  # noqa: BLE001 — 网络失败统一记 E1
        return EvidenceCheckResult(False, "E1_FETCH_FAIL", str(e))
    if body is None:
        return EvidenceCheckResult(False, "E1_FETCH_FAIL", "fetch returned None")
    if excerpt not in body:
        return EvidenceCheckResult(False, "E3_EVIDENCE_MISMATCH",
                                   "excerpt not found in fetched body")
    return EvidenceCheckResult(True, None, "ok")


def default_fetcher(url: str, timeout: float = 15.0) -> "str | None":
    """urllib 抓取（网络依赖，B1 解除后可用）。SEC 要求 User-Agent。"""
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "ThesisWatch/0.0 research@example.com"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 公开接口
        data = resp.read()
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data
