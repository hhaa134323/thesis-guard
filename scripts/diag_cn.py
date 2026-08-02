"""诊断：Chinese reason 触发的 JS 错误（snapshot_smoke 超时根因）。全捕获 console+pageerror。"""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}"))
    page.on("pageerror", lambda e: errors.append(f"PAGEERROR: {e}"))
    page.on("requestfailed", lambda r: errors.append(f"REQFAIL: {r.url} {r.failure}"))
    page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
    page.fill("#f-input", "我持有 HSBC，因为按照年来看，它的股价表现稳健上升的形状")
    page.get_by_role("button", name="开始录入").click()
    time.sleep(60)
    print("=== errors (full) ===")
    for e in errors:
        print(e)
    print("=== body text 前 500 字 ===")
    print(page.inner_text("body")[:500])
    page.screenshot(path="screenshots/00_cn_reason.png", full_page=True)
    b.close()
