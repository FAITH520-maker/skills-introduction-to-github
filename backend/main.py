"""FastAPI 入口：对话文件上传解析、决策流水线、报告查询与前端静态页面。"""
import re
from datetime import datetime

import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import FRONTEND_DIR, Settings
from coordinator import DecisionCoordinator
from llm import LLMClient
from parser import ParseError, decode_bytes, parse_conversation
from pipeline import default_steps, reset_session, run_pipeline
from storage import SessionStore

settings = Settings()
store = SessionStore()
coordinator = DecisionCoordinator(LLMClient(settings))

app = FastAPI(title="社群决策 AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# 上传文件解析（不依赖 python-multipart，兼容 multipart/form-data 与原始字节）
# ---------------------------------------------------------------------------


def _parse_multipart(body: bytes, content_type: str) -> tuple[str, bytes]:
    """从 multipart/form-data 中提取第一个带文件名的字段。"""
    match = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not match:
        raise ValueError("multipart 请求缺少 boundary")
    delimiter = b"--" + match.group(1).encode("utf-8")
    chunks = body.split(delimiter)
    for chunk in chunks[1:]:
        if chunk.startswith(b"--"):
            break  # 结束标记
        chunk = chunk.lstrip(b"\r\n")
        header_part, _, data = chunk.partition(b"\r\n\r\n")
        if not header_part:
            continue
        filename_match = re.search(rb'filename="([^"]*)"', header_part)
        name_match = re.search(rb'name="([^"]*)"', header_part)
        if not filename_match or not name_match:
            continue
        filename = filename_match.group(1).decode("utf-8", "replace")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        return filename, data
    raise ValueError("multipart 请求中未找到上传文件")


async def _read_upload(request: Request) -> tuple[str, bytes]:
    content_type = request.headers.get("content-type", "")
    query_filename = request.query_params.get("filename", "")
    body = await request.body()
    if "multipart/form-data" in content_type:
        filename, data = _parse_multipart(body, content_type)
        return filename, data
    if not query_filename:
        raise HTTPException(400, "缺少文件名（可放在 filename 查询参数或使用 multipart 上传）")
    return query_filename, body


# ---------------------------------------------------------------------------
# 会话辅助
# ---------------------------------------------------------------------------


def _summary(session: dict) -> dict:
    report = session.get("report") or {}
    intent = session.get("intent") or {}
    return {
        "id": session["id"],
        "source_file": session.get("source_file", ""),
        "title": report.get("title") or intent.get("topic") or session.get("source_file", ""),
        "status": session.get("status", "uploaded"),
        "progress": session.get("progress", 0),
        "created_at": session.get("created_at", ""),
        "message_count": len(session.get("messages") or []),
    }


def _make_session(source_file: str, messages: list[dict]) -> dict:
    file_type = "json" if source_file.lower().endswith(".json") else "txt"
    return {
        "id": store.new_id(),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": source_file,
        "file_type": file_type,
        "messages": messages,
        "status": "uploaded",
        "progress": 0,
        "steps": default_steps(),
        "intent": None,
        "agents_round1": None,
        "agents_round2": None,
        "report": None,
        "error": None,
    }


def _get_session(session_id: str) -> dict:
    try:
        return store.load(session_id)
    except FileNotFoundError:
        raise HTTPException(404, "会话不存在")


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "model": settings.model,
        "mock": settings.mock,
        "has_key": bool(settings.api_key),
    }


@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    return [_summary(session) for session in store.list_all()]


@app.post("/api/sessions")
async def upload(request: Request) -> dict:
    filename, data = await _read_upload(request)
    if not data:
        raise HTTPException(400, "文件为空")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "文件超过 2MB 限制")
    try:
        text = decode_bytes(data)
        messages = parse_conversation(text, filename)
    except ParseError as exc:
        raise HTTPException(400, str(exc))

    session = _make_session(filename, messages)
    store.save(session)
    return session


@app.post("/api/sessions/{session_id}/run")
async def run_analysis(session_id: str) -> dict:
    session = _get_session(session_id)
    if session.get("status") == "running":
        raise HTTPException(409, "该会话正在分析中")
    reset_session(session)
    store.save(session)
    asyncio.create_task(asyncio.to_thread(run_pipeline, session_id, store, coordinator))
    return {"ok": True, "id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    return _get_session(session_id)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    if not store.delete(session_id):
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# 前端静态页面
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
