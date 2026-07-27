## 项目上下文（2026-07-28 从全局 memory 迁入）

EchoMind 是从 voicerecorder fork 出来的二开项目，支持任意类型的录音分析。

**Why:** 原 voicerecorder 硬编码三种展厅报告类型，无法扩展到其他场景。
**How to apply:** 新功能开发在 echodmind 项目上进行，voicerecorder 保持不变供客户使用。

## 关键信息
- 路径: `/Users/leckyhuang/Desktop/project/echodmind`
- 端口: 8088（原项目 8000）
- DB: `data/echodmind.db`
- 管理后台: `/app/echodmind/login.html`
- venv: `venv/` 目录

## P0+P1+P2 改造已完成（2026-05-23）

**P0 已完成：**
- Fork 自 voicerecorder，独立 DB/端口/目录
- 品牌名改为 EchoMind

**P1 已完成（动态任务类型）：**
- 新增 `analysis_task_types` 表（`AnalysisTaskType` model）
- 新增 `routers/tasktype_router.py`（管理员 CRUD API）
- `main.py` + `file_router.py` 的分析流程改为动态读取 DB 类型
- 上传时前端支持勾选分析类型（A+C 混合：默认预选 + 可手动调整）
- 新增前端页面 `task-types.html` + `task-types.js`（管理员管理类型）
- 启动时 seed 三个内置类型（customer_brief/business_opportunity/reception_review）

**P2 已完成（通用渲染器）：**
- `_body_generic()` 函数：适配任意新类型，LLM 输出 sections 格式
- sections 支持: text / list / kv / tags / actions 五种段落类型
- 三个内置类型保留原有专用渲染函数（向后兼容）

## 类型库功能（2026-05-23 完成）

**预设库（presets_library.py）：** 10个预置类型（会议摘要/意图分析/心理画像/商业洞察/谈判复盘/客户声音/行动清单/风险预警/销售复盘/关系评估），按需安装，不提前写DB。

**default_rank（替换 is_default）：** 0=不默认，1/2/3=优先级排序，最多3个，rank唯一约束，同rank自动顶出前一个。

**新 API：** `GET /admin/type-presets`（浏览库）、`POST /admin/type-presets/{name}/install`（安装）、`POST /admin/type-presets/{name}/reset-prompt`（重置prompt）。

**前端（task-types.js）：** 两Tab—"我的类型"（3槽位可视化 + 类型卡片 + prompt微调）、"类型库"（按分类浏览+一键安装）。

## APP 已完成（echodmind-app，2026-05-23）

Fork 自 yulu-app，路径 `/Users/leckyhuang/Desktop/project/echodmind-app`

**改造内容：**
- P0: 包名 `com.voice.recorder` → `com.echodmind`；App名 "语录" → "EchoMind"；服务器地址存 base URL（不含路径）
- P1: 上传前自动拉取 `GET /api/v1/task-types`，弹出多选 Dialog（default_rank>0 预选，✦ 标注），upload 时带 `task_types` 参数
- P2: 上传成功后解析 `file_id` + `reportCount`，点报告按钮弹出 Dialog 并可一键打开管理后台浏览器

**关键新文件：**
- `api/TaskTypesApi.java` — 拉取类型列表（OkHttp，10s 超时）
- `api/UploadApi.java` — 上传接口，支持 `List<String> selectedTypeNames`
- `utils/PreferencesUtils.java` — 存 base URL，提供 `getAnalyzeUrl()` / `getTaskTypesUrl()` / `getAdminUrl()`

**用户设置：** 长按顶部标题区，填写 `http://IP:8088`（不带路径）

## 待完成（后续规划）
- P3: Project 实体（多次录音/分析/跟进闭环），schema 从一开始设计
- 新增分析类型时需在 Prompt管理 页面配置对应 prompt，并在 task-types 页面绑定 prompt_key

## 新类型 Prompt 格式规范
新增分析类型的 LLM Prompt 应要求输出 sections 格式：
```json
{"title": "...", "sections": [
  {"type": "text",    "title": "...", "content": "..."},
  {"type": "list",    "title": "...", "items": ["..."]},
  {"type": "kv",      "title": "...", "items": [{"label":"...","value":"..."}]},
  {"type": "tags",    "title": "...", "items": ["..."]},
  {"type": "actions", "title": "...", "items": [{"action":"...","priority":"高","notes":"..."}]}
]}
```

> 注：本文件原全局 memory 路径写作 `echodmind`（打字误差），实际仓库名为 `echomind`（本文件所在目录），内容按原文逐字保留。
