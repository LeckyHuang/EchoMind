# EchoMind · 智能录音分析平台

> 录音上传 → ASR 转文字 → 多维度 LLM 并发分析 → 自动生成可分享报告页

EchoMind 是一套**开箱即用的私有化录音分析后端**，配合同名 Android App 使用。录制完成后，一键上传即可获得结构化分析报告（参观简报 / 商机简报 / 接待复盘等），并自动生成可手机直接浏览的分享页。

---

## 功能亮点

| 模块 | 说明 |
|------|------|
| **ASR 转写** | 支持阿里云通义、豆包、腾讯云多家 ASR，可热切换 |
| **LLM 并发分析** | 支持 MiniMax / Kimi / 通义千问 / 豆包 / 智谱，多任务类型并发执行 |
| **自定义任务类型** | 管理后台可自定义分析维度，绑定独立 Prompt，无需改代码 |
| **分享页自动生成** | 分析完成后自动输出移动端友好的 HTML 分享页 |
| **JWT 鉴权** | Bearer Token，72h 过期，角色区分 admin / user |
| **管理后台** | 内置纯前端后台（`/app/echodmind`），管理文件、报告、用户、Prompt |
| **Android 配套 App** | 见 [EchoMind-App](https://github.com/LeckyHuang/EchoMind)（录音 + 上传 + 报告查看） |

---

## 技术栈

- **后端**：Python 3.11+ · FastAPI · SQLAlchemy · SQLite
- **鉴权**：JWT HS256 · passlib[bcrypt]
- **异步**：asyncio 并发调用多个 LLM
- **前端**：原生 HTML/JS（无框架依赖，内嵌于后端静态目录）

---

## 快速开始

### 1. 克隆 & 创建虚拟环境

```bash
git clone https://github.com/LeckyHuang/EchoMind.git
cd EchoMind
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写以下字段：

```dotenv
# JWT 密钥（必填，启动前必须设置）
JWT_SECRET_KEY=<运行下方命令生成>

# ASR 提供商及对应 API Key
ASR_PROVIDER=qwen        # 或 doubao / tencent / baidu
QWEN_API_KEY=...

# LLM 提供商及对应 API Key
LLM_PROVIDER=qwen        # 或 minimax / kimi / doubao / zhipu
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

生成 JWT 密钥：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. 初始化管理员账号

```bash
python init_admin.py
# 按提示设置用户名和密码
```

### 4. 启动服务

```bash
# 开发模式（热重载）
python main.py

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8088 --workers 2
```

服务启动后：

| 地址 | 说明 |
|------|------|
| `http://localhost:8088/` | API 健康检查 |
| `http://localhost:8088/docs` | Swagger 交互文档 |
| `http://localhost:8088/app/echodmind` | 管理后台登录页 |

---

## 目录结构

```
EchoMind/
├── main.py               # FastAPI 应用入口、核心路由
├── auth.py               # JWT 鉴权模块
├── config.py             # 配置读取（.env → Settings）
├── models.py             # SQLAlchemy ORM 模型
├── scheduler.py          # 定时清理任务
├── init_admin.py         # 初始化管理员脚本
├── presets_library.py    # 预置任务类型库
│
├── routers/
│   ├── auth_router.py    # 登录 / 用户信息
│   ├── file_router.py    # 文件管理（列表 / 重新分析 / 删除）
│   ├── report_router.py  # 报告编辑 / 分享页生成
│   ├── prompt_router.py  # Prompt 模板 CRUD
│   ├── tasktype_router.py# 分析任务类型 CRUD
│   ├── user_router.py    # 用户管理（仅 admin）
│   └── settings_router.py# 系统设置
│
├── services/
│   ├── asr_service.py    # ASR 转写（多 provider 适配）
│   ├── llm_service.py    # LLM 分析（多 provider 适配）
│   └── media_service.py  # 音频元数据处理
│
├── utils/
│   └── file_utils.py     # 文件保存 / 清理
│
├── prompts/              # 内置 Prompt 模板（Markdown）
│   ├── customer_brief.md
│   ├── business_opportunity.md
│   ├── reception_review.md
│   └── ...
│
├── frontend/             # 管理后台静态文件
│   ├── login.html
│   ├── dashboard.html
│   ├── files.html
│   ├── reports.html
│   ├── prompts.html
│   ├── task-types.html
│   ├── users.html
│   └── styles.css
│
├── .env.example          # 环境变量模板
├── requirements.txt
└── docs/
    ├── SCHEMA.md         # 数据库表结构说明
    └── 启动说明.md
```

---

## 主要 API

> 所有 `/api/v1/admin/*` 及分析接口均需要 `Authorization: Bearer <token>` 请求头。

### 鉴权

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/login` | 登录，返回 JWT Token |
| GET  | `/api/v1/auth/users/me` | 获取当前用户信息 |

### APP 端接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/task-types` | 获取所有分析任务类型（公开） |
| POST | `/api/v1/analyze` | 上传录音 → ASR → LLM 并发分析 → 返回分享链接 |
| POST | `/api/v1/analyze/text` | 直接分析文字（已有转写结果） |

### 分享页

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/share/{share_id}` | 查看分享页（公开，无需登录） |
| POST | `/share/{share_id}/edit` | 编辑分享页内容（需登录） |

### 文件 / 报告管理（`/api/v1/admin/`）

详见 `/docs` Swagger 文档。

---

## 自定义分析类型

1. 登录管理后台 → **任务类型** → 新建
2. 填写名称、Display Name、绑定 Prompt Key
3. 在 **Prompt 模板** 页创建对应 Prompt（变量：`{text}`）
4. App 端下次上传时即可选择该类型

也可通过 `presets_library.py` 批量导入预置类型。

---

## 部署参考

### Nginx 反代

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 200M;

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 600s;
    }
}
```

### systemd 服务

```ini
[Unit]
Description=EchoMind Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/path/to/EchoMind
EnvironmentFile=/path/to/EchoMind/.env
ExecStart=/path/to/EchoMind/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8088 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 快速部署脚本

```bash
chmod +x deploy.sh && ./deploy.sh
```

---

## 安全说明

- **JWT_SECRET_KEY 必须通过环境变量设置**，服务启动时若未设置会直接抛出异常，不会使用默认值
- `.env` 已加入 `.gitignore`，不会进入版本库
- 本地网络部署时 `usesCleartextTraffic=true`，请在生产环境配置 HTTPS/TLS
- 分享页 `/share/{id}` 公开可访问（设计上无需登录）；编辑分享页需登录

---

## 配套 Android App

Android 录音客户端见 [EchoMind-App](https://github.com/LeckyHuang/EchoMind)，功能包括：

- 前台录音服务，支持暂停/继续
- 上传前选择分析类型 + 补充背景说明
- 分析进度实时计时展示
- 内嵌 WebView 直接查看分享报告

---

## License

MIT
