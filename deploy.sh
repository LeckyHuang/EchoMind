#!/bin/bash

# 语录后端部署脚本 (Linux/MacOS)

# 1. 检查 Python 环境
if ! command -v python3 &> /dev/null
then
    echo "错误: 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 2. 创建虚拟环境 (推荐)
echo "正在创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
echo "正在安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. 检查 .env 文件
if [ ! -f .env ]; then
    echo "警告: 未找到 .env 文件，正在从 .env.example 创建..."
    cp .env.example .env
    echo "请编辑 .env 文件并填入真实的 API Key (ASR_PROVIDER, LLM_PROVIDER)"
fi

# 5. 创建上传目录
mkdir -p uploads

# 6. 启动服务 (后台运行建议使用 pm2 或 systemd)
echo "------------------------------------------------"
echo "部署完成！可以使用以下命令启动服务："
echo "source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo "------------------------------------------------"
