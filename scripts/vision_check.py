"""视觉校验脚本（qwen3-vl-plus，百炼 OpenAI 兼容端点，图片 base64 内联）。

读截图 → 问视觉模型：首屏是否白屏？root 有无渲染？布局是否符合（居中单栏对话 + 右侧确认卡抽屉）？
列出全部文字 + 任何异常。API key 走 env（config.yaml task_model.api_key_env，与 task_model 同套），
**不打印 key 明文、不写进代码**（R7/secret）。
PBC_Workstation 未 clone，按作者描述的调用方式实现（参考其 scripts/test_vision.py 模式）。

用法：python scripts/vision_check.py <screenshot.png> [more...]
判定：回「渲染正常且布局符合设计」才算通过；回异常则按描述继续修，修完重新截图复验。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_Q = (
    "这是一张 Web 应用截图。请逐一回答：\n"
    "1) 首屏是否白屏（无任何渲染内容）？\n"
    "2) root 区域有无实际渲染内容（对话气泡 / 表单 / 卡片）？\n"
    "3) 布局是否符合「居中单栏对话 + 右侧确认卡抽屉」的设计？\n"
    "4) 列出你看到的全部文字（中文原文）。\n"
    "5) 任何异常（错位 / 报错 / 英文堆叠 / 组件未挂载等）。\n"
    "最后给一句结论：渲染正常且布局符合设计 / 或 异常（简述）。"
)


def _task_cfg() -> dict:
    from thesis_watch.config import get_task_model, load_config
    cfg = load_config(str(ROOT / "config.yaml"))
    return get_task_model(cfg)


def check(image_path: str, question: str | None = None) -> str:
    task = _task_cfg()
    base_url = task.get("base_url", "").rstrip("/")
    api_key = os.environ.get(task.get("api_key_env", ""), "")
    if not base_url or not api_key:
        return f"ERROR: base_url 或 api key 未配（base_url={base_url!r}, key_env={task.get('api_key_env')!r}）"
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = json.dumps({
        "model": "qwen3-vl-plus",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": question or DEFAULT_Q},
        ]}],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=body,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
        return resp["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {type(e).__name__}: {str(e)[:300]}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/vision_check.py <screenshot.png> [more...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        print(f"\n=== {p} ===")
        print(check(p))
