# EchoMind 服务器部署指引

> 适用场景：服务器已有 voicerecorder 运行环境（Python 3.10+、ffmpeg、systemd），新建独立 EchoMind 服务，不影响 voicerecorder。
> 上传方式：FTP
> 服务器目录：`/app/echomind`
> 服务端口：`8088`

---

## 第一步：FTP 上传代码

用 FTP 客户端（FileZilla 等）将本地 `/Users/leckyhuang/Desktop/project/echodmind/` 的文件上传到服务器 `/app/echomind/`。

**以下文件/目录不需要上传：**

| 排除项 | 原因 |
|--------|------|
| `venv/` | 服务器自建 |
| `data/` | 服务器自建（含数据库） |
| `uploads/` | 服务器自建 |
| `shares/` | 服务器自建（随报告生成） |
| `.env` | 服务器单独配置，不上传本地密钥 |

---

## 第二步：服务器建环境

SSH 登录服务器后执行：

```bash
# 创建必要目录
mkdir -p /app/echomind/uploads /app/echomind/data /app/echomind/shares

# 建独立虚拟环境（不复用 voicerecorder 的 venv）
cd /app/echomind
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# ⚠️ 关键：passlib 1.7.4 与 bcrypt 5.x 不兼容，必须单独降级
pip install 'bcrypt==4.0.1'
```

> **为什么不复用 voicerecorder 的 venv？**
> bcrypt 版本必须锁定在 4.0.1，voicerecorder 的 venv 版本不确定，直接复用会导致 admin 登录报错。

---

## 第三步：创建 .env

```bash
nano /app/echomind/.env
```

粘贴以下内容并按实际情况填写：

```dotenv
# ==================== 服务配置 ====================
DEBUG=false
HOST=0.0.0.0
PORT=8088
UPLOAD_DIR=./uploads
MAX_FILE_SIZE=100
FILE_EXPIRE_HOURS=168
CORS_ORIGINS=*

# ==================== ASR 配置 ====================
ASR_PROVIDER=doubao
DOUBAO_APP_ID=<你的火山引擎 APP ID>
DOUBAO_ACCESS_KEY=<你的火山引擎 Access Key>
DOUBAO_SECRET_KEY=<你的火山引擎 Secret Key>

# ==================== LLM 配置 ====================
LLM_PROVIDER=qwen
QWEN_API_KEY=<你的阿里云百炼 API Key，形如 sk-xxxx>
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# ==================== MiniMax（备用）====================
MINIMAX_API_KEY=（完整 token）
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_MODEL=MiniMax-M2.5

# ==================== JWT 密钥 ====================
# 用 openssl rand -hex 32 现场生成，切勿照抄任何文档里的示例值
SECRET_KEY=<openssl rand -hex 32 的输出>
JWT_SECRET_KEY=<同上，与 SECRET_KEY 填相同值>
```

> ⚠️ 以上全部为占位符，需替换成你自己的真实值。真实密钥只写进服务器上的 `.env`，**不要回填到本文档或任何提交进 git 的文件里**。

---

## 第四步：初始化数据库

```bash
cd /app/echomind
source venv/bin/activate
python3 init_admin.py   # 创建 admin 账号，默认密码 123456
```

首次启动会自动建表并 seed 两个默认分析类型：**会议摘要** + **意图分析**。

---

## 第五步：配置 systemd 守护进程

```bash
sudo nano /etc/systemd/system/echodmind.service
```

```ini
[Unit]
Description=EchoMind - 智能录音分析平台
After=network.target

[Service]
User=root
WorkingDirectory=/app/echomind
ExecStart=/app/echomind/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment="PATH=/app/echomind/venv/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable echodmind
sudo systemctl start echodmind

# 确认运行状态
sudo systemctl status echodmind

# 实时查看日志
sudo journalctl -u echodmind -f
```

---

## 第六步：放行端口

```bash
# ufw 防火墙
sudo ufw allow 8088/tcp
```

> 如果服务器是云主机（阿里云/腾讯云），还需要在控制台「安全组」里放行 **8088 TCP 入方向**。

---

## 第七步：验证部署

```bash
# 管理后台（浏览器访问）
http://183.56.228.31:8088/app/echodmind

# API 健康检查
curl http://183.56.228.31:8088/

# 登录测试
curl -X POST http://183.56.228.31:8088/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"123456"}'
```

---

## APP 端连接服务器

长按 APP 主界面标题区域 → 弹出设置框 → 填入：

```
http://183.56.228.31:8088
```

---

## 常用运维命令

| 操作 | 命令 |
|------|------|
| 启动服务 | `sudo systemctl start echodmind` |
| 重启服务 | `sudo systemctl restart echodmind` |
| 停止服务 | `sudo systemctl stop echodmind` |
| 查看日志 | `sudo journalctl -u echodmind -f` |
| 更新代码 | FTP 重新上传 → `sudo systemctl restart echodmind` |
| 查看数据库 | `sqlite3 /app/echomind/data/echodmind.db ".tables"` |

---

## ⚠️ 注意事项

1. **bcrypt 每次重建 venv 后必须重新执行** `pip install 'bcrypt==4.0.1'`，否则 admin 登录报 `ValueError`
2. **不要复用 voicerecorder 的 venv**，两个项目各自独立，避免依赖冲突
3. **SOCKS 代理**：服务器如有系统代理环境变量，豆包 ASR 调用代码已加 `trust_env=False` 规避，无需额外处理
4. **更新代码后只需 FTP 覆盖上传 + `systemctl restart`，无需重建 venv**（除非 requirements.txt 有变化）

---

## 常见问题

| 现象 | 可能原因 | 解法 |
|------|----------|------|
| `systemctl status` 显示 failed | `.env` 缺字段 / 包未装 | `journalctl -u echodmind -n 50` 查详细报错 |
| admin 登录报错 `ValueError` | bcrypt 版本不对 | `pip install 'bcrypt==4.0.1'` 后重启 |
| ASR 报错 `Server disconnected` | 系统代理干扰 | 检查代码 `trust_env=False` 是否生效 |
| 上传成功但 ASR 返回空 | 豆包 Token 过期 | 更新 `.env` 中的 `DOUBAO_ACCESS_KEY` 后重启 |
| APP 上传失败 | 防火墙/安全组未放行 | 先浏览器确认 `http://ip:8088/` 能访问 |
| 管理后台加载不出分析类型 | 未完成 init_admin.py | 重新执行 `python3 init_admin.py` |
