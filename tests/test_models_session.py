#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task 1: RecordingSession 模型 + AudioFile 分段字段 测试。
"""


def test_recording_session_defaults(db_session):
    from models import RecordingSession

    s = RecordingSession(session_id="s-1", user_id=1, title="测试录音")
    db_session.add(s)
    db_session.commit()

    assert s.status == "recording"
    assert s.total_segments is None
    assert s.created_at is not None


def test_audio_file_segment_fields_nullable(db_session):
    """存量数据没有 session_id，必须允许为空"""
    from models import AudioFile

    af = AudioFile(user_id=1, stored_filename="a.m4a", file_path="uploads/a.m4a")
    db_session.add(af)
    db_session.commit()

    assert af.session_id is None and af.segment_index is None
