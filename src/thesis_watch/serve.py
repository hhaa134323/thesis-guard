"""录入 loop 承载层：FastAPI localhost 单页（2026-08-02 形态定稿）。

端点：
  GET  /                       单页 index.html
  GET  /static/{file}           静态资源（app.js / style.css，不依赖 CDN）
  POST /api/session             开会话 {user_id?, ticker, reason} → view
  POST /api/session/{id}/turn   {text? / picks? / edits? / request_menu?} → view
  POST /api/session/{id}/confirm {edits?} → 落库 SQLite → view

部署中立：HOST/PORT/DB/CONFIG 走 env（不写死本机）；启动脚本（start.bat）与主程序解耦。
本地自用：本地 HOST 时 1.5s 后自动开浏览器（THESIS_OPEN_BROWSER=0 关）。
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import load_config
from .entry_loop import S_CONFIRMED, EntrySession, new_session
from .store import ThesisStore

HOST = os.environ.get("THESIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("THESIS_PORT", "8000"))
DB_PATH = os.environ.get("THESIS_DB", "data/thesis.db")
CONFIG_PATH = os.environ.get("THESIS_CONFIG", "config.yaml")
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

app = FastAPI(title="Thesis Watch 录入 Agent", version="0.1")

# 会话内存存储（单进程 demo 用；进程重启即失，已落库的卡在 SQLite）
_sessions: dict[str, EntrySession] = {}

# 配置（task_model 走 config.yaml；缺失则空 dict，start() 时 build_agent 会 SystemExit 提示）
_cfg = load_config(CONFIG_PATH)

# 存储（部署中立：DB_PATH 相对路径，可被 env 覆盖到任意位置 / 卷）
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
_store = ThesisStore(DB_PATH)
_store.seed_preset_users()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


def _err_view(sess: EntrySession, e: Exception) -> dict:
    msg = f"出错：{type(e).__name__}: {str(e)[:200]}"
    return {"stage": sess.stage, "assistant": msg, "card": None, "menu": None,
            "open_questions": [], "ticker": sess.ticker, "error": str(e)[:300]}


@app.post("/api/session")
def api_start(payload: dict) -> JSONResponse:
    user_id = (payload.get("user_id") or "beta1").strip() or "beta1"
    ticker = (payload.get("ticker") or "").strip()
    reason = (payload.get("reason") or "").strip()
    if not ticker or not reason:
        raise HTTPException(400, "ticker 与 reason 必填")
    if _store.get_user(user_id) is None:
        raise HTTPException(400, f"未知 user_id={user_id}（预置 beta1–beta5）")
    sid = uuid.uuid4().hex[:12]
    sess = new_session(user_id, ticker, _cfg)
    _sessions[sid] = sess
    try:
        view = sess.start(reason)
    except Exception as e:  # noqa: BLE001
        view = _err_view(sess, e)
    view["session_id"] = sid
    return JSONResponse(view)


@app.post("/api/session/{sid}/turn")
def api_turn(sid: str, payload: dict) -> JSONResponse:
    sess = _sessions.get(sid)
    if sess is None:
        raise HTTPException(404, "session 不存在（服务可能已重启）")
    try:
        view = sess.turn(payload)
    except Exception as e:  # noqa: BLE001
        view = _err_view(sess, e)
    view["session_id"] = sid
    return JSONResponse(view)


@app.post("/api/session/{sid}/confirm")
def api_confirm(sid: str, payload: dict) -> JSONResponse:
    sess = _sessions.get(sid)
    if sess is None:
        raise HTTPException(404, "session 不存在")
    try:
        view = sess.confirm(payload.get("edits"))
    except Exception as e:  # noqa: BLE001
        view = _err_view(sess, e)
    view["session_id"] = sid
    if sess.stage == S_CONFIRMED and sess.card_draft is not None:
        _store.upsert_card(sess.card_draft)
        view["stored"] = True
        view["card_id"] = sess.card_draft.card_id
    return JSONResponse(view)


def main() -> None:
    import uvicorn

    url = f"http://{HOST}:{PORT}/"
    print(f"Thesis Watch 录入 Agent → {url}  (DB={DB_PATH}, config={CONFIG_PATH})")
    open_browser = (os.environ.get("THESIS_OPEN_BROWSER", "1") == "1"
                    and HOST in ("127.0.0.1", "localhost", "0.0.0.0"))
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print("（1.5s 后自动开浏览器；THESIS_OPEN_BROWSER=0 关）")
    print("Ctrl+C 退出。")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
