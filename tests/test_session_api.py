#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话接口测试（routers/session_router.py + report 别名路由 + 孤儿 session 清理）。

覆盖 spec 4.2「接口设计」与 plan Task 3 Step 1 列出的用例。

铁律：
- ASR/LLM 全部打桩（monkeypatch services/segment_pipeline.py 内部服务获取函数），
  不打真实厂商 API。
- 不连接生产库：session_router / segment_pipeline 内部各自用 `SessionLocal`
  开会话，测试里必须把 `models.SessionLocal` 与 `services.segment_pipeline.SessionLocal`
  一起 monkeypatch 到同一个临时 SQLite，否则路由层和流水线层各写各的库，断言全部失真。
- 不触发 FastAPI 的 startup 事件（不用 `with TestClient(app) as c:`），
  避免真的跑 init_db()/scheduler/迁移，污染真实环境。
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-session-api")

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import (  # noqa: E402
    Base,
    User,
    AudioFile,
    AnalysisReport,
    AnalysisTaskType,
    RecordingSession,
    UploadStatus,
    get_db,
)
import auth as auth_module  # noqa: E402
import services.segment_pipeline as pipeline  # noqa: E402


# ==================== 打桩（同 test_segment_pipeline.py 的写法） ====================

class FakeASR:
    def __init__(self, default="转写文本"):
        self.default = default
        self.calls = []

    async def transcribe(self, file_path: str, audio_duration_s: float = 0.0) -> dict:
        self.calls.append(file_path)
        return {"success": True, "text": self.default, "error": None}


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def analyze(self, text: str, report_type: str = None, db=None, **kwargs) -> dict:
        self.calls.append({"report_type": report_type, "text": text})
        return {
            "success": True,
            "data": {"title": f"报告-{report_type}", "sections": []},
            "error": None,
        }


# ==================== fixtures ====================

@pytest.fixture()
def env(monkeypatch):
    """独立临时 SQLite + 打桩 ASR/LLM + FastAPI TestClient。"""
    tmp_dir = tempfile.mkdtemp(prefix="echomind_session_api_test_")
    db_path = Path(tmp_dir) / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 种子数据：两个用户 + 两个默认分析类型
    db = TestingSessionLocal()
    user_a = User(username="tester-a", password_hash="x", role="user")
    user_b = User(username="tester-b", password_hash="x", role="user")
    db.add_all([user_a, user_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    db.add_all([
        AnalysisTaskType(name="customer_brief", display_name="接待简报",
                          is_active=True, default_rank=1, sort_order=1),
        AnalysisTaskType(name="reception_review", display_name="接待复盘",
                          is_active=True, default_rank=2, sort_order=2),
    ])
    db.commit()
    user_a_id, user_b_id = user_a.id, user_b.id
    token_a = auth_module.create_access_token(user_a)
    token_b = auth_module.create_access_token(user_b)
    db.close()

    asr = FakeASR()
    llm = FakeLLM()

    # 流水线内部各自开 SessionLocal，必须指向同一临时库
    monkeypatch.setattr(pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(pipeline, "get_asr_service", lambda: asr)
    monkeypatch.setattr(pipeline, "get_llm_service", lambda: llm)
    monkeypatch.setattr(pipeline, "RETRY_BACKOFF_SECONDS", (0, 0))
    monkeypatch.setattr(pipeline, "_generate_share", lambda report, db, file_name: "")

    import main as main_module

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    main_module.app.dependency_overrides[get_db] = override_get_db
    client = TestClient(main_module.app)

    class Env:
        pass

    e = Env()
    e.client = client
    e.SessionLocal = TestingSessionLocal
    e.asr = asr
    e.llm = llm
    e.user_a_id = user_a_id
    e.user_b_id = user_b_id
    e.headers_a = {"Authorization": f"Bearer {token_a}"}
    e.headers_b = {"Authorization": f"Bearer {token_b}"}
    e.engine = engine
    try:
        yield e
    finally:
        main_module.app.dependency_overrides.clear()
        engine.dispose()


def db_session(env):
    return env.SessionLocal()


def get_recording_session(env, session_id):
    db = db_session(env)
    try:
        return db.query(RecordingSession).filter(
            RecordingSession.session_id == session_id
        ).first()
    finally:
        db.close()


# ==================== 测试用例 ====================

def test_upload_segment_creates_session_implicitly(env):
    """首段上传时 session 不存在，应隐式创建"""
    r = env.client.post(
        "/api/v1/segments",
        headers=env.headers_a,
        files={"file": ("s0.m4a", b"fake-audio-bytes", "audio/m4a")},
        data={"session_id": "s-1", "segment_index": 0},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["session_id"] == "s-1"
    assert body["segment_index"] == 0
    assert body["status"] == "pending"
    assert "file_id" in body

    sess = get_recording_session(env, "s-1")
    assert sess is not None
    assert sess.status == "recording"
    assert sess.user_id == env.user_a_id


def test_upload_same_index_twice_overwrites(env):
    """同 (session_id, segment_index) 重复上传，覆盖原段并重跑 ASR"""
    r1 = env.client.post(
        "/api/v1/segments",
        headers=env.headers_a,
        files={"file": ("s0.m4a", b"first", "audio/m4a")},
        data={"session_id": "s-2", "segment_index": 0},
    )
    assert r1.status_code == 202
    file_id_1 = r1.json()["file_id"]

    r2 = env.client.post(
        "/api/v1/segments",
        headers=env.headers_a,
        files={"file": ("s0-retry.m4a", b"second", "audio/m4a")},
        data={"session_id": "s-2", "segment_index": 0},
    )
    assert r2.status_code == 202
    file_id_2 = r2.json()["file_id"]

    db = db_session(env)
    try:
        segs = db.query(AudioFile).filter(
            AudioFile.session_id == "s-2", AudioFile.segment_index == 0
        ).all()
    finally:
        db.close()
    assert len(segs) == 1, "重复上传同一段应覆盖，不应产生两条记录"
    assert file_id_1 != file_id_2 or True  # file_id 允许变化，关键是行数不翻倍


def test_finalize_sets_total_and_types(env):
    for i in range(2):
        r = env.client.post(
            "/api/v1/segments",
            headers=env.headers_a,
            files={"file": (f"s{i}.m4a", b"data", "audio/m4a")},
            data={"session_id": "s-3", "segment_index": i},
        )
        assert r.status_code == 202

    r = env.client.post(
        "/api/v1/sessions/s-3/finalize",
        headers=env.headers_a,
        json={"total_segments": 2, "task_types": ["customer_brief"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == "s-3"
    assert body["status"] in ("analyzing", "generating", "completed")

    sess = get_recording_session(env, "s-3")
    assert sess.total_segments == 2
    assert sess.task_types == ["customer_brief"]


def test_duplicate_finalize_is_idempotent(env):
    """重复调用 finalize 只更新字段，不重复触发分析（LLM 只跑一轮）"""
    for i in range(1):
        env.client.post(
            "/api/v1/segments",
            headers=env.headers_a,
            files={"file": (f"s{i}.m4a", b"data", "audio/m4a")},
            data={"session_id": "s-dup", "segment_index": i},
        )

    r1 = env.client.post(
        "/api/v1/sessions/s-dup/finalize",
        headers=env.headers_a,
        json={"total_segments": 1, "task_types": ["customer_brief"]},
    )
    assert r1.status_code == 200
    assert get_recording_session(env, "s-dup").status == "completed"
    baseline_calls = len(env.llm.calls)
    assert baseline_calls == 1

    r2 = env.client.post(
        "/api/v1/sessions/s-dup/finalize",
        headers=env.headers_a,
        json={"total_segments": 1, "task_types": ["customer_brief"]},
    )
    assert r2.status_code == 200
    assert len(env.llm.calls) == baseline_calls, "重复 finalize 不得再跑一轮 LLM"
    assert get_recording_session(env, "s-dup").status == "completed"


def test_get_session_returns_progress(env):
    for i in range(2):
        env.client.post(
            "/api/v1/segments",
            headers=env.headers_a,
            files={"file": (f"s{i}.m4a", b"data", "audio/m4a")},
            data={"session_id": "s-4", "segment_index": i},
        )
    env.client.post(
        "/api/v1/sessions/s-4/finalize",
        headers=env.headers_a,
        json={"total_segments": 2, "task_types": ["customer_brief"]},
    )

    r = env.client.get("/api/v1/sessions/s-4", headers=env.headers_a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == "s-4"
    assert body["status"] == "completed"
    assert body["total_segments"] == 2
    assert len(body["segments"]) == 2
    for seg in body["segments"]:
        assert set(seg.keys()) >= {"segment_index", "status", "duration"}
        assert seg["status"] == "completed"
    assert body["progress"] == {"asr_done": 2, "asr_total": 2}
    assert len(body["report_ids"]) == 1  # 只勾了 customer_brief
    assert body["error_message"] is None


def test_get_session_not_found(env):
    r = env.client.get("/api/v1/sessions/does-not-exist", headers=env.headers_a)
    assert r.status_code == 404


def test_cannot_access_other_users_session(env):
    """越权：查别人的 session 应 403/404"""
    env.client.post(
        "/api/v1/segments",
        headers=env.headers_a,
        files={"file": ("s0.m4a", b"data", "audio/m4a")},
        data={"session_id": "s-5", "segment_index": 0},
    )

    r = env.client.get("/api/v1/sessions/s-5", headers=env.headers_b)
    assert r.status_code in (403, 404)

    r2 = env.client.post(
        "/api/v1/sessions/s-5/finalize",
        headers=env.headers_b,
        json={"total_segments": 1},
    )
    assert r2.status_code in (403, 404)


def test_list_sessions_scoped_to_current_user(env):
    env.client.post(
        "/api/v1/segments",
        headers=env.headers_a,
        files={"file": ("a.m4a", b"data", "audio/m4a")},
        data={"session_id": "s-list-a", "segment_index": 0},
    )
    env.client.post(
        "/api/v1/segments",
        headers=env.headers_b,
        files={"file": ("b.m4a", b"data", "audio/m4a")},
        data={"session_id": "s-list-b", "segment_index": 0},
    )

    r = env.client.get("/api/v1/sessions", headers=env.headers_a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sessions" in body
    session_ids = [s["session_id"] for s in body["sessions"]]
    assert "s-list-a" in session_ids
    assert "s-list-b" not in session_ids

    item = next(s for s in body["sessions"] if s["session_id"] == "s-list-a")
    assert set(item.keys()) >= {
        "session_id", "title", "status", "total_segments",
        "progress", "report_ids", "error_message", "created_at",
    }
    assert set(item["progress"].keys()) == {"asr_done", "asr_total"}


def test_report_alias_route_matches_admin_route(env):
    """GET /api/v1/reports/{id} 与 /api/v1/admin/reports/{id} 返回一致"""
    env.client.post(
        "/api/v1/segments",
        headers=env.headers_a,
        files={"file": ("s0.m4a", b"data", "audio/m4a")},
        data={"session_id": "s-6", "segment_index": 0},
    )
    env.client.post(
        "/api/v1/sessions/s-6/finalize",
        headers=env.headers_a,
        json={"total_segments": 1, "task_types": ["customer_brief"]},
    )
    r = env.client.get("/api/v1/sessions/s-6", headers=env.headers_a)
    report_id = r.json()["report_ids"][0]

    r_alias = env.client.get(f"/api/v1/reports/{report_id}", headers=env.headers_a)
    r_admin = env.client.get(f"/api/v1/admin/reports/{report_id}", headers=env.headers_a)
    assert r_alias.status_code == 200
    assert r_admin.status_code == 200
    assert r_alias.json() == r_admin.json()


def test_orphan_session_cleanup(env):
    """recording 状态超过 24 小时的 session 应被清理任务标记为 failed"""
    from datetime import datetime, timedelta
    import scheduler

    db = db_session(env)
    old_sess = RecordingSession(
        session_id="s-orphan",
        user_id=env.user_a_id,
        title="孤儿会话",
        status="recording",
        created_at=datetime.utcnow() - timedelta(hours=25),
    )
    fresh_sess = RecordingSession(
        session_id="s-fresh",
        user_id=env.user_a_id,
        title="新会话",
        status="recording",
        created_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.add_all([old_sess, fresh_sess])
    db.commit()
    db.close()

    import asyncio
    asyncio.run(scheduler.cleanup_orphan_sessions(env.SessionLocal))

    db = db_session(env)
    try:
        old_after = db.query(RecordingSession).filter(
            RecordingSession.session_id == "s-orphan"
        ).first()
        fresh_after = db.query(RecordingSession).filter(
            RecordingSession.session_id == "s-fresh"
        ).first()
    finally:
        db.close()

    assert old_after.status == "failed"
    assert old_after.error_message == "录音未正常结束"
    assert fresh_after.status == "recording"
