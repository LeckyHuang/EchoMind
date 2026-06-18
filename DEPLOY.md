# 语录后端 - 服务器部署说明

> 适用系统：Ubuntu 20.04 / 22.04（其他 Debian 系均可）  
> 预计操作时长：20–30 分钟

---

## 一、服务器环境准备

### 1.1 安装 Python 3.10+

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
python3 --version   # 确认 >= 3.10
```

### 1.2 安装 ffmpeg（音频时长解析必需）

```bash
sudo apt install -y ffmpeg
ffmpeg -version     # 确认安装成功
```

### 1.3 安装 git

```bash
sudo apt install -y git
```

---

## 二、上传代码到服务器

### 方式 A：rsync（推荐，本机直接同步）

在**本机**终端执行：

```bash
# 将 voicerecorder 目录同步到服务器
# 替换 user 和 your-server-ip
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
  --exclude='uploads/' --exclude='data/' \
  /Users/qc/.openclaw/workspace/工作交付物/voicerecorder/ \
  user@your-server-ip:/opt/voicerecorder/
```

> `--exclude='.env'` 和 `--exclude='data/'` 是为了不覆盖服务器上的密钥配置和数据库。

### 方式 B：git（如已推送到私有仓库）

```bash
# 在服务器上执行
mkdir -p /opt/voicerecorder
cd /opt/voicerecorder
git clone https://your-repo-url.git .
```

---

## 三、服务器端配置

### 3.1 创建 Python 虚拟环境并安装依赖

```bash
cd /opt/voicerecorder
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 创建并配置 .env

```bash
cp .env.example .env   # 如果没有 example，直接新建
nano .env
```

将下方内容粘贴进去，**按实际情况填写**：

```dotenv
# ==================== 服务配置 ====================
DEBUG=false
HOST=0.0.0.0
PORT=8088
UPLOAD_DIR=./uploads
MAX_FILE_SIZE=100
FILE_EXPIRE_HOURS=168
CORS_ORIGINS=*

# 供百炼 Fun-ASR 临时下载音频的公网基地址（必须能被百炼服务端访问）
# 录音文件仍保存在本服务器，仅通过短期签名 URL 暴露给百炼拉取
ASR_TEMP_BASE_URL=https://your-domain.com

# ==================== ASR 配置 ====================
# 默认使用阿里云百炼 Fun-ASR（支持长录音）；如需切回豆包，改为 doubao
ASR_PROVIDER=qwen

# 阿里云百炼 Fun-ASR（ASR_PROVIDER=qwen 时生效）
QWEN_API_KEY=your_dashscope_api_key

# 豆包 ASR（ASR_PROVIDER=doubao 时生效）
DOUBAO_APP_ID=your_doubao_app_id
DOUBAO_ACCESS_KEY=your_doubao_access_key
DOUBAO_SECRET_KEY=your_doubao_secret_key

# ==================== LLM 配置 ====================
LLM_PROVIDER=qwen

QWEN_API_KEY=your_qwen_api_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# ==================== JWT 密钥（建议改成随机字符串）====================
SECRET_KEY=请替换为随机长字符串，例如：openssl rand -hex 32 的输出
JWT_SECRET_KEY=${SECRET_KEY}
```

> **生成随机 SECRET_KEY**：
> ```bash
> openssl rand -hex 32
> ```
> 把输出填入 `SECRET_KEY=` 后面。`ASR_TEMP_BASE_URL` 必须改为服务器公网可访问地址（如 `https://echomind.yourdomain.com` 或 `http://your-server-ip:8088`），否则百炼无法拉取音频。

### 3.3 创建必要目录并初始化数据库

```bash
cd /opt/voicerecorder
mkdir -p uploads data

source venv/bin/activate
python3 init_admin.py   # 创建 admin 账号（默认密码 123456，建议登录后台后修改）
```

---

## 四、配置 systemd 守护进程

### 4.1 创建 service 文件

```bash
sudo nano /etc/systemd/system/echomind.service
```

粘贴以下内容（注意替换 `user` 为你的服务器用户名）：

```ini
[Unit]
Description=EchoMind Backend (FastAPI + uvicorn)
After=network.target

[Service]
User=root
WorkingDirectory=/opt/echomind
ExecStart=/opt/echomind/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8088 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment="PATH=/opt/echomind/venv/bin"

[Install]
WantedBy=multi-user.target
```

> 如果服务器用的是非 root 用户（推荐），将 `User=root` 改为实际用户名，
> 并确保该用户对 `/opt/echomind` 有读写权限。

### 4.2 启动并设置开机自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable echomind
sudo systemctl start echomind

# 确认运行状态
sudo systemctl status echomind
```

看到 `active (running)` 即表示成功。

### 4.3 查看实时日志

```bash
sudo journalctl -u echomind -f
```

---

## 五、防火墙放行端口

```bash
# Ubuntu ufw
sudo ufw allow 8000/tcp
sudo ufw status

# 或者 iptables
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
```

> 如果服务器有云厂商的安全组（阿里云/腾讯云/AWS），还需要在控制台「安全组规则」里放行 8000 端口。

---

## 六、验证部署

在**本机**浏览器访问：

```
http://your-server-ip:8000/
```

应返回：
```json
{"status": "ok", "message": "语录后端服务运行中 v2.0"}
```

测试登录接口：

```bash
curl -X POST http://your-server-ip:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"123456"}'
```

返回包含 `access_token` 字段即为正常。

---

## 七、配置管理后台连接服务器

管理后台的 API 地址写在 `frontend/api.js` 第 1 行：

```javascript
const API_BASE = 'http://localhost:8000/api/v1';  // 本机开发
```

**部署后需改成服务器地址**：

```javascript
const API_BASE = 'http://your-server-ip:8000/api/v1';
```

改完后，直接用浏览器打开 `frontend/files.html` 即可访问线上数据。

---

## 八、Android App 连接服务器

App 内置了服务器地址修改入口：**长按主界面「语录」标题** → 弹出设置输入框 → 填入：

```
http://your-server-ip:8000
```

保存后重新上传录音即可走线上链路。

---

## 九、常用运维命令

| 操作 | 命令 |
|------|------|
| 重启服务 | `sudo systemctl restart echomind` |
| 停止服务 | `sudo systemctl stop echomind` |
| 查看日志 | `sudo journalctl -u echomind -f` |
| 更新代码后重启 | `sudo systemctl restart echomind` |
| 查看上传文件 | `ls -lh /opt/echomind/uploads/` |
| 查看数据库 | `sqlite3 /opt/echomind/data/echodmind.db ".tables"` |

---

## 十、（可选）Nginx 反向代理

如果希望用 80 端口访问，或后续配置 HTTPS，可加一层 Nginx：

```bash
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/voicerecorder
```

```nginx
server {
    listen 80;
    server_name your-server-ip;  # 或域名

    client_max_body_size 200M;   # 允许上传大文件

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;  # LLM 生成可能较慢，超时设长一点
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/voicerecorder /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow 80/tcp
```

配好后把 `frontend/api.js` 和 App 的服务器地址改为 `http://your-server-ip`（去掉 `:8000`）即可。

---

## 十一、常见问题排查

| 现象 | 可能原因 | 解法 |
|------|----------|------|
| `systemctl status` 显示 failed | `.env` 缺字段 / Python 包未装 | `journalctl -u echomind -n 50` 查详细报错 |
| 上传成功但 ASR 返回空 | 百炼 API Key 余额不足 / `ASR_TEMP_BASE_URL` 不可达 | 检查 DashScope 余额；确认 `ASR_TEMP_BASE_URL` 能被公网访问 |
| 上传成功但 ASR 返回空（doubao） | 豆包 Token 过期 | 更新 `.env` 中的 `DOUBAO_TOKEN` 后重启 |
| LLM 返回 `choices: null` | Qwen API Key 余额不足 | 充值或换 `LLM_PROVIDER` |
| App 上传失败 | 防火墙未放行 / IP 填错 | 先用浏览器确认 `http://ip:8088/` 能访问 |
| 管理后台跨域报错 | `CORS_ORIGINS` 配置 | 确认 `.env` 中 `CORS_ORIGINS=*` |

---

## 十二、本次 ASR 迁移 FTP 上传清单

如使用 FTP 增量更新，把以下文件上传到服务器 `/opt/echomind/` 目录（覆盖原文件），然后重启服务：

```
services/asr_service.py
utils/file_utils.py
config.py
main.py
.env
.env.example
DEPLOY.md
```

重启命令：

```bash
sudo systemctl restart echomind
```

> 注意：上传 `.env` 前请确认服务器上的真实密钥（`QWEN_API_KEY`、`SECRET_KEY`、`ASR_TEMP_BASE_URL`）已正确填写，不要覆盖为示例值。
