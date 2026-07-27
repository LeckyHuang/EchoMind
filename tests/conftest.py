#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pytest 公共 fixtures。

关键约束：测试绝不连接 data/echodmind.db 本体，一律用独立的临时 SQLite 文件，
每个测试用例结束后清理，互不污染。
"""

import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 确保项目根目录在 sys.path 上，能 `import models`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import Base  # noqa: E402


@pytest.fixture()
def db_session():
    """提供一个基于独立临时 SQLite 文件的 db session，测试结束后销毁。"""
    tmp_dir = tempfile.mkdtemp(prefix="echomind_test_")
    db_path = Path(tmp_dir) / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
