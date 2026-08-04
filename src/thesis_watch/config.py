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


def _llm(cfg: dict) -> dict:
    return cfg.get("llm", {}) or {}


def get_session_model(cfg: dict) -> dict:
    """会话模型配置（作者产 spec/schema/prompt 用）。
    形如 {provider, base_url, model, api_key_env}。与 task_model 独立，不复用同一字段。
    """
    return _llm(cfg).get("session_model", {}) or {}


def get_task_model(cfg: dict) -> dict:
    """任务模型配置（录入抽取 + eval）。形如 {provider, base_url, model, api_key_env}。"""
    return _llm(cfg).get("task_model", {}) or {}


def get_agent_model(cfg: dict) -> dict:
    """Agent loop 主模型配置（OpenAI Agents SDK + deepseek-v4-flash）。
    形如 {provider, base_url, model, api_key_env}。Phase 5 后 extract / generate_menu 也走
    agent_model（移植自 entry_agent/menu，pydantic-ai 已删）。run_l1 eval 用 model_override
    在同一端点跑多模型对比（deepseek vs glm）。
    """
    return _llm(cfg).get("agent_model", {}) or {}


def get_llm_limits(cfg: dict) -> dict:
    """限流 / token / 并发上限。429 与其它错误分开计数（见 eval-report per-call 表）。"""
    ll = _llm(cfg)
    return {
        "max_tokens": ll.get("max_tokens", 8192),
        "request_interval_sec": ll.get("request_interval_sec", 0.5),
        "max_retries_429": ll.get("max_retries_429", 5),
        "backoff_base_sec": ll.get("backoff_base_sec", 2.0),
        "backoff_cap_sec": ll.get("backoff_cap_sec", 60.0),
        "max_concurrency": ll.get("max_concurrency", 1),
    }
