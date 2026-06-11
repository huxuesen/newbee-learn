"""
保密观刷课 Web 应用 — FastAPI 版本
"""
import os
import uuid
import threading
import time
import json
import asyncio
from datetime import datetime, timedelta

import jwt
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import login as baomi_login
from course import CourseManager
import config as app_config

# ─── 配置 ────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET", "auto-baomiguan-secret-key-2026")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "cbirc")
COURSE_PACKET_ID = app_config.course_packet_id

# ─── FastAPI ─────────────────────────────────────────────────────────
app = FastAPI(title="小蜜蜂学习系统")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ─── 内存存储 ─────────────────────────────────────────────────────────
# sessions: session_id -> {phone, baomi_token, nickname}
sessions: dict = {}
# tasks: session_id -> {status, logs, log_idx, exam_result}
tasks: dict = {}
tasks_lock = threading.Lock()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ─── Pydantic 模型 ──────────────────────────────────────────────────
class AccessReq(BaseModel):
    access_password: str  # 网站访问密码 (AUTH_PASSWORD)


class BaomiLoginReq(BaseModel):
    phone: str
    password: str  # 保密观账号密码


class StartTaskReq(BaseModel):
    task_type: str  # "learning" 或 "exam"


# ─── JWT 工具 ─────────────────────────────────────────────────────────
def create_jwt(session_id: str, phone: str) -> str:
    payload = {
        "sid": session_id,
        "phone": phone,
        "exp": datetime.utcnow() + timedelta(hours=24),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")


# ─── 保密观 Token 校验 ──────────────────────────────────────────────
def check_baomi_token(session: requests.Session, token: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "token": token,
        "authToken": token,
        "siteId": "95",
        "Content-Type": "application/json",
    }
    try:
        resp = session.get(
            "https://www.baomi.org.cn/portal/main-api/checkToken.do",
            headers=headers,
        ).json()
        if resp.get("result"):
            return resp["data"].get("nickName") or "未设定姓名"
    except Exception:
        pass
    return None


# ─── 路由：页面 ──────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ─── 路由：认证 ──────────────────────────────────────────────────────
@app.post("/api/auth/access")
async def auth_access(req: AccessReq):
    """第一步：校验访问密码，通过后返回 JWT（此时尚未登录保密观）。"""
    if req.access_password != AUTH_PASSWORD:
        raise HTTPException(status_code=403, detail="访问密码错误")
    sid = str(uuid.uuid4())
    sessions[sid] = {"phone": "", "baomi_token": "", "nickname": ""}
    tasks[sid] = {"status": "idle", "logs": [], "log_idx": 0, "course_info": None, "exam_result": None}
    jwt_token = create_jwt(sid, "")
    return {"token": jwt_token}


@app.post("/api/auth/login")
async def auth_login(req: BaomiLoginReq, request: Request):
    """第二步：在主页面用手机号+密码登录保密观。"""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")

    # 保密观登录
    try:
        baomi_token = baomi_login.login(req.phone, req.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保密观登录失败: {e}")

    # 验证 token 并获取昵称
    http_session = requests.Session()
    nickname = check_baomi_token(http_session, baomi_token)
    if not nickname:
        raise HTTPException(status_code=400, detail="保密观 token 校验失败")

    # 更新 session
    sessions[sid]["phone"] = req.phone
    sessions[sid]["baomi_token"] = baomi_token
    sessions[sid]["nickname"] = nickname

    return {"nickname": nickname, "phone": req.phone}


@app.get("/api/auth/check")
async def auth_check(request: Request):
    """校验 JWT 是否有效，返回用户信息。"""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")
    sess = sessions[sid]
    return {
        "nickname": sess["nickname"] or "",
        "phone": sess["phone"] or "",
        "logged_in": bool(sess["baomi_token"]),
    }


# ─── 路由：课程状态 ──────────────────────────────────────────────────
@app.get("/api/status")
async def get_status(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")

    task = tasks.get(sid, {"status": "idle", "logs": [], "log_idx": 0, "course_info": None, "exam_result": None})
    return {
        "status": task["status"],
        "nickname": sessions[sid]["nickname"],
        "phone": sessions[sid]["phone"],
        "course_info": task.get("course_info"),
        "exam_result": task.get("exam_result"),
    }


# ─── 路由：课程进度 ──────────────────────────────────────────────────
@app.get("/api/progress")
async def get_progress(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")

    sess = sessions[sid]
    http_session = requests.Session()
    cm = CourseManager(http_session, sess["baomi_token"])

    # 获取课程进度
    progress = cm.get_course_progress(COURSE_PACKET_ID)
    progress_data = None
    if progress and progress.get("data"):
        d = progress["data"]
        progress_data = {
            "courseName": d.get("courseName", ""),
            "progressRate": d.get("progressRate", 0),
            "studyResourceNum": d.get("studyResourceNum", 0),
            "resourceSum": d.get("resourceSum", 0),
            "totalStudyTime": d.get("totalStudyTime", 0),
            "isFinish": d.get("isFinish", False),
            "isCertificate": d.get("isCertificate", False),
        }

    # 获取课程信息
    course_info = cm.get_course_info(COURSE_PACKET_ID)
    info_data = None
    if course_info and course_info.get("data"):
        info_data = {
            "name": course_info["data"].get("name", ""),
            "note": course_info["data"].get("note", ""),
        }

    return {
        "progress": progress_data,
        "course_info": info_data,
    }


# ─── 路由：启动任务 ──────────────────────────────────────────────────
@app.post("/api/start-learning")
async def start_learning(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")
    if not sessions[sid].get("baomi_token"):
        raise HTTPException(status_code=400, detail="请先登录保密观账号")

    with tasks_lock:
        task = tasks.get(sid)
        if not task:
            tasks[sid] = {"status": "idle", "logs": [], "log_idx": 0, "course_info": None, "exam_result": None}
            task = tasks[sid]
        if task["status"] in ("learning", "exam"):
            raise HTTPException(status_code=400, detail="当前有任务正在执行，请等待完成")
        task["status"] = "learning"
        task["logs"] = []
        task["log_idx"] = 0
        task["exam_result"] = None

    def _run():
        try:
            sess = sessions[sid]
            http_session = requests.Session()

            def web_logger(msg):
                with tasks_lock:
                    t = tasks[sid]
                    t["logs"].append({"time": _now(), "msg": msg})

            cm = CourseManager(http_session, sess["baomi_token"], logger=web_logger)
            cm._log(f"开始自动学习课程... [{_now()}]")

            success = cm.study_course(COURSE_PACKET_ID)
            if success:
                cm._log("✅ 课程学习完成！")
                with tasks_lock:
                    tasks[sid]["status"] = "completed"
            else:
                cm._log("❌ 课程学习失败，请稍后重试")
                with tasks_lock:
                    tasks[sid]["status"] = "error"
        except Exception as e:
            with tasks_lock:
                tasks[sid]["logs"].append({"time": _now(), "msg": f"[ERROR] 异常: {e}"})
                tasks[sid]["status"] = "error"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"message": "开始学习"}


@app.post("/api/start-exam")
async def start_exam(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")
    if not sessions[sid].get("baomi_token"):
        raise HTTPException(status_code=400, detail="请先登录保密观账号")

    with tasks_lock:
        task = tasks.get(sid)
        if not task:
            tasks[sid] = {"status": "idle", "logs": [], "log_idx": 0, "course_info": None, "exam_result": None}
            task = tasks[sid]
        if task["status"] in ("learning", "exam"):
            raise HTTPException(status_code=400, detail="当前有任务正在执行，请等待完成")
        task["status"] = "exam"
        task["logs"] = []
        task["log_idx"] = 0

    def _run():
        try:
            sess = sessions[sid]
            http_session = requests.Session()

            def web_logger(msg):
                with tasks_lock:
                    t = tasks[sid]
                    t["logs"].append({"time": _now(), "msg": msg})

            cm = CourseManager(http_session, sess["baomi_token"], logger=web_logger)
            cm._log(f"开始自动完成考试... [{_now()}]")

            success = cm.complete_exam(COURSE_PACKET_ID)
            if success:
                cm._log("✅ 考试完成！")
                with tasks_lock:
                    tasks[sid]["status"] = "completed"
            else:
                cm._log("❌ 考试失败，请稍后重试")
                with tasks_lock:
                    tasks[sid]["status"] = "error"
        except Exception as e:
            with tasks_lock:
                tasks[sid]["logs"].append({"time": _now(), "msg": f"[ERROR] 异常: {e}"})
                tasks[sid]["status"] = "error"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"message": "开始考试"}


# ─── 路由：SSE 日志流 ────────────────────────────────────────────────
@app.get("/api/stream")
async def stream_logs(request: Request):
    token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = decode_jwt(token)
    except HTTPException:
        raise
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")

    async def event_generator():
        idx = 0
        while True:
            # 检查客户端是否断开
            try:
                if await request.is_disconnected():
                    break
            except Exception:
                break

            with tasks_lock:
                task = tasks.get(sid)
                if not task:
                    await asyncio.sleep(0.5)
                    continue
                logs = task["logs"]
                status = task["status"]

            # 发送新日志
            while idx < len(logs):
                entry = logs[idx]
                data = json.dumps(entry, ensure_ascii=False)
                yield f"data: {data}\n\n"
                idx += 1

            # 发送状态更新
            state_data = json.dumps({"type": "status", "status": status}, ensure_ascii=False)
            yield f"data: {state_data}\n\n"

            # 如果任务完成/出错，发送完剩余日志后退出
            if status in ("completed", "error", "idle") and idx >= len(logs):
                yield f"data: {json.dumps({'type': 'done', 'status': status})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── 路由：轮询日志（备用） ──────────────────────────────────────────
@app.get("/api/logs")
async def get_logs(request: Request, idx: int = 0):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_jwt(token)
    sid = payload["sid"]
    if sid not in sessions:
        raise HTTPException(status_code=401, detail="会话已失效")

    with tasks_lock:
        task = tasks.get(sid)
        if not task:
            return {"logs": [], "status": "idle", "new_idx": 0}
        logs = task["logs"][idx:]
        status = task["status"]

    return {
        "logs": logs,
        "status": status,
        "new_idx": idx + len(logs),
    }


# ─── 启动 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
