#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件 - 所有配置项集中管理
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 加载环境变量
load_dotenv(BASE_DIR / ".env", override=True)


# ==================== 服务配置 ====================

class Settings:
    """应用配置"""
    
    # 服务信息
    APP_NAME = "EchoMind"
    APP_VERSION = "1.0.0"
    DEBUG = os.getenv("DEBUG", "true").lower() == "true"
    
    # 服务器
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    
    # 文件存储
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "100"))  # MB
    FILE_EXPIRE_HOURS = int(os.getenv("FILE_EXPIRE_HOURS", "168"))  # 7天后自动删除
    
    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

    # SSL（留空则使用 HTTP，填写后自动切换为 HTTPS）
    SSL_CERTFILE = os.getenv("SSL_CERTFILE", "")   # 证书文件路径，如 /path/to/cert.pem
    SSL_KEYFILE  = os.getenv("SSL_KEYFILE",  "")   # 私钥文件路径，如 /path/to/key.pem


# ==================== ASR 配置 ====================

class ASRSettings:
    """ASR 服务配置"""
    
    # ASR 提供商: qwen(阿里云), doubao(豆包), tencent(腾讯云), baidu(百度)
    PROVIDER = os.getenv("ASR_PROVIDER", "qwen")
    
    # 阿里云 ASR (通义)
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "placeholder")
    QWEN_APP_KEY = os.getenv("QWEN_APP_KEY", "")  # 项目AppKey
    
    # 豆包 ASR
    DOUBAO_APP_ID = os.getenv("DOUBAO_APP_ID", "")
    DOUBAO_ACCESS_KEY = os.getenv("DOUBAO_ACCESS_KEY", "")  # 火山引擎 Access Key
    DOUBAO_SECRET_KEY = os.getenv("DOUBAO_SECRET_KEY", "")  # 火山引擎 Secret Key
    
    # 腾讯云 ASR
    TENCENT_SECRET_ID = os.getenv("TENCENT_SECRET_ID", "")
    TENCENT_SECRET_KEY = os.getenv("TENCENT_SECRET_KEY", "")
    TENCENT_APP_ID = os.getenv("TENCENT_APP_ID", "")
    
    # MiniMax ASR
    MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
    MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "")


# ==================== LLM 配置 ====================

class LLMSettings:
    """LLM 服务配置"""
    
    # LLM 提供商: minimax, kimi, qwen, doubao, zhipu
    PROVIDER = os.getenv("LLM_PROVIDER", "minimax")
    
    # MiniMax
    MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
    MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
    MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
    
    # Kimi (Moonshot)
    KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
    KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
    KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
    
    # 通义千问 (Qwen)
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "placeholder")
    QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
    
    # 豆包 (Doubao)
    DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
    DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    DOUBAO_MODEL = os.getenv("DOUBAO_MODEL", "doubao-32k")
    
    # 智谱 GLM
    ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
    ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    ZHIPU_MODEL = os.getenv("ZHIPU_MODEL", "glm-4")


# 导出配置
settings = Settings()
asr_settings = ASRSettings()
llm_settings = LLMSettings()
