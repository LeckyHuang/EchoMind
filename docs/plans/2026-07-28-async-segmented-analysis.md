# 异步分析 + 录音分段串联 实施计划

> **For agentic workers:** 按任务顺序实施，每个任务自带测试与提交。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 让用户只装 App 就能完成「录音 → 自动分段上传 → 一份完整报告」的闭环，长录音边录边转写，录完 3-5 分钟出报告。

**Architecture:** 后端 `POST /api/v1/segments` 收段即刻异步转写（asyncio task + DB 状态表，进程内并发上限 3），`finalize` 声明总段数，「到齐检查」作为唯一且幂等的分析触发点，拼接文本后复用现有 `analyze/merge` 逻辑出一份报告。App 端 15 分钟自动切段、自动入队上传、轮询状态、原生渲染报告。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + SQLite + uvicorn(workers=1)；Android Java + OkHttp 4.12 + RecyclerView。

**设计依据：** `docs/specs/2026-07-28-async-segmented-analysis-design.md`（以下简称 spec）。本计划不重复 spec 的论证，只给可执行步骤。**实施中若发现与 spec 冲突，停下来报告，不要自行改设计。**

## Global Constraints

- 分段阈值：**15 分钟**（`SEG_MS = 15 * 60 * 1000`）
- 段 ASR 全局并发上限：**3**
- uvicorn **必须 `--workers 1`**，这是正确性前提不是性能参数
- `POST /api/v1/analyze` 同步接口**原样保留不动**，一行都不改
- 段级状态复用 `UploadStatus` 枚举（`pending`/`processing`/`completed`/`failed`），不新建枚举
- 会话状态取值：`recording` / `analyzing` / `completed` / `failed`
- `session_id` 由**客户端**生成（UUID v4），服务端不生成
- `segment_index` 从 **0** 起
- 所有新接口挂 `/api/v1`，Bearer Token 鉴权，数据归属 `current_user`
- 本轮不做断点续传、不做推送通知

---

## 文件结构

**后端 `echomind`：**

| 文件 | 责任 |
|---|---|
| `models.py`（改） | 新增 `RecordingSession` 模型；`AudioFile` 加 `session_id` / `segment_index` 两列 |
| `migrations/2026_07_28_add_sessions.py`（新） | 一次性迁移脚本：建表 + 加列，幂等可重跑 |
| `services/segment_pipeline.py`（新） | **核心**。段 ASR 任务提交、并发信号量、到齐检查、拼接与分析触发、启动续跑扫描 |
| `routers/session_router.py`（新） | `POST /segments`、`POST /sessions/{id}/finalize`、`GET /sessions/{id}`、`GET /sessions` |
| `routers/report_router.py`（改） | 新增非 admin 别名路由 `GET /api/v1/reports/{report_id}` |
| `main.py`（改） | 注册 session_router；startup 事件调用续跑扫描。**不动 `/api/v1/analyze`** |
| `scheduler.py`（改） | 加一条清理：`recording` 超 24 小时的 session 标 failed |
| `tests/test_segment_pipeline.py`（新） | 状态机时序、幂等、降级的全部测试 |
| `DEPLOY.md` / systemd unit（改） | workers 2 → 1 |

**App `echomind-app`：**

| 文件 | 责任 |
|---|---|
| `service/VoiceRecordService.java`（改） | `SEG_MS` 改 15 分钟；开录生成 session_id；回调带 session_id + segmentIndex |
| `api/SegmentApi.java`（新） | `POST /segments`、`POST /sessions/{id}/finalize`、`GET /sessions/{id}`、`GET /sessions` |
| `upload/SegmentUploadQueue.java`（新） | 段落盘即入队，串行上传，失败标记（本轮不自动重试） |
| `ui/MainActivity.java`（改） | 列表按 session 聚合；停止录音时选类型并 finalize；页面可见时 10s 轮询 |
| `ui/ReportActivity.java`（新） | RecyclerView 多 ViewType 渲染 sections |
| `ui/adapter/ReportSectionAdapter.java`（新） | 五种段落类型的 ViewHolder |

---

## 任务分解

### Task 1：数据层 + 迁移 + 部署配置

**Files:**
- Modify: `models.py`
- Create: `migrations/2026_07_28_add_sessions.py`
- Modify: `DEPLOY.md`（uvicorn workers）
- Test: `tests/test_models_session.py`

**Interfaces（后续任务依赖这些名字，必须一字不差）:**
- Produces: `RecordingSession` 模型，字段见下；`AudioFile.session_id: str|None`、`AudioFile.segment_index: int|None`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models_session.py
def test_recording_session_defaults(db_session):
    from models import RecordingSession
    s = RecordingSession(session_id="s-1", user_id=1, title="测试录音")
    db_session.add(s); db_session.commit()
    assert s.status == "recording"
    assert s.total_segments is None
    assert s.created_at is not None

def test_audio_file_segment_fields_nullable(db_session):
    """存量数据没有 session_id，必须允许为空"""
    from models import AudioFile
    af = AudioFile(user_id=1, stored_filename="a.m4a", file_path="uploads/a.m4a")
    db_session.add(af); db_session.commit()
    assert af.session_id is None and af.segment_index is None
```

- [ ] **Step 2: 跑测试确认失败** — `pytest tests/test_models_session.py -v`，预期 `ImportError: cannot import name 'RecordingSession'`

- [ ] **Step 3: 加模型**

在 `models.py` 中 `AnalysisReport` 之后新增：

```python
class RecordingSession(Base):
    """录音会话：一次录音（可含多段）"""
    __tablename__ = "recording_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), unique=True, nullable=False, index=True)  # 客户端生成
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=True)
    status = Column(String(20), default="recording", index=True)  # recording/analyzing/completed/failed
    total_segments = Column(Integer, nullable=True)   # finalize 时由客户端声明
    task_types = Column(JSON, nullable=True)          # 分析类型名列表
    supplementary_text = Column(Text, nullable=True)
    merged_file_id = Column(Integer, ForeignKey("audio_files.id", ondelete="SET NULL"), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

在 `AudioFile` 类中 `asr_text` 之后加两列：

```python
    session_id = Column(String(36), nullable=True, index=True)  # 所属会话，单文件上传为空
    segment_index = Column(Integer, nullable=True)              # 段序号，从 0 起
```

并在 `AudioFile.to_dict()` 返回值里补 `"session_id"` 和 `"segment_index"`。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 写迁移脚本** — `migrations/2026_07_28_add_sessions.py`，要求**幂等可重跑**（先查 `PRAGMA table_info(audio_files)`，列已存在就跳过；建表用 `CREATE TABLE IF NOT EXISTS`）。脚本入口 `python migrations/2026_07_28_add_sessions.py`，打印每一步做了什么或跳过了什么。

- [ ] **Step 6: 对 `data/echodmind.db` 的副本实跑迁移**

```bash
cp data/echodmind.db /tmp/mig_test.db && DATABASE_URL=sqlite:////tmp/mig_test.db python migrations/2026_07_28_add_sessions.py && DATABASE_URL=sqlite:////tmp/mig_test.db python migrations/2026_07_28_add_sessions.py
```

跑两遍，第二遍必须全部报「已存在，跳过」且不报错。然后用 sqlite3 确认 6 条存量 `audio_files` 记录完好、新列为 NULL。

- [ ] **Step 7: 改 uvicorn workers** — `DEPLOY.md:155` 的 systemd `ExecStart` 里 `--workers 2` → `--workers 1`，并在旁边加注释：`# 必须为 1：分段任务的启动续跑扫描在多 worker 下会重复执行，且 SQLite 并发写会锁`

- [ ] **Step 8: 提交** — `git add models.py migrations/ DEPLOY.md tests/test_models_session.py && git commit -m "feat(session): 新增 RecordingSession 模型与分段字段，uvicorn 降为单 worker"`

---

### Task 2：分段流水线核心（状态机）

> **这是全计划风险最高的任务。** 到齐检查的幂等性与时序竞争是核心难点，实施时优先把测试写全再写实现。

**Files:**
- Create: `services/segment_pipeline.py`
- Test: `tests/test_segment_pipeline.py`

**Interfaces:**
- Consumes: Task 1 的 `RecordingSession`、`AudioFile.session_id/segment_index`
- Produces（Task 3 的路由层调用这些）:
  - `async def submit_segment_asr(audio_file_id: int) -> None` — 提交某段 ASR（受信号量限流），完成后自动调到齐检查
  - `async def check_and_finalize(session_id: str) -> bool` — 到齐检查，**幂等**；触发了分析返回 True，否则 False
  - `async def recover_pending_on_startup() -> dict` — 启动续跑扫描，返回 `{"segments_resubmitted": int, "sessions_rechecked": int}`

- [ ] **Step 1: 写全部失败测试**

ASR 与 LLM 全部打桩（monkeypatch `asr_service.transcribe` 与 `llm_service.analyze`），不打真实厂商 API。必须覆盖：

```python
async def test_finalize_before_asr_done(...):
    """finalize 早于 ASR 完成：最后一段转写完时触发分析"""

async def test_finalize_after_asr_done(...):
    """finalize 晚于全部 ASR 完成：finalize 当场触发分析"""
    # 上面两个时序都必须触发分析，且只触发一次

async def test_check_and_finalize_is_idempotent(...):
    """连续调 3 次 check_and_finalize，LLM 只被调用一轮"""

async def test_segments_arrive_out_of_order(...):
    """段 2 先于段 0 到达，拼接后文本顺序仍为 0,1,2"""

async def test_duplicate_finalize_is_idempotent(...):
    """重复 finalize 只更新字段，不重复分析"""

async def test_one_segment_asr_failed_degrades(...):
    """段 1 转写失败：报告仍生成，拼接文本含 '[片段2：转写失败，内容缺失]'"""

async def test_all_segments_failed(...):
    """全部段失败：session 转 failed，LLM 一次都不调"""

async def test_single_segment_session(...):
    """不分段的普通录音（total_segments=1）走完整流程——验证归一模型没搞坏简单场景"""

async def test_recover_pending_on_startup(...):
    """把某段置为 processing 后调续跑扫描，该段被重新提交"""

async def test_asr_retry_twice_then_fail(...):
    """ASR 连续抛错 3 次（首次 + 重试 2 次）后该段标 failed"""
```

- [ ] **Step 2: 跑测试确认全部失败** — `pytest tests/test_segment_pipeline.py -v`

- [ ] **Step 3: 实现 `services/segment_pipeline.py`**

要点（其余自由发挥，但这几条是硬约束）：

```python
_asr_semaphore = asyncio.Semaphore(3)   # 全局并发上限，防打爆豆包配额

async def check_and_finalize(session_id: str) -> bool:
    """唯一的分析触发点。幂等：靠 session.status 的原子推进保证只跑一轮。"""
    # 1. 取 session；status != "analyzing" 直接 return False
    #    （recording 说明还没 finalize；completed/failed 说明已经跑过）
    # 2. total_segments 为 None -> return False
    # 3. 查该 session 所有段，数量 < total_segments -> return False
    # 4. 任一段仍在 pending/processing -> return False
    # 5. 全部 failed -> session.status = "failed"，写 error_message，return False
    # 6. 抢占：session.status = "generating"，commit
    #    —— 这一步必须在调 LLM 之前完成，它就是幂等锁
    # 7. 按 segment_index 排序拼接，失败段插占位
    #    "[片段{i+1}：转写失败，内容缺失]"
    # 8. 建虚拟 merged AudioFile（file_format="merged", file_path=""），
    #    照抄 routers/file_router.py:487-502 的现有写法
    # 9. 复用该处的 LLM 并发分析 + 写报告 + auto_generate_share
    # 10. session.merged_file_id / status="completed"，commit
```

**注意**：步骤 6 引入了一个中间状态 `generating`，spec 的状态表里没写。它是实现幂等所必需的（`analyzing` 表示"等段到齐"，`generating` 表示"已进入 LLM 分析"）。**实施时把它补进 spec 的状态表**，别让文档和代码不一致。

`submit_segment_asr` 要点：段状态 `pending → processing`（进信号量前置位）→ 调 ASR（失败重试 2 次，退避 5s / 15s）→ 写 `asr_text` + `completed`/`failed` → 调 `check_and_finalize`。

`recover_pending_on_startup` 要点：扫 `upload_status IN ('pending','processing')` 且 `session_id IS NOT NULL` 的段重新提交；对所有 `status IN ('analyzing','generating')` 的 session 跑一次到齐检查（`generating` 的要先退回 `analyzing`，否则永远不会重跑）。

- [ ] **Step 4: 跑测试确认全绿** — `pytest tests/test_segment_pipeline.py -v`

- [ ] **Step 5: 补 spec 状态表** — 在 spec 4.3 节状态流转里补 `generating` 态与说明

- [ ] **Step 6: 提交** — `git commit -m "feat(session): 分段流水线核心，到齐检查幂等 + 启动续跑"`

---

### Task 3：会话接口 + 报告别名路由 + 清理

**Files:**
- Create: `routers/session_router.py`
- Modify: `routers/report_router.py`（加别名路由）、`main.py`（注册路由 + startup 钩子）、`scheduler.py`
- Test: `tests/test_session_api.py`

**Interfaces:**
- Consumes: Task 2 的 `submit_segment_asr` / `check_and_finalize` / `recover_pending_on_startup`

- [ ] **Step 1: 写失败测试**（用 FastAPI `TestClient`，ASR/LLM 打桩）

```python
def test_upload_segment_creates_session_implicitly(client, auth_headers):
    """首段上传时 session 不存在，应隐式创建"""
    r = client.post("/api/v1/segments", headers=auth_headers,
                    files={"file": ("s0.m4a", b"fake", "audio/m4a")},
                    data={"session_id": "s-1", "segment_index": 0})
    assert r.status_code == 202
    assert r.json()["status"] == "pending"

def test_upload_same_index_twice_overwrites(client, auth_headers): ...
def test_finalize_sets_total_and_types(client, auth_headers): ...
def test_get_session_returns_progress(client, auth_headers): ...
def test_cannot_access_other_users_session(client, other_auth_headers):
    """越权：查别人的 session 应 403/404"""
def test_report_alias_route_matches_admin_route(client, auth_headers):
    """GET /api/v1/reports/{id} 与 /api/v1/admin/reports/{id} 返回一致"""
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现路由**，签名严格按 spec 4.2 节。`GET /sessions/{id}` 返回体字段一字不差：`session_id` / `status` / `total_segments` / `segments[]{segment_index,status,duration}` / `progress{asr_done,asr_total}` / `report_ids[]` / `error_message`。

- [ ] **Step 4: 注册 + startup 钩子** — `main.py` 注册 session_router；startup 事件里 `await recover_pending_on_startup()` 并 log 返回的计数

- [ ] **Step 5: scheduler 清理** — 加一条：`recording` 状态且 `created_at` 早于 24 小时前的 session 标 `failed`、`error_message="录音未正常结束"`，并删除其段音频文件

- [ ] **Step 6: 跑全量测试** — `pytest tests/ -v`，**必须全绿**，尤其确认既有测试没被打破

- [ ] **Step 7: 真实起服务冒烟**（不是只跑测试）

```bash
source venv/bin/activate && uvicorn main:app --port 8099 --workers 1
```

用 curl 走一遍：登录拿 token → 传两段真实小音频 → finalize → 轮询到 completed → 取报告正文。把每一步的 curl 与响应贴进交付报告。

- [ ] **Step 8: 提交** — `git commit -m "feat(session): 分段上传/finalize/状态查询接口 + 报告别名路由"`

---

### Task 4：App 录音分段 + 自动上传 + finalize

**Files:**
- Modify: `service/VoiceRecordService.java`、`ui/MainActivity.java`
- Create: `api/SegmentApi.java`、`upload/SegmentUploadQueue.java`

**Interfaces:**
- Consumes: Task 3 的四个接口（契约已在 spec 4.2 冻结，**不需要等后端做完**，按 spec 写即可）

- [ ] **Step 1: `SEG_MS` 改 15 分钟** — `VoiceRecordService.java:21`，`120 * 60 * 1000` → `15 * 60 * 1000`
- [ ] **Step 2: 开录时生成 session_id**（UUID v4），录音停止前保持不变；`onSegmentComplete` 回调签名加 `String sessionId, int segmentIndex`
- [ ] **Step 3: 写 `SegmentApi.java`** — 四个方法，照 `UploadApi.java` 现有 OkHttp 写法。**上传超时可以调回 120s**（不再需要 1800s，段上传是纯传输不含分析）
- [ ] **Step 4: 写 `SegmentUploadQueue.java`** — 单线程串行队列，段落盘即入队；上传成功/失败写回本地状态；失败**不自动重试**（本轮非目标），标记为失败供 UI 展示
- [ ] **Step 5: 停止录音流程改造** — 停止录音时弹分析类型选择（原本在上传前弹），选完调 `finalize(sessionId, totalSegments, taskTypes)`
- [ ] **Step 6: 编译** — `./gradlew assembleDebug`，必须 BUILD SUCCESSFUL
- [ ] **Step 7: 真机/模拟器验证** — 把 `SEG_MS` 临时改成 60 秒录一段 3 分钟的音，确认切出 3 段且自动全部上传（看后端日志确认收到 3 个 segment_index）。**验证完把 SEG_MS 改回 15 分钟**
- [ ] **Step 8: 提交**

---

### Task 5：App 轮询 + 会话聚合列表

**Files:** Modify `ui/MainActivity.java`

- [ ] **Step 1: 列表改为按 session 聚合** — 调 `GET /api/v1/sessions`，一次录音一行，显示标题/段数/状态
- [ ] **Step 2: 轮询** — 页面 `onResume` 起 10 秒轮询未完成的 session，`onPause` 停止；`completed`/`failed` 后停止该 session 的轮询
- [ ] **Step 3: 进度展示** — 用 `progress{asr_done,asr_total}` 显示「已转写 11/12 段」
- [ ] **Step 4: 编译 + 真机验证** — 确认轮询在后台不跑（切后台后看日志确认无请求）
- [ ] **Step 5: 提交**

---

### Task 6：App 原生报告渲染

**Files:** Create `ui/ReportActivity.java`、`ui/adapter/ReportSectionAdapter.java`

> 这个任务**零依赖新后端接口**——`report_data` 的 sections 契约在现网已经存在，可最先开工。

- [ ] **Step 1: 读契约** — 读 `routers/report_router.py` 的 `_body_generic()` 与 `frontend/report.js`，确认五种段落类型（`text`/`list`/`kv`/`tags`/`actions`）各自的字段结构。**以代码为准，不要照抄本计划的概括**
- [ ] **Step 2: 写 `ReportSectionAdapter`** — RecyclerView 多 ViewType，五种段落各一个 ViewHolder；遇到未知 `type` 降级为纯文本展示而不是崩溃
- [ ] **Step 3: 写 `ReportActivity`** — 调 `GET /api/v1/reports/{report_id}` 取 `report_data` 渲染；加载中/失败态要有
- [ ] **Step 4: 入口接线** — 报告列表点击优先进 `ReportActivity`；`ReportWebViewActivity` 保留给老数据与分享页
- [ ] **Step 5: 编译 + 用现网真实 report_id 验证渲染**（现网 db 里有 4 条完整报告可用）
- [ ] **Step 6: 提交**

---

### Task 7：端到端集成验证

- [ ] **Step 1: 部署到测试环境**，确认 `--workers 1` 生效（`ps aux | grep uvicorn` 只有一个 worker 进程）
- [ ] **Step 2: 真机录一段跨 2 段的真实录音**（`SEG_MS` 保持 15 分钟，录 20 分钟），走完整闭环
- [ ] **Step 3: 断言**：产出**一份**报告；报告内容覆盖全程（能找到第 1 段和第 2 段各自的独有内容）；App 内原生页面正常渲染；全程未打开网页后台
- [ ] **Step 4: 计时**：记录「停止录音」到「报告可见」的墙钟时间，写进报告
- [ ] **Step 5: 重启验证**：在第 2 段 ASR 处理中时 `systemctl restart`，确认重启后该段被续跑、最终仍出报告
- [ ] **Step 6: 回归**：用旧版 App（或直接 curl `/api/v1/analyze`）确认老同步接口未被打破

---

## 派发方案与模型建议

### 并行结构

**核心洞察：前后端是两个独立仓库，git 索引不共享，两条泳道可真并行。** 同一仓库内的任务必须串行（多 agent 共享 git 索引会互相污染），跨仓库则无此约束。

```
后端泳道(echomind)：   Task1 ──→ Task2 ──→ Task3 ──┐
                                                    ├──→ Task7 端到端
App 泳道(echomind-app)：Task6 ──→ Task4 ──→ Task5 ──┘
```

App 泳道把零依赖的 Task 6 放最前，让它与后端 Task 1 同时开跑；Task 4/5 按 spec 冻结的接口契约写，不必等后端完工。

### 模型选型与理由

| 任务 | 模型 | 理由 |
|---|---|---|
| Task 1 数据层+迁移 | **sonnet** | 照 spec 建模，规格明确 |
| **Task 2 流水线核心** | **opus** | 幂等锁、时序竞争、重启续跑，是全计划唯一需要深度推理的部分。这里省钱最亏 |
| Task 3 接口层 | **sonnet** | 照 spec 4.2 接线 |
| Task 4 App 分段上传 | **sonnet** | 常规 Android 开发 |
| Task 5 App 轮询列表 | **sonnet** | 同上；与 Task 4 改同一个 `MainActivity`，**必须串行，不可与 Task 4 并行** |
| Task 6 App 报告渲染 | **sonnet** | 契约现成，纯体力活 |
| Task 2 验收 | **opus** | 见下 |

### 验收分档

按「风险 × 不可自证性」分：

- **Task 1 / 3（免独立验收）**：pytest 断言即规格，机器可证。主控看 diff + 确认测试真跑过即可。
- **Task 2（必须 opus 独立验收）**：状态机的幂等和竞态**执行者自己写测试自己跑，大概率全绿**——他测的是自己脑中的时序模型。派独立 opus 冷启动，只给 spec + diff 范围，要求**自己另写时序用例**（尤其并发重入、finalize 与最后一段 ASR 同时到达），真实起服务验证。范围盒：只验 `services/segment_pipeline.py` 这一份 diff；时间盒：20 分钟。
- **Task 4/5/6（人工验收）**：Android 端无自动化测试基建，本轮不为此新建（过度工程）。靠编译通过 + 真机跑一遍 + 主控审 diff。
- **Task 7（主控亲自把关）**：端到端是唯一能证明「闭环真的成了」的证据，不外包。

### 存档点

每个 Task 的每个 Step 完成即 commit，中断后从最后一个 commit 继续。派发 prompt 里写死：**禁止转包子代理**、**禁止 `git add .` / `git reset`（只 add 自己改的文件）**、每完成一步立即提交。

### 成本预估与省钱点

一次 opus（Task 2）+ 一次 opus 验收 + 五次 sonnet。省钱的地方在于：Task 4/5/6 三个 App 任务本可以合成一个 agent 跑完（同一仓库、同一批文件、固定开销大于单个任务的开发量），**但 Task 4 和 5 都改 `MainActivity.java`，合并反而更安全**——所以实际建议：**Task 4+5 合并为一个 sonnet agent**，Task 6 单独一个。这样 App 泳道只需 2 个 agent 而非 3 个。

最终派发：**5 个 agent**（sonnet×4 + opus×1）+ **1 个 opus 验收** + 主控做 Task 7。

---

## 自查

**spec 覆盖**：4.1 数据模型 → Task 1；4.2 接口 → Task 3；4.3 任务执行与状态机 → Task 2；4.4 错误处理降级 → Task 2（测试已覆盖全部降级分支）+ Task 3（孤儿 session 清理）；4.5 App 改造 → Task 4/5/6；第 6 节部署影响 → Task 1 Step 7（workers）+ Task 1 Step 5-6（迁移）。无遗漏。

**已知的计划-spec 偏差**：Task 2 引入了 spec 未写的 `generating` 中间态（幂等所需），已在 Task 2 Step 5 要求补回 spec。这是本计划**唯一**允许偏离 spec 的地方。
