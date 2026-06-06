#!/usr/bin/env bash
# ============================================================
# EchoMind 启动脚本
# 用法：./start.sh
# ============================================================

set -e  # 任意一条命令失败就立刻退出

# ---------- ① 切换到脚本所在目录 ----------
# 不管你从哪里运行这个脚本，都能正确找到项目文件
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "📁 工作目录: $SCRIPT_DIR"

# ---------- ② 检查并激活虚拟环境 ----------
if [ ! -d "venv" ]; then
    echo "❌ 未找到 venv 目录，请先运行："
    echo "   python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "🐍 激活虚拟环境..."
source venv/bin/activate

# ---------- ③ 首次启动检查：数据库初始化 ----------
# 如果数据库文件不存在，说明是第一次启动，需要初始化管理员账号
if [ ! -f "data/echodmind.db" ]; then
    echo "🗄️  首次启动，初始化数据库和管理员账号..."
    python init_admin.py
    echo "✅ 初始化完成，默认账号 admin / 123456"
fi

# ---------- ④ 自动打开浏览器（延迟 2 秒，等服务启动） ----------
# macOS 专属：后台延迟执行，不阻塞服务启动
(sleep 2 && open "http://localhost:8088/app/echodmind/login.html") &

# ---------- ⑤ 启动服务 ----------
echo ""
echo "🚀 启动 EchoMind 服务..."
echo "   管理后台: http://localhost:8088/app/echodmind/login.html"
echo "   API 文档: http://localhost:8088/docs"
echo "   按 Ctrl+C 停止服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python main.py
