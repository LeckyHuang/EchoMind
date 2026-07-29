# 异步分析 + 录音分段串联 设计方案

- 日期：2026-07-28
- 状态：已定稿，待实施
- 涉及仓库：`echomind`（后端）、`echomind-app`（Android）

## 1. 背景与问题

当前 `POST /api/v1/analyze` 是一次同步阻塞请求，在单次请求内跑完「上传 → ASR → LLM 并发分析 → 生成分享页」。App 侧 OkHttp 把连接/读/写超时设成 1800 秒硬等。

审计发现三个互相纠缠的问题：

1. **同步阻塞不可持续**。录音越长，单次请求越久。App 被系统回收、切后台、断网，这次录音就永久停在「未上传」，没有任何续查机制。
2. **分段上传只做了一半**。App 按 120 分钟切分录音（`VoiceRecordService.java:21` `SEG_MS`），但上传协议、`/api/v1/analyze` 接口、`AudioFile` 表全都不认识「分段」这个概念。每段被当成独立录音，独立生成 `file_id`、独立出报告，彼此无任何关联。一场 3 小时的接待会产出 2 份割裂的报告，各自只看到一半对话。
3. **唯一的合并能力没接进来**。`routers/file_router.py:449` 的 `POST /api/v1/admin/analyze/merge` 明确写着「用于处理因分段录制产生的多个文件」，按顺序拼接各段 `asr_text` 后统一出报告——但 App 源码全文搜 `merge` 零匹配，只能靠人工登录网页后台手动勾选 file_ids 触发。这直接破坏了「App 单独闭环」。

问题 2 和 3 的根因，与问题 1 是同一件事的两面：120 分钟的分段阈值配上同步阻塞架构本身就是矛盾的——2 小时录音单次 ASR + LLM 未必能压进任何合理的超时窗口。因此本方案把两者合并解决。

## 2. 目标与非目标

### 目标

- 用户只装 App、不碰网页后台，能完成「录音 → 自动分段上传 → 拿到一份完整报告」的闭环。
- 长录音出报告时间可控：ASR 从「录完才开始」变为「边录边转」，3 小时录音在录制结束后 3-5 分钟内出报告。
- 服务重启不丢正在处理的任务。

### 非目标（本轮明确不做）

- **断点续传 / 断网重试队列**。单独一块工作量，下一轮再做。本轮上传失败仍需用户手动重试该段。
- **推送通知**。App 靠前台轮询，不引入 FCM/极光等推送通道。
- **改造现有 `/api/v1/analyze` 同步接口**。线上老版本 App 仍在调用，原样保留不动。

## 3. 关键决策与取舍

| 决策 | 选择 | 理由 |
|---|---|---|
| 异步执行机制 | asyncio task + DB 状态表 + 启动扫描续跑 | Celery/RQ + Redis 对单机部署是过度工程；FastAPI BackgroundTasks 重启即丢任务，在长录音场景是致命的 |
| uvicorn worker 数 | **降为 1** | 分析链路全是 `await` 的 IO 等待，单 worker 吃得下并发。多 worker 会让「启动扫描续跑」重复执行、同一段音频转写两次扣两次费，且 SQLite 并发写会 `database is locked`。用复杂度换一个用不上的吞吐不划算 |
| 分段阈值 | **15 分钟** | 3 小时录音 12 段，并行度足够；比 10 分钟段数少一半，状态管理更简单 |
| 报告粒度 | **只出一份合并总报告** | 段级报告对「接待复盘」这类分析类型意义不大，且 LLM 调用成本翻倍 |
| 单段录音的建模 | 也建成「只有一段的 session」 | 不做两条代码路径。归一到唯一内部 schema，避免后续所有查询/渲染都要判断两种形态 |

## 4. 架构设计

### 4.1 数据模型

新增 `recording_sessions` 表：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `session_id` | String(36) unique index | **客户端生成**的 UUID，开录时确定 |
| `user_id` | FK users.id | |
| `title` | String(255) | 默认取首段文件名 |
| `status` | String(20) index | `recording` / `analyzing` / `generating` / `completed` / `failed`（`generating` 见 4.3） |
| `total_segments` | Integer nullable | finalize 时由客户端声明；未 finalize 时为 NULL |
| `task_types` | JSON | finalize 时传入的分析类型名列表 |
| `supplementary_text` | Text nullable | 用户补充说明 |
| `merged_file_id` | FK audio_files.id nullable | 指向合并产生的虚拟 AudioFile |
| `error_message` | Text nullable | |
| `created_at` / `updated_at` | DateTime | |

`AudioFile` 表新增两列（均 nullable，兼容存量数据）：

- `session_id` String(36) index —— 所属会话
- `segment_index` Integer —— 段序号，从 0 起

`AnalysisReport` **不改**。合并报告沿用 `analyze/merge` 已有的做法：建一个 `file_format="merged"`、`file_path=""` 的虚拟 `AudioFile` 承载拼接后的 `asr_text`，报告外键挂到它上面（`file_router.py:487-502` 已是这个模式）。

段级 ASR 状态复用 `AudioFile.upload_status`，不新建字段：`pending` → `processing` → `completed` / `failed`。

⚠️ **不变量：merged 虚拟 AudioFile 也带 `session_id`，但 `segment_index` 为 NULL。** 因此**所有「按 session 捞段」的查询都必须加 `segment_index IS NOT NULL` 过滤**，否则合并记录会被当成一个「段」参与计数、拼接与到齐判断。这一条被两处独立踩中过（到齐检查、会话状态查询接口），是本设计最容易漏的坑。

### 4.2 接口设计

全部挂在 `/api/v1` 下，Bearer Token 鉴权，归属当前用户。

**`POST /api/v1/segments`** —— 上传一段
- 入参：`file`（multipart）、`session_id`、`segment_index`
- 行为：落盘 → 建 `AudioFile`（`upload_status=pending`）→ 若 session 不存在则隐式创建（`status=recording`）→ 提交 ASR 异步任务 → 立即返回
- 返回：`202 { session_id, segment_index, file_id, status: "pending" }`
- 幂等：同 `(session_id, segment_index)` 重复上传，覆盖原段并重跑 ASR

**`POST /api/v1/sessions/{session_id}/finalize`** —— 声明录完
- 入参：`total_segments`、`task_types`（可选，为空用默认类型）、`supplementary_text`（可选）
- 行为：写入 `total_segments` / `task_types`，session 转 `analyzing`，触发一次「到齐检查」
- 返回：`200 { session_id, status }`
- 幂等：重复调用只更新字段，不重复触发分析

**`GET /api/v1/sessions/{session_id}`** —— 状态轮询
```json
{
  "session_id": "...",
  "status": "analyzing",
  "total_segments": 12,
  "segments": [{"segment_index": 0, "status": "completed", "duration": 900.0}],
  "progress": {"asr_done": 11, "asr_total": 12},
  "report_ids": ["..."],
  "error_message": null
}
```

**`GET /api/v1/reports/{report_id}`** —— 取结构化报告正文
- 现有的 `GET /api/v1/admin/reports/{id}` 路径带 `admin` 但鉴权只按当前用户，语义误导。新增此非 admin 别名路由，复用同一 handler，供 App 原生渲染取 `report_data`。旧路由保留。

**`GET /api/v1/sessions`** —— App 历史列表用，分页返回当前用户的会话摘要。

### 4.3 任务执行与状态机

单一后台执行器，进程内 asyncio：

- **提交**：`POST /api/v1/segments` 落库后创建 asyncio task 跑该段 ASR。全局并发上限 **3**（`asyncio.Semaphore`），防打爆豆包 ASR 配额与限流。
- **段完成回调**：写回 `asr_text` + `upload_status=completed`，然后调用「到齐检查」。
- **到齐检查**（唯一的分析触发点，幂等）：当 `session.total_segments` 非空、且该 session 下所有段都已 `completed` 或 `failed` 时，按 `segment_index` 排序拼接文本 → 建虚拟 merged AudioFile → 复用 `analyze/merge` 的 LLM 并发分析逻辑 → 写报告 + 生成分享页 → session 转 `completed`。
- **重启续跑**：应用启动时扫描 `upload_status IN (pending, processing)` 的段，重新提交 ASR；并对所有 `status IN (analyzing, generating)` 的 session 跑一次到齐检查（`generating` 的先退回 `analyzing`，见下）。这是 workers 必须为 1 的直接原因。

状态流转：

```
segment:  pending -> processing -> completed | failed
session:  recording -> analyzing -> generating -> completed | failed
```

| 会话状态 | 含义 | 入口 | 出口 |
|---|---|---|---|
| `recording` | 已开录，尚未 finalize，总段数未知 | 首段上传时隐式创建 | finalize → `analyzing`；超 24 小时未 finalize → `failed`（孤儿清理） |
| `analyzing` | 总段数已声明，等各段 ASR 到齐 | finalize | 到齐检查抢锁成功 → `generating`；全段失败 → `failed` |
| `generating` | 已进入 LLM 分析（**幂等锁**） | 到齐检查的条件原子推进 | 分析完成 → `completed`；分析异常 → `failed`；进程重启 → 由续跑扫描退回 `analyzing` |
| `completed` | 报告已生成 | 分析完成 | 终态 |
| `failed` | 全段转写失败 / 分析异常 / 孤儿清理 | 见上 | 终态 |

`recording → analyzing` 只由 finalize 触发；`analyzing → generating → completed` 只由到齐检查触发。

**关于 `generating`**：`finalize` 与「最后一段 ASR 完成」是两个互相独立、可能同时发生的事件，都会调用到齐检查，而分析必须且只能跑一轮（多跑一轮就多扣一次 LLM 费）。幂等锁由两道防线叠加，作用不同：

1. **单进程互斥的真正来源是「前置状态读检查 + 抢锁前零 await」**：`check_and_finalize` 从读 `session.status` 到把状态改成 `generating` 并 `commit`，中间不含任何 `await`。因为没有让出点，这一段在单事件循环内是原子的——后到的调用一定会看到已经被改过的状态。这条不变量若被破坏（例如在抢锁前插入一次 `await`），后果不止是幂等失效多扣一次 LLM 费：多个协程各自持有已开事务的 SQLite 连接同时抢锁，会把事件循环整个堵死、**进程挂死**。`tests/test_segment_timing.py` 用 AST 断言守住这条不变量，防止后人在抢锁前插入 `await`。
2. **条件原子推进是跨进程/跨线程下的保险**（单进程下是冗余的第二道防线）：

   ```sql
   UPDATE recording_sessions SET status='generating'
    WHERE session_id=? AND status='analyzing'
   ```

   只有 `rowcount == 1` 的那一次调用继续往下调 LLM，其余一律返回 False。本方案已强制 workers=1，但数据库层并未禁止多进程接入；一旦有人在这个前提之外多开 worker，第 1 条防线不再成立，这句条件 UPDATE 才是唯一还生效的兜底。

**重启续跑必须把 `generating` 退回 `analyzing`**：`generating` 表示「进了 LLM 但没跑完就重启」，若不退回，到齐检查会因状态不是 `analyzing` 直接返回，该会话永远卡死。

### 4.4 错误处理与降级

- **单段 ASR 失败**：重试 2 次（指数退避 5s / 15s）。仍失败则该段标 `failed`，**不阻塞到齐检查**。
- **缺段降级出报告**：拼接文本时对失败段插入占位 `[片段N：转写失败，内容缺失]`，报告照常生成。这与既有的「单元失败降级留痕、不拖垮整体」原则一致（`main.py:324` 的 `return_exceptions=True` 已是此模式）。
- **全部段失败**：session 转 `failed`，`error_message` 说明原因，不调 LLM。
- **单个报告类型 LLM 失败**：沿用现状，`asyncio.gather(return_exceptions=True)` 隔离，其他类型照常产出。
- **孤儿 session**：finalize 从未被调用（App 崩溃/卸载）的 session，由 `scheduler.py` 现有清理 cron 加一条：`recording` 状态超过 24 小时的标记 `failed` 并清理音频文件。

### 4.5 App 端改造

- **会话 ID**：`VoiceRecordService` 开录时生成 `session_id`，`SEG_MS` 由 120 分钟改为 15 分钟，`onSegmentComplete` 回调带上 `session_id` + `segmentIndex`。
- **自动上传队列**：新增 `SegmentUploadQueue`，段落盘即入队，串行上传（避免手机上行带宽被打满）。用户不再需要手动逐个点上传。
- **停止录音**：调 `finalize` 提交总段数 + 用户选的分析类型。类型选择 UI 从「上传前」移到「停止录音时」，因为现在上传是自动的。
- **轮询**：录音详情页每 10 秒轮询 `GET /api/v1/sessions/{id}`，展示「已转写 11/12 段」进度；`completed` 后停止轮询。仅在页面可见时轮询，退到后台即停。
- **原生报告渲染**：新增 `ReportActivity`，用 RecyclerView 多 ViewType 渲染 `report_data` 的 sections 契约（`text` / `list` / `kv` / `tags` / `actions` 五种段落类型。契约的权威实现在后端 `routers/report_router.py` 的 `_body_generic()` 与前端 `frontend/report.js`，App 渲染器必须与之对齐）。`ReportWebViewActivity` 保留，作为老数据和分享页的入口。
- **历史列表**：`MainActivity` 改为**双 Tab**。「录音会话」Tab 按 session 聚合展示，一次录音一行（含段数与状态）；「本地文件」Tab 保留原有的本地录音文件管理（播放 / 重命名 / 保存到手机 / 删除 / 手动上传入口）。轮询按 Tab 门控，仅「录音会话」Tab 可见时运行。

  > **为什么是双 Tab**：本条原文只写了「改为按 session 聚合，一次录音一行」，实施时被照字面执行，连带把本地文件管理整块砍掉了（播放/重命名/保存/删除全失，`UploadFlowActivity` 沦为死代码），事后回滚补救。会话聚合解决的是「报告怎么归组」，与「本地音频文件怎么管理」是两件正交的事，不该互相替代。

## 5. 测试策略

后端 pytest，重点覆盖状态机的时序竞争：

- 段乱序到达（`segment_index` 2 先于 0 到达）
- finalize 早于所有段 ASR 完成 / 晚于所有段 ASR 完成——两种时序都必须触发分析且只触发一次
- 重复 finalize 幂等
- 同 `(session_id, segment_index)` 重复上传覆盖
- 单段 ASR 失败后的缺段降级：报告仍生成且含占位标记
- 全段失败：session 转 `failed` 且不调 LLM
- 重启续跑：模拟 `processing` 中断的段被重新提交
- 单段 session（不分段的普通录音）走完整流程——验证归一模型没有把简单场景搞坏

ASR 与 LLM 在测试中打桩，不打真实厂商 API。

端到端真实验证（不可省略，人工执行）：用 App 录一段跨 2 个分段的真实录音，确认产出**一份**完整报告且内容覆盖全程。

## 6. 部署影响

- `uvicorn --workers 2` → `--workers 1`（systemd unit 与 `DEPLOY.md` 同步修改）。**这是本方案的正确性前提，不是优化项。**
- 数据库需要迁移：`recording_sessions` 建表 + `audio_files` 加两列。项目当前无 Alembic，沿用既有做法在启动时建表，加列用一次性迁移脚本。
- 新旧 App 共存期：老版本继续走 `/api/v1/analyze`，不受影响。

## 7. 遗留与后续

- 断点续传 / 上传失败自动重试（本轮非目标，建议紧接着做——15 分钟一段约 5MB，失败重传代价已比之前的 43MB 小很多，但仍不该让用户手动点）
- 推送通知替代轮询
- 段级实时预览（边录边看已转写文本）
