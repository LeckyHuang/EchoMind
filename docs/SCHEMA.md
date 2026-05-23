# 数据库设计文档

> 版本：v1.0 | 日期：2026-03-30

---

## 数据库信息

- **数据库类型**：SQLite（开发/轻量使用）
- **数据库文件**：`data/voicerecorder.db`
- **ORM**：SQLAlchemy 2.0（后续可迁移到 PostgreSQL/MySQL，改一处 URL 即可）
- **迁移说明**：生产环境只需把 `DATABASE_URL` 改成 PostgreSQL/MySQL 连接字符串

---

## 数据表设计

### 1. users（用户表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| user_id | VARCHAR(36) | UNIQUE, INDEX | 公开用 UUID |
| username | VARCHAR(50) | UNIQUE, NOT NULL | 用户名 |
| email | VARCHAR(100) | UNIQUE | 邮箱 |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 加密密码 |
| role | VARCHAR(20) | NOT NULL, DEFAULT 'user' | admin / user |
| is_active | BOOLEAN | DEFAULT TRUE | 账号是否激活 |
| created_at | DATETIME | AUTO | 创建时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

**索引**：`username`(唯一), `email`(唯一)

**说明**：
- 密码用 bcrypt 哈希，不存储明文
- role = 'admin' 可管理所有数据；role = 'user' 只能看自己的数据

---

### 2. audio_files（录音文件表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| file_id | VARCHAR(36) | UNIQUE, INDEX | 公开用 UUID |
| user_id | INTEGER | FK → users.id, NOT NULL | 上传者 |
| original_filename | VARCHAR(255) | | 原始文件名 |
| stored_filename | VARCHAR(255) | NOT NULL | 存储文件名(UUID) |
| file_path | VARCHAR(500) | NOT NULL | 完整存储路径 |
| file_size | INTEGER | | 文件大小（字节） |
| duration | FLOAT | | 录音时长（秒，ffprobe 准确值） |
| file_format | VARCHAR(20) | | mp3 / m4a / wav 等 |
| upload_status | VARCHAR(20) | DEFAULT 'pending' | pending / processing / completed / failed |
| asr_text | TEXT | | ASR 转写文本 |
| created_at | DATETIME | AUTO | 上传时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

**索引**：`file_id`(唯一), `user_id`

**关系**：
- User (1) → AudioFile (N)
- AudioFile (1) → AnalysisReport (1)

---

### 3. analysis_reports（分析报告表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| report_id | VARCHAR(36) | UNIQUE, INDEX | 公开用 UUID |
| file_id | INTEGER | FK → audio_files.id, NOT NULL | 对应录音文件 |
| user_id | INTEGER | FK → users.id, NOT NULL | 所属用户 |
| report_data | JSON | | 完整分析结果（LLM 输出） |
| status | VARCHAR(20) | DEFAULT 'pending' | pending / processing / completed / failed |
| error_message | TEXT | | 失败时的错误信息 |
| created_at | DATETIME | AUTO | 分析时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

**索引**：`report_id`(唯一), `file_id`, `user_id`

**report_data JSON 结构示例**：
```json
{
  "summary": {
    "background": "Q2产品规划会议",
    "core_topics": "资源调配、搬迁计划",
    "participants": ["张总", "李经理", "王总"],
    "tone": "协商型",
    "estimated_duration": "约20分钟"
  },
  "topics": [...],
  "consensus": [...],
  "needs": {...},
  "action_items": [...],
  "risks_and_concerns": [...]
}
```

---

### 4. prompt_templates（Prompt 模板表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| template_id | VARCHAR(36) | UNIQUE, INDEX | 公开用 UUID |
| name | VARCHAR(100) | UNIQUE, NOT NULL | 模板名称 |
| description | TEXT | | 模板描述 |
| content | TEXT | NOT NULL | Prompt 模板内容 |
| is_active | BOOLEAN | DEFAULT FALSE | 是否为当前激活模板 |
| created_at | DATETIME | AUTO | 创建时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

**索引**：`template_id`(唯一), `name`(唯一)

**说明**：
- `is_active = True` 的模板会在分析时被使用
- 支持在线编辑修改，修改后下次分析生效

---

### 5. system_settings（系统设置表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| key | VARCHAR(100) | UNIQUE, INDEX | 配置项 key |
| value | TEXT | | 配置值 |
| description | TEXT | | 配置说明 |
| updated_at | DATETIME | AUTO | 更新时间 |

**已有配置项**：

| key | 说明 | 默认值 |
|-----|------|--------|
| file_expire_hours | 文件过期时间（小时） | 168（7天） |
| cleanup_enabled | 是否开启自动清理 | true |
| cleanup_cron | 清理执行周期（cron 表达式） | 0 3 * * *（每天凌晨3点） |
| asr_provider | ASR 服务商 | doubao |
| llm_provider | LLM 服务商 | minimax |

---

## ER 关系图

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────────┐
│    users     │       │   audio_files    │       │  analysis_reports │
├──────────────┤       ├──────────────────┤       ├──────────────────┤
│ id (PK)      │──┐    │ id (PK)          │──┐    │ id (PK)          │
│ user_id      │  │    │ file_id (UNIQUE) │  │    │ report_id        │
│ username     │  └──→ │ user_id (FK) ────┼──┘    │ file_id (FK) ────┼──┐
│ password_hash│       │ duration          │       │ user_id (FK) ────┘  │
│ role         │       │ upload_status     │       │ report_data (JSON)  │
│ is_active    │       │ asr_text          │       │ status            │
└──────────────┘       └──────────────────┘       └──────────────────┘
                              │
                              │
                       ┌──────┴──────┐
                       │ prompt_templates│
                       ├──────────────┤
                       │ id (PK)      │
                       │ name (UNIQUE)│
                       │ content      │
                       │ is_active    │
                       └──────────────┘
```

---

## 初始化操作

```bash
# 初始化数据库（创建表 + 默认数据）
python models.py
```

---

## 生产环境迁移

```python
# 改成 PostgreSQL
DATABASE_URL = "postgresql+aiomysql://user:pass@localhost/voicerecorder"

# 或 MySQL
DATABASE_URL = "mysql+aiomysql://user:pass@localhost/voicerecorder"
```
