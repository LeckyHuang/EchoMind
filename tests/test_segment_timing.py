#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立验收方自写的时序用例（不复用实现者的测试断言口径以外的东西）。

口径：LLM stub 调用次数必须 == 分析类型数 × 1 轮。
"""
import asyncio
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import (  # noqa: E402
    Base, User, AudioFile, AnalysisReport, AnalysisTaskType,
    RecordingSession, UploadStatus,
)
import services.segment_pipeline as pipeline  # noqa: E402

TYPES = ["t_a", "t_b"]


class YieldyASR:
    """每次 transcribe 主动让出 N 次控制权，强制协程交错。"""

    def __init__(self, yields=3, behaviour=None):
        self.yields = yields
        self.behaviour = behaviour or {}
        self.calls = []
        self.inflight = 0
        self.peak = 0

    async def transcribe(self, file_path, audio_duration_s=0.0):
        self.calls.append(file_path)
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        for _ in range(self.yields):
            await asyncio.sleep(0)
        self.inflight -= 1
        for k, v in self.behaviour.items():
            if k in file_path:
                return v
        return {"success": True, "text": f"TXT::{file_path[-24:]}", "error": None}


class CountingLLM:
    def __init__(self, yields=3):
        self.calls = []
        self.yields = yields

    async def analyze(self, text, report_type=None, db=None, **kw):
        self.calls.append(report_type)
        for _ in range(self.yields):
            await asyncio.sleep(0)
        return {"success": True, "data": {"title": report_type, "sections": []}, "error": None}

    @property
    def n(self):
        return len(self.calls)


@pytest.fixture()
def env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="review_")
    engine = create_engine(f"sqlite:///{Path(tmp)/'t.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SL = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SL()
    u = User(username="u", password_hash="x", role="user")
    db.add(u); db.commit(); db.refresh(u)
    db.add_all([
        AnalysisTaskType(name="t_a", display_name="A", is_active=True, default_rank=1, sort_order=1),
        AnalysisTaskType(name="t_b", display_name="B", is_active=True, default_rank=2, sort_order=2),
    ])
    db.commit()
    uid = u.id
    db.close()

    asr = YieldyASR()
    llm = CountingLLM()
    monkeypatch.setattr(pipeline, "SessionLocal", SL)
    monkeypatch.setattr(pipeline, "get_asr_service", lambda: asr)
    monkeypatch.setattr(pipeline, "get_llm_service", lambda: llm)
    monkeypatch.setattr(pipeline, "RETRY_BACKOFF_SECONDS", (0, 0))
    monkeypatch.setattr(pipeline, "_generate_share", lambda r, d, f: "")

    class E: pass
    e = E(); e.SL = SL; e.asr = asr; e.llm = llm; e.uid = uid
    try:
        yield e
    finally:
        engine.dispose()


def mk_sess(env, sid="S", status="recording", total=None):
    db = env.SL()
    db.add(RecordingSession(session_id=sid, user_id=env.uid, title="t",
                            status=status, total_segments=total, task_types=TYPES))
    db.commit(); db.close()


def mk_seg(env, sid, i, status=UploadStatus.PENDING.value, text=None):
    db = env.SL()
    af = AudioFile(user_id=env.uid, original_filename=f"g{i}.m4a",
                   stored_filename=f"g{i}.m4a", file_path=f"/x/{sid}_g{i}.m4a",
                   file_size=1, duration=10.0, file_format="m4a",
                   upload_status=status, asr_text=text, session_id=sid, segment_index=i)
    db.add(af); db.commit(); n = af.id; db.close()
    return n


def sess(env, sid="S"):
    db = env.SL()
    try:
        return db.query(RecordingSession).filter(RecordingSession.session_id == sid).first()
    finally:
        db.close()


def merged(env, sid="S"):
    db = env.SL()
    try:
        s = db.query(RecordingSession).filter(RecordingSession.session_id == sid).first()
        if not s or not s.merged_file_id:
            return None
        a = db.query(AudioFile).filter(AudioFile.id == s.merged_file_id).first()
        return a.asr_text
    finally:
        db.close()


# ---------- Q1: 幂等锁 ----------

@pytest.mark.asyncio
async def test_r1_finalize_races_last_segment(env):
    """finalize 与最后一段 ASR 几乎同时；ASR 内部多次让出，强制交错。"""
    mk_sess(env)
    ids = [mk_seg(env, "S", i) for i in range(4)]
    for i in ids[:3]:
        await pipeline.submit_segment_asr(i)
    assert env.llm.n == 0

    await asyncio.gather(
        pipeline.submit_segment_asr(ids[3]),
        pipeline.finalize_session("S", 4, TYPES),
    )
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次，应为 {len(TYPES)}"
    assert sess(env).status == "completed"


@pytest.mark.asyncio
async def test_r2_finalize_first_then_all_segments_concurrent(env):
    """先 finalize，再把 5 段 ASR 全部并发发起（交错回调）。"""
    mk_sess(env)
    ids = [mk_seg(env, "S", i) for i in range(5)]
    assert await pipeline.finalize_session("S", 5, TYPES) is False
    await asyncio.gather(*[pipeline.submit_segment_asr(i) for i in ids])
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次"
    assert len(set(env.llm.calls)) == len(TYPES)
    assert sess(env).status == "completed"


@pytest.mark.asyncio
async def test_r3_n_coroutines_check_and_finalize(env):
    """25 个协程同时 check_and_finalize，只能有一个抢到。"""
    mk_sess(env, status="analyzing", total=2)
    for i in range(2):
        mk_seg(env, "S", i, UploadStatus.COMPLETED.value, f"文本{i}")
    res = await asyncio.gather(*[pipeline.check_and_finalize("S") for _ in range(25)])
    assert sum(1 for r in res if r) == 1, f"抢锁成功 {sum(1 for r in res if r)} 次"
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次"
    db = env.SL()
    assert db.query(AnalysisReport).count() == len(TYPES)
    assert db.query(AudioFile).filter(AudioFile.file_format == "merged").count() == 1
    db.close()


@pytest.mark.asyncio
async def test_r4_interleaved_segment_callbacks(env):
    """两段 ASR 回调交错 + finalize 同时三路并发。"""
    mk_sess(env)
    a = mk_seg(env, "S", 0)
    b = mk_seg(env, "S", 1)
    await asyncio.gather(
        pipeline.submit_segment_asr(a),
        pipeline.finalize_session("S", 2, TYPES),
        pipeline.submit_segment_asr(b),
    )
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次"
    db = env.SL()
    assert db.query(AudioFile).filter(AudioFile.file_format == "merged").count() == 1
    db.close()


@pytest.mark.asyncio
async def test_r5_repeat_finalize_during_llm(env):
    """LLM 正在跑（generating）时重复 finalize + check，不得再起一轮。"""
    mk_sess(env, status="analyzing", total=1)
    mk_seg(env, "S", 0, UploadStatus.COMPLETED.value, "内容")
    t = asyncio.create_task(pipeline.check_and_finalize("S"))
    await asyncio.sleep(0)  # 让它抢到锁并进入 LLM
    assert sess(env).status == "generating", "锁未生效：未进入 generating"
    r2 = await pipeline.finalize_session("S", 1, TYPES)
    r3 = await pipeline.check_and_finalize("S")
    assert (r2, r3) == (False, False)
    assert await t is True
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次"


# ---------- Q2: generating 重启复原 ----------

@pytest.mark.asyncio
async def test_r6_generating_recovered_on_startup(env):
    mk_sess(env, status="generating", total=2)
    mk_seg(env, "S", 0, UploadStatus.COMPLETED.value, "甲")
    mk_seg(env, "S", 1, UploadStatus.COMPLETED.value, "乙")
    stats = await pipeline.recover_pending_on_startup()
    await pipeline.wait_for_background_tasks()
    assert stats["sessions_rechecked"] == 1
    assert sess(env).status == "completed", "generating 未复原 → 永久卡死"
    assert env.llm.n == len(TYPES)


@pytest.mark.asyncio
async def test_r7_recover_processing_segment(env):
    mk_sess(env, status="analyzing", total=2)
    mk_seg(env, "S", 0, UploadStatus.COMPLETED.value, "甲")
    mk_seg(env, "S", 1, UploadStatus.PROCESSING.value)
    stats = await pipeline.recover_pending_on_startup()
    await pipeline.wait_for_background_tasks()
    assert stats["segments_resubmitted"] == 1
    assert sess(env).status == "completed"
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次"


@pytest.mark.asyncio
async def test_r8_recover_twice_no_double_llm(env):
    """连续两次启动扫描（模拟重复触发）不得重复分析。"""
    mk_sess(env, status="generating", total=1)
    mk_seg(env, "S", 0, UploadStatus.COMPLETED.value, "甲")
    await pipeline.recover_pending_on_startup()
    await pipeline.recover_pending_on_startup()
    await pipeline.wait_for_background_tasks()
    assert env.llm.n == len(TYPES), f"LLM 跑了 {env.llm.n} 次"


# ---------- Q4: 降级路径 ----------

@pytest.mark.asyncio
async def test_r9_placeholder_exact_text(env):
    env.asr.behaviour = {"S_g1.m4a": {"success": False, "text": "", "error": "boom"}}
    mk_sess(env)
    ids = [mk_seg(env, "S", i) for i in range(3)]
    await pipeline.finalize_session("S", 3, TYPES)
    for i in ids:
        await pipeline.submit_segment_asr(i)
    txt = merged(env)
    assert "[片段2：转写失败，内容缺失]" in txt, txt
    assert env.llm.n == len(TYPES)
    assert sess(env).status == "completed"


@pytest.mark.asyncio
async def test_r10_all_failed_no_llm(env):
    env.asr.behaviour = {"/x/": {"success": False, "text": "", "error": "全挂"}}
    mk_sess(env)
    ids = [mk_seg(env, "S", i) for i in range(3)]
    await pipeline.finalize_session("S", 3, TYPES)
    for i in ids:
        await pipeline.submit_segment_asr(i)
    assert env.llm.n == 0, "全段失败仍调了 LLM"
    s = sess(env)
    assert s.status == "failed" and s.error_message
    db = env.SL()
    assert db.query(AnalysisReport).count() == 0
    assert db.query(AudioFile).filter(AudioFile.file_format == "merged").count() == 0
    db.close()


@pytest.mark.asyncio
async def test_r11_empty_asr_text_treated_as_missing(env):
    """段成功但文本为空（静音）→ 目前也打成 '转写失败' 占位（记录实际行为）。"""
    env.asr.behaviour = {"S_g0.m4a": {"success": True, "text": "", "error": None}}
    mk_sess(env)
    ids = [mk_seg(env, "S", i) for i in range(2)]
    await pipeline.finalize_session("S", 2, TYPES)
    for i in ids:
        await pipeline.submit_segment_asr(i)
    txt = merged(env)
    db = env.SL()
    seg0 = db.query(AudioFile).filter(AudioFile.session_id == "S",
                                      AudioFile.segment_index == 0).first()
    st = seg0.upload_status
    db.close()
    assert st == UploadStatus.COMPLETED.value
    assert "[片段1：转写失败，内容缺失]" in txt, f"实际拼接={txt!r}"


# ---------- Q5: 并发上限 ----------

@pytest.mark.asyncio
async def test_r12_concurrency_cap(env):
    mk_sess(env)
    env.asr.yields = 20
    ids = [mk_seg(env, "S", i) for i in range(12)]
    await asyncio.gather(*[pipeline.submit_segment_asr(i) for i in ids])
    assert env.asr.peak <= 3, f"ASR 并发峰值 {env.asr.peak} > 3"
    assert env.asr.peak == 3, f"未达到 3，信号量位置可能不对；peak={env.asr.peak}"


@pytest.mark.asyncio
async def test_r13_zero_segments_edge(env):
    """total_segments=0 且无段：观察实际行为（是否误判全失败）。"""
    mk_sess(env, status="analyzing", total=0)
    r = await pipeline.check_and_finalize("S")
    print("RESULT:", r, "status=", sess(env).status, "llm=", env.llm.n)
