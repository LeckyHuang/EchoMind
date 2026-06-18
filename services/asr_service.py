#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR 服务 - 语音转文字
支持: 阿里云(通义)、豆包、腾讯云、百度、MiniMax
"""

import asyncio
import httpx
import json
import time
import uuid
import base64
import hmac
import hashlib
from pathlib import Path
from typing import Optional
import logging

from config import asr_settings

logger = logging.getLogger(__name__)

try:
    import obs as _obs
except ImportError:
    _obs = None


class ASRService:
    """ASR 服务统一接口"""

    def __init__(self):
        self.provider = asr_settings.PROVIDER
        logger.info(f"ASR服务初始化，提供商: {self.provider}")

    async def transcribe(self, file_path: str, audio_duration_s: float = 0.0) -> dict:
        """
        语音转文字
        :param file_path: 音频文件路径
        :param audio_duration_s: 音频时长（秒），用于 ASR 成本计算
        :return: {"success": bool, "text": str, "error": str}
        """
        if not Path(file_path).exists():
            return {"success": False, "text": "", "error": "文件不存在"}

        if _obs:
            if audio_duration_s > 0:
                span_kwargs = {
                    "audio_duration_s": audio_duration_s,
                    "audio_size_bytes": Path(file_path).stat().st_size,
                }
                with _obs.span("asr", provider=self.provider, **span_kwargs):
                    return await self._do_transcribe(file_path)
            else:
                with _obs.span("asr", provider=self.provider):
                    return await self._do_transcribe(file_path)
        return await self._do_transcribe(file_path)

    async def _do_transcribe(self, file_path: str) -> dict:
        try:
            if self.provider == "qwen":
                return await self._transcribe_qwen(file_path)
            elif self.provider == "doubao":
                return await self._transcribe_doubao(file_path)
            elif self.provider == "minimax":
                return await self._transcribe_minimax(file_path)
            elif self.provider == "mock":
                return await self._mock_transcribe(file_path)
            elif self.provider == "tencent":
                return await self._transcribe_tencent(file_path)
            elif self.provider == "baidu":
                return await self._transcribe_baidu(file_path)
            else:
                return {"success": False, "text": "", "error": f"未知的ASR提供商: {self.provider}"}
        except Exception as e:
            logger.error(f"ASR转写异常: {str(e)}")
            return {"success": False, "text": "", "error": str(e)}

    async def _mock_transcribe(self, file_path: str) -> dict:
        """模拟转写 - 用于测试"""
        logger.info(f"使用模拟转写模式，文件: {file_path}")
        await asyncio.sleep(1)
        mock_text = """
        面试官：你好，请简单介绍一下你自己。
        求职者：您好，我叫张三，毕业于北京大学计算机科学专业。之前在字节跳动担任产品经理助理，主要负责数据分析和用户调研工作。
        面试官：你在之前的项目中遇到过最大的挑战是什么？
        求职者：最大的挑战是团队协调和资源争取。因为涉及多个部门，需要协调开发、设计、运营等多个团队。
        面试官：你的职业规划是什么？
        求职者：我的职业规划是深耕产品领域，3年内成为高级产品经理，能够独立负责一个完整的产品线。
        """
        return {"success": True, "text": mock_text.strip(), "duration": 180}

    # ==================== MiniMax ASR ====================

    async def _transcribe_minimax(self, file_path: str) -> dict:
        """MiniMax ASR"""
        api_key = asr_settings.MINIMAX_API_KEY
        group_id = asr_settings.MINIMAX_GROUP_ID

        if not api_key:
            return await self._mock_transcribe(file_path)

        url = "https://api.minimax.chat/v1/audio_transcription"
        if group_id:
            url += f"?GroupId={group_id}"

        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (Path(file_path).name, f)}
                    data = {"model": "asr-01"}
                    resp = await client.post(url, files=files, data=data, headers=headers)

                if resp.status_code == 200:
                    result = resp.json()
                    return {"success": True, "text": result.get("text", "")}
                else:
                    logger.error(f"MiniMax ASR错误: {resp.text}")
                    return {"success": False, "text": "", "error": f"API错误: {resp.status_code}"}
        except Exception as e:
            logger.error(f"MiniMax ASR请求异常: {e}")
            return {"success": False, "text": "", "error": str(e)}

    # ==================== 豆包 ASR V3 (火山引擎) ====================

    def _generate_volc_token(self, access_token: str, secret_key: str) -> str:
        """生成火山引擎签名 Token"""
        import datetime
        now = datetime.datetime.utcnow()
        expire = now + datetime.timedelta(hours=1)

        sign_str = "".join([
            f"GET\n",
            f"/api/v3/auc/bigmodel/submit\n",
            f"host:openspeech.bytedance.com\n",
            f"date: {now.strftime('%Y%m%dT%H%M%SZ')}\n",
            f"action: BigmodelAudioSubmit\n",
            f"version: 2024-03-01\n",
            f"{expire.strftime('%Y%m%dT%H%M%SZ')}"
        ])

        signature = hmac.new(
            secret_key.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return f"Bearer; {access_token}; {signature}"

    async def _transcribe_doubao(self, file_path: str) -> dict:
        """豆包 ASR V3 - 录音文件识别标准版"""
        app_id = asr_settings.DOUBAO_APP_ID
        access_key = asr_settings.DOUBAO_ACCESS_KEY
        secret_key = asr_settings.DOUBAO_SECRET_KEY

        if not access_key:
            logger.warning("豆包ASR未配置Token，使用模拟模式")
            return await self._mock_transcribe(file_path)

        request_id = str(uuid.uuid4())
        file_ext = Path(file_path).suffix.lower().replace(".", "")

        # 豆包只支持 MP3，非 mp3 文件需要先用 ffmpeg 转换
        mp3_tmp_path = None
        actual_path = file_path
        if file_ext != "mp3":
            mp3_tmp_path = str(Path(file_path).with_suffix(".tmp_asr.mp3"))
            try:
                import shutil
                ffmpeg_bin = shutil.which("ffmpeg") or "/root/miniconda3/bin/ffmpeg"
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg_bin, "-y", "-i", file_path,
                    "-ar", "16000", "-ac", "1", "-b:a", "64k",
                    mp3_tmp_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.error(f"ffmpeg转换失败: {stderr.decode()}")
                    return {"success": False, "text": "", "error": "音频格式转换失败（ffmpeg错误）"}
                actual_path = mp3_tmp_path
                logger.info(f"豆包ASR: 已将 {file_ext} 转换为 mp3: {mp3_tmp_path}")
            except FileNotFoundError:
                logger.error("ffmpeg未安装，无法转换音频格式")
                return {"success": False, "text": "", "error": "服务器缺少 ffmpeg，无法处理非 mp3 文件"}

        file_size = Path(actual_path).stat().st_size
        logger.info(f"豆包ASR开始处理: format=mp3, size={file_size/1024/1024:.1f}MB")

        with open(actual_path, "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode("utf-8")
        logger.info(f"豆包ASR base64编码完成，payload大小: {len(audio_base64)/1024/1024:.1f}MB")

        # 转换后的临时文件已读取，立即删除
        if mp3_tmp_path:
            try:
                Path(mp3_tmp_path).unlink()
            except Exception:
                pass

        submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
        authorization = self._generate_volc_token(access_key, secret_key)

        headers = {
            "Authorization": authorization,
            "X-Api-Access-Key": access_key,
            "X-Api-App-Key": app_id,
            "X-Api-Resource-Id": "volc.bigasr.auc",
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json"
        }

        payload = {
            "user": {"uid": "voicerecorder"},
            "audio": {
                "format": "mp3",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "data": audio_base64
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True
            }
        }

        try:
            # trust_env=False：禁止继承系统代理（SOCKS/HTTP），豆包是国内服务直连即可
            async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
                # 1. 提交任务（大文件 base64 上传需要更长超时）
                resp = await client.post(submit_url, json=payload, headers=headers)
                status_code = resp.headers.get("X-Api-Status-Code", "")
                message = resp.headers.get("X-Api-Message", "")

                logger.info(f"豆包ASR提交任务: status={status_code}, message={message}")

                if status_code != "20000000" and status_code != "":
                    logger.error(f"豆包ASR提交失败: status={status_code}, message={message}, body={resp.text}")
                    return {"success": False, "text": "", "error": f"提交失败: {message}"}

                # 2. 轮询查询结果
                await asyncio.sleep(2)

                query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
                query_headers = {
                    "Authorization": authorization,
                    "X-Api-Access-Key": access_key,
                    "X-Api-App-Key": app_id,
                    "X-Api-Resource-Id": "volc.bigasr.auc",
                    "X-Api-Request-Id": request_id,
                    "Content-Type": "application/json"
                }

                for i in range(90):
                    await asyncio.sleep(2)

                    resp = await client.post(query_url, json={}, headers=query_headers, timeout=30)
                    result_status = resp.headers.get("X-Api-Status-Code", "")

                    if result_status == "20000000":
                        result_body = resp.json()
                        text = result_body.get("result", {}).get("text", "")
                        logger.info(f"豆包ASR识别成功，文字长度: {len(text)}")
                        return {"success": True, "text": text}

                    elif result_status in ["20000001", "20000002"]:
                        logger.info(f"豆包ASR处理中... ({i+1}/30)")
                        continue

                    elif result_status == "20000003":
                        return {"success": False, "text": "", "error": "音频中没有检测到人声"}

                    else:
                        error_msg = resp.headers.get("X-Api-Message", result_status)
                        logger.error(f"豆包ASR查询失败: status={result_status}, msg={error_msg}, body={resp.text}")
                        return {"success": False, "text": "", "error": f"查询失败: {error_msg}"}

                return {"success": False, "text": "", "error": "识别超时，请检查音频文件或网络连接"}

        except httpx.HTTPError as e:
            logger.error(f"豆包ASR网络错误: {e}")
            return {"success": False, "text": "", "error": f"网络错误: {str(e)}"}
        except Exception as e:
            logger.error(f"豆包ASR请求异常: {e}")
            return {"success": False, "text": "", "error": str(e)}

    # ==================== 阿里云 ASR (通义 / 百炼 Fun-ASR) ====================

    def _extract_funasr_text(self, transcription: dict) -> str:
        """从 Fun-ASR 转写结果 JSON 中提取文本"""
        texts = []
        for transcript in transcription.get("transcripts", []):
            text = transcript.get("text", "")
            if text:
                texts.append(text)
        return "\n".join(texts)

    async def _transcribe_qwen(self, file_path: str) -> dict:
        """阿里云百炼 Fun-ASR 录音文件识别（异步任务 + 轮询）"""
        api_key = asr_settings.QWEN_API_KEY

        if not api_key or api_key == "placeholder":
            logger.warning("百炼ASR未配置API Key，使用模拟模式")
            return await self._mock_transcribe(file_path)

        # 生成临时下载 URL，供百炼服务端拉取音频文件
        from utils.file_utils import create_asr_temp_url
        filename = Path(file_path).name
        file_url = create_asr_temp_url(filename, expire_seconds=1800)

        logger.info(f"Fun-ASR开始处理: {filename}, url={file_url}")

        submit_url = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
        query_base_url = "https://dashscope.aliyuncs.com/api/v1/tasks/"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable"
        }

        payload = {
            "model": "fun-asr",
            "input": {
                "file_urls": [file_url]
            },
            "parameters": {
                "channel_id": [0],
                "language_hints": ["zh", "en"]
            }
        }

        try:
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                # 1. 提交任务
                resp = await client.post(submit_url, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.error(f"Fun-ASR提交失败: {resp.status_code} {resp.text}")
                    return {"success": False, "text": "", "error": f"提交失败: {resp.status_code}"}

                result = resp.json()
                output = result.get("output", {})
                task_id = output.get("task_id")
                if not task_id:
                    logger.error(f"Fun-ASR提交响应异常: {result}")
                    return {"success": False, "text": "", "error": "提交响应异常，未返回 task_id"}

                logger.info(f"Fun-ASR任务已提交: {task_id}")

                # 2. 轮询查询结果
                query_headers = {"Authorization": f"Bearer {api_key}"}
                for i in range(180):  # 最多 180 * 2s = 6 分钟
                    await asyncio.sleep(2)

                    resp = await client.get(f"{query_base_url}{task_id}", headers=query_headers)
                    if resp.status_code != 200:
                        logger.error(f"Fun-ASR查询失败: {resp.status_code} {resp.text}")
                        continue

                    result = resp.json()
                    output = result.get("output", {})
                    task_status = output.get("task_status", "")
                    logger.info(f"Fun-ASR任务状态: {task_status} ({i+1}/180)")

                    if task_status == "SUCCEEDED":
                        results = output.get("results", [])
                        if not results:
                            return {"success": False, "text": "", "error": "转写结果为空"}

                        transcription_url = results[0].get("transcription_url", "")
                        if not transcription_url:
                            return {"success": False, "text": "", "error": "转写结果URL为空"}

                        # 下载 JSON 转写结果
                        resp = await client.get(transcription_url, timeout=60)
                        if resp.status_code != 200:
                            return {"success": False, "text": "", "error": f"下载转写结果失败: {resp.status_code}"}

                        transcription = resp.json()
                        text = self._extract_funasr_text(transcription)
                        logger.info(f"Fun-ASR识别成功，文字长度: {len(text)}")
                        return {"success": True, "text": text}

                    elif task_status == "FAILED":
                        error_message = output.get("message", "未知错误")
                        logger.error(f"Fun-ASR任务失败: {error_message}")
                        return {"success": False, "text": "", "error": f"识别失败: {error_message}"}

                    elif task_status in ["UNKNOWN", "CANCELLED"]:
                        return {"success": False, "text": "", "error": f"任务状态异常: {task_status}"}

                    # PENDING / RUNNING 继续轮询

                return {"success": False, "text": "", "error": "识别超时，请检查音频文件或网络连接"}

        except httpx.HTTPError as e:
            logger.error(f"Fun-ASR网络错误: {e}")
            return {"success": False, "text": "", "error": f"网络错误: {str(e)}"}
        except Exception as e:
            logger.error(f"Fun-ASR请求异常: {e}")
            return {"success": False, "text": "", "error": str(e)}

    # ==================== 腾讯云 ASR ====================

    async def _transcribe_tencent(self, file_path: str) -> dict:
        """腾讯云 ASR"""
        return await self._mock_transcribe(file_path)

    # ==================== 百度 ASR ====================

    async def _transcribe_baidu(self, file_path: str) -> dict:
        """百度 ASR"""
        api_key = asr_settings.BAIDU_API_KEY
        secret_key = asr_settings.BAIDU_SECRET_KEY

        if not api_key or not secret_key:
            return await self._mock_transcribe(file_path)

        try:
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                # 获取 token
                token_url = "https://aip.baidubce.com/oauth/2.0/token"
                params = {"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}

                resp = await client.get(token_url, params=params)
                if resp.status_code != 200:
                    return {"success": False, "text": "", "error": "获取百度token失败"}
                token_data = resp.json()
                access_token = token_data.get("access_token")

                if not access_token:
                    return {"success": False, "text": "", "error": "获取access_token失败"}

                # 调用 ASR
                asr_url = f"https://vop.baidu.com/server_api?access_token={access_token}"

                with open(file_path, "rb") as f:
                    audio_base64 = base64.b64encode(f.read()).decode()

                asr_data = {
                    "format": "pcm", "rate": 16000, "dev_pid": 15372,
                    "channel": 1, "len": len(audio_base64), "speech": audio_base64
                }

                resp = await client.post(asr_url, json=asr_data, headers={"Content-Type": "application/json"}, timeout=60)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("err_no") == 0:
                        return {"success": True, "text": "".join(result.get("result", []))}
                    else:
                        return {"success": False, "text": "", "error": result.get("err_msg", "未知错误")}
                else:
                    return {"success": False, "text": "", "error": f"API错误: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "text": "", "error": str(e)}
