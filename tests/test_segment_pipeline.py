#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分段流水线（services/segment_pipeline.py）测试。

覆盖 spec 4.3「任务执行与状态机」与 4.4「错误处理与降级」的全部时序与降级分支。

铁律：
- ASR 与 LLM **全部打桩**，绝不打真实厂商 API，不产生任何真实费用。
- 幂等测试断言 LLM stub 的**调用次数**恰好等于「分析类型数 × 1 轮」，
  而不是只断言「没报错」。
- 重试退避打桩为 0，测试不真睡。
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
    Base,
    User,
    AudioFile,
    AnalysisReport,
    AnalysisTaskType,
    RecordingSession,
    UploadStatus,
    AnalysisStatus,
)

import services.segment_pipeline as pipeline  # noqa: E402


# ==================== 打桩 ====================

class FakeASR:
    """ASR 打桩。results 按调用顺序给出行为：

    - str            → 成功，返回该文本
    - Exception 实例 → 抛出
    - dict           → 原样作为 transcribe 返回值（可造 success=False）

    按 file_path 分派：results 为 {file_path_substring: behaviour or [behaviours]}。
    """

    def __init__(self, behaviours=None, default="转写文本"):
        self.behaviours = behaviours or {}
        self.default = default
        self.calls = []

    async def transcribe(self, file_path: str, audio_duration_s: float = 0.0) -> dict:
        self.calls.append(file_path)
        behaviour = self.default
        for key, val in self.behaviours.items():
            if key in file_path:
                behaviour = val
                break
        if isinstance(behaviour, list):
            # 逐次消费；用尽后重复最后一个
            behaviour = behaviour.pop(0) if len(behaviour) > 1 else behaviour[0]
        if isinstance(behaviour, Exception):
            raise behaviour
        if isinstance(behaviour, dict):
            return behaviour
        return {"success": True, "text": behaviour, "error": None}


class FakeLLM:
    """LLM 打桩，记录每一次调用的 (report_type, text)。"""

    def __init__(self):
        self.calls = []

    async def analyze(self, text: str, report_type: str = None, db=None, **kwargs) -> dict:
        self.calls.append({"report_type": report_type, "text": text})
        # 让出一次控制权，暴露「LLM 进行中时的重入」这类竞态
        await asyncio.sleep(0)
        return {
            "success": True,
            "data": {"title": f"报告-{report_type}", "sections": []},
            "error": None,
        }

    @property
    def call_count(self) -> int:
        return len(self.calls)


# ==================== fixtures ====================

@pytest.fixture()
def env(monkeypatch):
    """独立临时 SQLite + 打桩的 ASR/LLM + 零退避。

    返回一个简单命名空间：env.SessionLocal / env.asr / env.llm / env.user_id
    """
    tmp_dir = tempfile.mkdtemp(prefix="echomind_pipeline_test_")
    db_path = Path(tmp_dir) / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 种子数据：一个用户 + 两个默认分析类型
    db = TestingSessionLocal()
    user = User(username="tester", password_hash="x", role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add_all([
        AnalysisTaskType(name="customer_brief", display_name="接待简报",
                         is_active=True, default_rank=1, sort_order=1),
        AnalysisTaskType(name="reception_review", display_name="接待复盘",
                         is_active=True, default_rank=2, sort_order=2),
        AnalysisTaskType(name="not_default", display_name="非默认",
                         is_active=True, default_rank=0, sort_order=3),
    ])
    db.commit()
    user_id = user.id
    db.close()

    asr = FakeASR()
    llm = FakeLLM()

    monkeypatch.setattr(pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(pipeline, "get_asr_service", lambda: asr)
    monkeypatch.setattr(pipeline, "get_llm_service", lambda: llm)
    monkeypatch.setattr(pipeline, "RETRY_BACKOFF_SECONDS", (0, 0))
    # 分享页生成依赖 auth/JWT 环境，单测里整体旁路
    monkeypatch.setattr(pipeline, "_generate_share", lambda report, db, file_name: "")

    class Env:
        pass

    e = Env()
    e.SessionLocal = TestingSessionLocal
    e.asr = asr
    e.llm = llm
    e.user_id = user_id
    e.engine = engine
    try:
        yield e
    finally:
        engine.dispose()


# ==================== 测试辅助 ====================

DEFAULT_TYPES = ["customer_brief", "reception_review"]


def make_session(env, session_id="s-1", status="recording"):
    db = env.SessionLocal()
    s = RecordingSession(
        session_id=session_id, user_id=env.user_id, title="测试录音", status=status
    )
    db.add(s)
    db.commit()
    db.close()


def add_segment(env, session_id, index, status=UploadStatus.PENDING.value, asr_text=None):
    """落库一个段（模拟 POST /segments 已写完 DB），返回 audio_file.id"""
    db = env.SessionLocal()
    af = AudioFile(
        user_id=env.user_id,
        original_filename=f"seg{index}.m4a",
        stored_filename=f"seg{index}.m4a",
        file_path=f"/tmp/echomind_fake/seg{index}_{session_id}.m4a",
        file_size=1024,
        duration=60.0,
        file_format="m4a",
        upload_status=status,
        asr_text=asr_text,
        session_id=session_id,
        segment_index=index,
    )
    db.add(af)
    db.commit()
    af_id = af.id
    db.close()
    return af_id


def get_session(env, session_id="s-1"):
    db = env.SessionLocal()
    try:
        return db.query(RecordingSession).filter(
            RecordingSession.session_id == session_id
        ).first()
    finally:
        db.close()


def get_reports(env):
    db = env.SessionLocal()
    try:
        return db.query(AnalysisReport).all()
    finally:
        db.close()


def merged_text_of(env, session_id="s-1"):
    """取合并产生的虚拟 AudioFile 的 asr_text"""
    db = env.SessionLocal()
    try:
        s = db.query(RecordingSession).filter(
            RecordingSession.session_id == session_id
        ).first()
        if not s or not s.merged_file_id:
            return None
        af = db.query(AudioFile).filter(AudioFile.id == s.merged_file_id).first()
        return af.asr_text if af else None
    finally:
        db.close()


# ==================== 测试用例 ====================

@pytest.mark.asyncio
async def test_finalize_before_asr_done(env):
    """finalize 早于 ASR 完成：最后一段转写完时触发分析，且只触发一次。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(3)]

    # 先 finalize（此时三段都还没转写）
    triggered = await pipeline.finalize_session("s-1", 3, DEFAULT_TYPES)
    assert triggered is False, "段未到齐时 finalize 不应触发分析"
    assert env.llm.call_count == 0
    assert get_session(env).status == "analyzing"

    # 再逐段跑 ASR
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    assert env.llm.call_count == len(DEFAULT_TYPES), "分析必须且只能跑一轮"
    assert get_session(env).status == "completed"
    assert len(get_reports(env)) == len(DEFAULT_TYPES)


@pytest.mark.asyncio
async def test_finalize_after_asr_done(env):
    """finalize 晚于全部 ASR 完成：finalize 当场触发分析，且只触发一次。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(3)]

    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    # 还没 finalize，绝不能提前分析
    assert env.llm.call_count == 0
    assert get_session(env).status == "recording"

    triggered = await pipeline.finalize_session("s-1", 3, DEFAULT_TYPES)
    assert triggered is True
    assert env.llm.call_count == len(DEFAULT_TYPES)
    assert get_session(env).status == "completed"


@pytest.mark.asyncio
async def test_check_and_finalize_is_idempotent(env):
    """连续调 3 次 check_and_finalize，LLM 只被调用一轮。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(2)]
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)
    await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)

    baseline = env.llm.call_count
    assert baseline == len(DEFAULT_TYPES)

    results = [await pipeline.check_and_finalize("s-1") for _ in range(3)]
    assert results == [False, False, False]
    assert env.llm.call_count == baseline, "重复到齐检查不得再调一次 LLM"
    assert len(get_reports(env)) == len(DEFAULT_TYPES)


@pytest.mark.asyncio
async def test_concurrent_finalize_and_last_segment_asr(env):
    """真实竞态：finalize 与最后一段 ASR 完成在同一轮事件循环里并发发生。

    两个独立事件都会调到齐检查，无论谁先谁后，分析必须且只能跑一轮。
    """
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(3)]
    # 前两段先完成
    for af_id in ids[:2]:
        await pipeline.submit_segment_asr(af_id)
    assert env.llm.call_count == 0

    # finalize 与最后一段 ASR 同时发起
    await asyncio.gather(
        pipeline.finalize_session("s-1", 3, DEFAULT_TYPES),
        pipeline.submit_segment_asr(ids[2]),
    )

    assert env.llm.call_count == len(DEFAULT_TYPES), (
        f"并发下分析跑了 {env.llm.call_count / max(len(DEFAULT_TYPES), 1)} 轮，幂等锁失效"
    )
    assert len(get_reports(env)) == len(DEFAULT_TYPES)
    assert get_session(env).status == "completed"


@pytest.mark.asyncio
async def test_many_concurrent_check_and_finalize(env):
    """10 个到齐检查同时涌入，只能有一个抢到锁。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(2)]
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    db = env.SessionLocal()
    s = db.query(RecordingSession).filter(RecordingSession.session_id == "s-1").first()
    s.total_segments = 2
    s.task_types = DEFAULT_TYPES
    s.status = "analyzing"
    db.commit()
    db.close()

    results = await asyncio.gather(*[pipeline.check_and_finalize("s-1") for _ in range(10)])
    assert sum(1 for r in results if r) == 1, "有且只有一次到齐检查可以触发分析"
    assert env.llm.call_count == len(DEFAULT_TYPES)
    assert len(get_reports(env)) == len(DEFAULT_TYPES)


@pytest.mark.asyncio
async def test_segments_arrive_out_of_order(env):
    """段 2 先于段 0 到达，拼接后文本顺序仍为 0,1,2。"""
    make_session(env)
    env.asr.behaviours = {
        "seg0_": "内容零",
        "seg1_": "内容壹",
        "seg2_": "内容贰",
    }
    id2 = add_segment(env, "s-1", 2)
    id0 = add_segment(env, "s-1", 0)
    id1 = add_segment(env, "s-1", 1)

    await pipeline.finalize_session("s-1", 3, DEFAULT_TYPES)
    for af_id in (id2, id0, id1):
        await pipeline.submit_segment_asr(af_id)

    text = merged_text_of(env)
    assert text is not None
    assert text.index("内容零") < text.index("内容壹") < text.index("内容贰")
    # LLM 拿到的正是这份有序文本
    assert env.llm.calls[0]["text"] == text


@pytest.mark.asyncio
async def test_duplicate_finalize_is_idempotent(env):
    """重复 finalize 只更新字段，不重复分析。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(2)]
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    first = await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)
    assert first is True
    assert env.llm.call_count == len(DEFAULT_TYPES)

    second = await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)
    third = await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)
    assert second is False and third is False
    assert env.llm.call_count == len(DEFAULT_TYPES), "重复 finalize 不得重复扣 LLM 费用"
    assert get_session(env).status == "completed"
    assert len(get_reports(env)) == len(DEFAULT_TYPES)


@pytest.mark.asyncio
async def test_one_segment_asr_failed_degrades(env):
    """段 1 转写失败：报告仍生成，拼接文本含 '[片段2：转写失败，内容缺失]'。"""
    make_session(env)
    env.asr.behaviours = {
        "seg0_": "内容零",
        "seg1_": {"success": False, "text": "", "error": "厂商 500"},
        "seg2_": "内容贰",
    }
    ids = [add_segment(env, "s-1", i) for i in range(3)]
    await pipeline.finalize_session("s-1", 3, DEFAULT_TYPES)
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    text = merged_text_of(env)
    assert "[片段2：转写失败，内容缺失]" in text
    assert "内容零" in text and "内容贰" in text
    assert env.llm.call_count == len(DEFAULT_TYPES), "缺段必须降级出报告，不是不出"
    assert get_session(env).status == "completed"

    db = env.SessionLocal()
    seg1 = db.query(AudioFile).filter(
        AudioFile.session_id == "s-1", AudioFile.segment_index == 1
    ).first()
    assert seg1.upload_status == UploadStatus.FAILED.value
    db.close()


@pytest.mark.asyncio
async def test_placeholder_uses_segment_index_not_position(env):
    """段号有洞（0, 1, 3；段 2 从未落库）时，占位编号必须用真实 segment_index+1，
    不能用列表位置序号——否则用户看到的「片段N」会和真实段号错位。"""
    make_session(env)
    env.asr.behaviours = {
        "seg0_": "内容零",
        "seg1_": {"success": False, "text": "", "error": "厂商 500"},
        "seg3_": "内容三",
    }
    ids = [add_segment(env, "s-1", i) for i in (0, 1, 3)]
    await pipeline.finalize_session("s-1", 3, DEFAULT_TYPES)
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    text = merged_text_of(env)
    # 真实段号 1（位置序号本应是 2）转写失败 → 占位必须写「片段2」
    assert "[片段2：转写失败，内容缺失]" in text, f"实际拼接={text!r}"
    # 真实段号 3（位置序号本应是 3）→ 占位/正文必须写「片段4」，不是「片段3」
    assert "[片段4]" in text, f"实际拼接={text!r}"
    assert "[片段3" not in text, f"用了位置序号而非 segment_index：{text!r}"


@pytest.mark.asyncio
async def test_all_segments_failed(env):
    """全部段失败：session 转 failed，LLM 一次都不调。"""
    make_session(env)
    env.asr.default = {"success": False, "text": "", "error": "厂商全挂"}
    ids = [add_segment(env, "s-1", i) for i in range(2)]
    await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    s = get_session(env)
    assert s.status == "failed"
    assert s.error_message
    assert env.llm.call_count == 0, "全段失败绝不能调 LLM"
    assert get_reports(env) == []


@pytest.mark.asyncio
async def test_single_segment_session(env):
    """不分段的普通录音（total_segments=1）走完整流程。"""
    make_session(env, "s-single")
    env.asr.default = "一整段的内容"
    af_id = add_segment(env, "s-single", 0)

    await pipeline.submit_segment_asr(af_id)
    assert env.llm.call_count == 0

    triggered = await pipeline.finalize_session("s-single", 1, DEFAULT_TYPES)
    assert triggered is True
    assert env.llm.call_count == len(DEFAULT_TYPES)
    s = get_session(env, "s-single")
    assert s.status == "completed"
    assert s.merged_file_id is not None
    assert "一整段的内容" in merged_text_of(env, "s-single")


@pytest.mark.asyncio
async def test_recover_pending_on_startup(env):
    """把某段置为 processing 后调续跑扫描，该段被重新提交并跑完。"""
    make_session(env)
    done_id = add_segment(env, "s-1", 0, status=UploadStatus.COMPLETED.value,
                          asr_text="已完成的段")
    stuck_id = add_segment(env, "s-1", 1, status=UploadStatus.PROCESSING.value)
    await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)
    assert env.llm.call_count == 0, "有段卡在 processing，不该分析"

    stats = await pipeline.recover_pending_on_startup()
    assert stats["segments_resubmitted"] == 1
    assert stats["sessions_rechecked"] >= 1
    await pipeline.wait_for_background_tasks()

    db = env.SessionLocal()
    stuck = db.query(AudioFile).filter(AudioFile.id == stuck_id).first()
    assert stuck.upload_status == UploadStatus.COMPLETED.value
    db.close()
    assert done_id is not None
    assert env.llm.call_count == len(DEFAULT_TYPES)
    assert get_session(env).status == "completed"


@pytest.mark.asyncio
async def test_recover_resets_generating_session(env):
    """重启时卡在 generating 的 session 必须退回 analyzing 并重跑，否则永远卡死。"""
    make_session(env, "s-1", status="generating")
    add_segment(env, "s-1", 0, status=UploadStatus.COMPLETED.value, asr_text="甲")
    add_segment(env, "s-1", 1, status=UploadStatus.COMPLETED.value, asr_text="乙")
    db = env.SessionLocal()
    s = db.query(RecordingSession).filter(RecordingSession.session_id == "s-1").first()
    s.total_segments = 2
    s.task_types = DEFAULT_TYPES
    db.commit()
    db.close()

    stats = await pipeline.recover_pending_on_startup()
    assert stats["sessions_rechecked"] == 1
    await pipeline.wait_for_background_tasks()

    assert get_session(env).status == "completed", "generating 未退回 analyzing → 永久卡死"
    assert env.llm.call_count == len(DEFAULT_TYPES)


@pytest.mark.asyncio
async def test_asr_retry_twice_then_fail(env):
    """ASR 连续抛错 3 次（首次 + 重试 2 次）后该段标 failed。"""
    make_session(env)
    env.asr.default = RuntimeError("网络炸了")
    af_id = add_segment(env, "s-1", 0)

    await pipeline.submit_segment_asr(af_id)

    assert len(env.asr.calls) == 3, f"应为 1 次首发 + 2 次重试，实际 {len(env.asr.calls)} 次"
    db = env.SessionLocal()
    af = db.query(AudioFile).filter(AudioFile.id == af_id).first()
    assert af.upload_status == UploadStatus.FAILED.value
    db.close()


@pytest.mark.asyncio
async def test_asr_succeeds_on_second_attempt(env):
    """首次失败、第二次成功：该段 completed，不多调一次。"""
    make_session(env)
    env.asr.default = [RuntimeError("抖了一下"), "第二次成功"]
    af_id = add_segment(env, "s-1", 0)

    await pipeline.submit_segment_asr(af_id)

    assert len(env.asr.calls) == 2
    db = env.SessionLocal()
    af = db.query(AudioFile).filter(AudioFile.id == af_id).first()
    assert af.upload_status == UploadStatus.COMPLETED.value
    assert af.asr_text == "第二次成功"
    db.close()


@pytest.mark.asyncio
async def test_asr_concurrency_capped_at_three(env):
    """段 ASR 全局并发上限为 3。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(8)]

    state = {"inflight": 0, "peak": 0}

    class SlowASR:
        calls = []

        async def transcribe(self, file_path, audio_duration_s=0.0):
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
            await asyncio.sleep(0.02)
            state["inflight"] -= 1
            return {"success": True, "text": "x", "error": None}

    slow = SlowASR()
    pipeline.get_asr_service = lambda: slow  # monkeypatch fixture 会在结束时还原
    await asyncio.gather(*[pipeline.submit_segment_asr(i) for i in ids])

    assert state["peak"] <= 3, f"并发峰值 {state['peak']} 超过上限 3"
    assert state["peak"] > 1, "信号量把并发压成串行了，上限设置有误"


@pytest.mark.asyncio
async def test_reports_bound_to_merged_file_and_user(env):
    """报告挂在虚拟 merged AudioFile 上，归属会话所有者（照抄 merge_analyze 的写法）。"""
    make_session(env)
    ids = [add_segment(env, "s-1", i) for i in range(2)]
    await pipeline.finalize_session("s-1", 2, DEFAULT_TYPES)
    for af_id in ids:
        await pipeline.submit_segment_asr(af_id)

    s = get_session(env)
    db = env.SessionLocal()
    merged = db.query(AudioFile).filter(AudioFile.id == s.merged_file_id).first()
    assert merged.file_format == "merged"
    assert merged.file_path == ""
    assert merged.session_id == "s-1"
    assert merged.upload_status == UploadStatus.COMPLETED.value
    reports = db.query(AnalysisReport).all()
    assert {r.report_type for r in reports} == set(DEFAULT_TYPES)
    assert all(r.file_id == merged.id for r in reports)
    assert all(r.user_id == env.user_id for r in reports)
    assert all(r.status == AnalysisStatus.COMPLETED.value for r in reports)
    db.close()
