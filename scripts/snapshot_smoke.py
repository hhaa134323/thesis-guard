"""Playwright 截图 + HSBC 录入冒烟（round-2 目检辅助）。

首页 + 各状态（extracted / menu / confirm_card / confirmed）截图，存 screenshots/。
跑完用 vision_check.py 让 qwen3-vl-plus 读图验证（Claude 本体不看截图）。

需要 chromium：首次跑若报 browser not found，先 `python -m playwright install chromium`。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"
OUT.mkdir(exist_ok=True)
URL = "http://127.0.0.1:8000/"


def shot(page, name: str) -> str:
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=True)
    print("shot:", p)
    return str(p)


def main() -> int:
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            print(f"chromium 启动失败：{e}\n→ 先跑：python -m playwright install chromium")
            return 1
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.on("console", lambda msg: print(f"  [console.{msg.type}] {msg.text}") if msg.type == "error" else None)
        page.on("requestfailed", lambda req: print(f"  [404/fail] {req.url} {req.failure}") if req.failure else None)
        page.goto(URL, wait_until="networkidle")
        shot(page, "01_home")

        # 开始录入（单输入框：一句话标的 + 理由）
        page.fill("#f-input", "我持有 HSBC，因为按照年来看，它的股价表现稳健上升的形状")
        page.get_by_role("button", name="开始录入").click()
        # 等 extract + 话术 → 抽屉出现「买入逻辑」字段（最长 extract 45s + 话术 5s）
        page.wait_for_selector("text=买入逻辑", timeout=120000)
        time.sleep(3)  # 打字机走一会儿
        shot(page, "02_extracted")

        # 无法确定 → 菜单
        page.fill("#f-msg", "无法确定")
        page.get_by_role("button", name="发送").click()
        page.wait_for_selector("text=提交勾选", timeout=120000)
        time.sleep(2)
        shot(page, "03_menu")

        # 勾 A[0]（第一个 label）+ B[0]（第一个含「对应」的 label）
        page.locator("label").first.click()
        page.locator("label:has-text('对应')").first.click()
        time.sleep(0.5)
        shot(page, "03b_menu_picked")
        page.get_by_role("button", name="提交勾选").click()
        page.wait_for_selector("text=确认入库", timeout=60000)
        time.sleep(2)
        shot(page, "04_confirm_card")

        # 确认入库
        page.get_by_role("button", name="确认入库").click()
        time.sleep(2)
        shot(page, "05_confirmed")

        b.close()
    print("\n截图完成 →", OUT)
    print("视觉校验：python scripts/vision_check.py screenshots/*.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
