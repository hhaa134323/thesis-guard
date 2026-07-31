"""用户可配阈值与文案（v0.1）。

对应 config.example.yaml。Layer 2 红线阈值用户可调；
R3 文案黑名单可扩展（不可缩水到低于红线要求）。
"""
from __future__ import annotations

import os
from pathlib import Path


def load_config(path: str | os.PathLike | None = None) -> dict:
    """加载 YAML 配置；缺省/不存在返回空 dict（全部走代码默认）。"""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    import yaml  # 延迟导入：无 pyyaml 时仅本函数不可用，其余包正常
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_redline_thresholds(cfg: dict) -> dict:
    """形如 {"large_fine": {"amount_usd": 5e7}, ...}。"""
    return (cfg.get("redline", {}) or {}).get("thresholds", {}) or {}


def get_forbidden_extra(cfg: dict) -> list[str]:
    """用户扩展的黑名单短语（叠加在默认之上）。"""
    return (cfg.get("redline", {}) or {}).get("extra_forbidden_phrases", []) or []


def get_llm_model(cfg: dict) -> str:
    """默认 Claude 模型（agent loop 选型确认后启用）。"""
    return (cfg.get("llm", {}) or {}).get("model", "claude-sonnet-4-6")
