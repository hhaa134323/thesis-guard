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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import load_config
from .entry_loop import EntrySession, new_session
from .store import ThesisStore

HOST = os.environ.get("THESIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("THESIS_PORT", "8000"))
DB_PATH = os.environ.get("THESIS_DB", "data/thesis.db")
os.environ.setdefault("THESIS_DB_PATH", DB_PATH)  # 让 orchestrator._get_store() 落同一 DB（save_card 入此库）
CONFIG_PATH = os.environ.get("THESIS_CONFIG", "config.yaml")
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

app = FastAPI(title="Thesis Watch 录入 Agent", version="0.1")


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """HTML 响应不缓存（index.html 引用的 /assets/* hash 每次 build 变，
    缓存旧 index.html → 旧 hash CSS/JS 404 → 白屏/无样式）。/assets/* 哈希产物可缓存。"""
    response = await call_next(request)
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# 会话内存存储（单进程 demo 用；进程重启即失，已落库的卡在 SQLite）
_sessions: dict[str, EntrySession] = {}

# 配置（task_model 走 config.yaml；缺失则空 dict，start() 时 build_agent 会 SystemExit 提示）
_cfg = load_config(CONFIG_PATH)

# 存储（部署中立：DB_PATH 相对路径，可被 env 覆盖到任意位置 / 卷）
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
_store = ThesisStore(DB_PATH)
_store.seed_preset_users()

# 静态托管：根挂载放最后（/api/* 路由先匹配），其余（/、/assets/*）走 StaticFiles。
# html=True → GET / 服务 static/index.html；/assets/* 命中构建产物（修 Vite 绝对路径白屏，2026-08-02）。
# 旧的 /static 挂载 + @app.get("/") 已删（Vite 产物引用 /assets/，/static 对不上 → 404 → 白屏）。


def _err_view(sess: EntrySession, e: Exception) -> dict:
    sess.error = f"{type(e).__name__}: {str(e)[:200]}"
    msg = f"出错：{type(e).__name__}: {str(e)[:160]}"
    return sess._view(assistant=msg)


@app.post("/api/session")
def api_start(payload: dict) -> JSONResponse:
    user_id = (payload.get("user_id") or "beta1").strip() or "beta1"
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 必填（一句话说标的 + 理由）")
    if _store.get_user(user_id) is None:
        raise HTTPException(400, f"未知 user_id={user_id}（预置 beta1–beta5）")
    model = (payload.get("model") or "").strip() or None  # Stage 2：按会话选模型；None 走 config 默认
    sid = uuid.uuid4().hex[:12]
    sess = new_session(user_id, _cfg, model_name=model)  # ticker 由 start 从一句话抽取
    _sessions[sid] = sess
    try:
        view = sess.start(text)
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
    # save_card 已在 agent loop 内落库（orchestrator._get_store = 本 DB）；view 自带 stored/card_id
    return JSONResponse(view)


@app.post("/api/session/{sid}/stream")
async def api_stream(sid: str, payload: dict):
    """SSE 流式 turn：逐 token 推 agent 回复 + tool_call/tool_result 事件（Phase 3）。
    现有 JSON /turn 不动；前端切到本端点即可逐字显示（打字机效果）。事件：
      event: token       data: {"text": "..."}
      event: tool_call   data: {"tool": "resolve_ticker", "args": {...}}
      event: tool_result data: {"tool": "resolve_ticker", "result": {...}}
      event: done        data: {}
    """
    sess = _sessions.get(sid)
    if sess is None:
        raise HTTPException(404, "session 不存在（服务可能已重启）")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 必填")

    async def gen():
        async for sse in sess.stream_run(text):
            yield sse
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# 根挂载（必须在所有 /api/* 路由之后注册，否则会吞掉 /api）：
# GET / → static/index.html；GET /assets/* → static/assets/*（Vite 产物）；/api/* 由上方路由匹配。
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="root")


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
