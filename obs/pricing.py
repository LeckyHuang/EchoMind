"""
第三方 API 定价表（CNY / 1K tokens，或 CNY / 次 / 分钟）
来源：各厂商官网公示价格，仅做成本估算参考

未在表中的模型记录 cost=NULL，面板展示为"未知"，绝不用 0 兜底。

价格单位说明：
  LLM  → (input_cny_per_1k_tokens, output_cny_per_1k_tokens)
  ASR  → cny_per_minute（按音频时长计费）
  TTS  → cny_per_1k_chars（按字符计费）

更新日期：2026-06
标注 [?] 的价格需人工核查后填入。
"""

# ══════════════════════════════════════════════════════════════════
# LLM 定价  (input_cny/1K, output_cny/1K)
# ══════════════════════════════════════════════════════════════════

_LLM_PRICE: dict[str, tuple[float, float]] = {

    # ── Moonshot (Kimi) ───────────────────────────────────────────
    # https://platform.moonshot.cn/docs/pricing
    "moonshot-v1-8k":      (0.012,  0.012),
    "moonshot-v1-32k":     (0.024,  0.024),
    "moonshot-v1-128k":    (0.060,  0.060),
    "moonshot-v1-auto":    (0.012,  0.012),   # 自动档按实际窗口定价，此为下限估算

    # ── Qwen / 阿里云百炼 ──────────────────────────────────────────
    # https://bailian.console.aliyun.com/#/model-market
    "qwen-turbo":          (0.0008, 0.002),
    "qwen-turbo-latest":   (0.0008, 0.002),
    "qwen3-turbo":         (0.0008, 0.002),
    "qwen-plus":           (0.0004, 0.0012),
    "qwen-plus-latest":    (0.0004, 0.0012),
    "qwen3-plus":          (0.0004, 0.0012),
    "qwen-max":            (0.040,  0.120),
    "qwen-max-latest":     (0.040,  0.120),
    "qwen3-max":           (0.040,  0.120),
    "qwen-long":           (0.0005, 0.002),
    "qwen3-235b-a22b":     (0.0014, 0.0056),  # MoE 旗舰 [?] 待核查
    "qwen2.5-72b-instruct":(0.004,  0.012),   # [?] 待核查

    # ── MiniMax ───────────────────────────────────────────────────
    # https://www.minimaxi.com/document/price-detail
    "minimax-text-01":     (0.001,  0.008),   # [?] 待核查，官网有活动价
    "abab6.5-chat":        (0.001,  0.008),   # [?] 待核查
    "abab6.5s-chat":       (0.0005, 0.0045),  # [?] 待核查
    "abab5.5-chat":        (0.00015,0.00015), # [?] 待核查

    # ── ByteDance / 豆包 (火山引擎) ───────────────────────────────
    # https://www.volcengine.com/product/doubao
    "doubao-pro-4k":       (0.0008, 0.002),   # [?] 待核查
    "doubao-pro-32k":      (0.0008, 0.002),   # 参考官网活动定价
    "doubao-pro-128k":     (0.005,  0.009),   # [?] 待核查
    "doubao-lite-4k":      (0.0003, 0.0006),  # [?] 待核查
    "doubao-lite-32k":     (0.0003, 0.0006),  # [?] 待核查
    "doubao-32k":          (0.0008, 0.002),   # 别名兜底
    "doubao-128k":         (0.005,  0.009),   # 别名兜底

    # ── Zhipu / 智谱 GLM ──────────────────────────────────────────
    # https://open.bigmodel.cn/pricing
    "glm-4":               (0.100,  0.100),   # [?] 待核查
    "glm-4-flash":         (0.0,    0.0),     # 免费模型
    "glm-4-air":           (0.001,  0.001),   # [?] 待核查
    "glm-4-airx":          (0.010,  0.010),   # [?] 待核查
    "glm-4-long":          (0.001,  0.001),   # [?] 待核查
    "glm-4v":              (0.050,  0.050),   # 视觉版 [?] 待核查
    "glm-zero-preview":    (0.050,  0.050),   # [?] 待核查

    # ── OpenAI（wiki-app 可能使用）────────────────────────────────
    # https://openai.com/api/pricing/
    "gpt-4o":              (0.182,  0.726),   # $25/$100 per 1M ≈ CNY 7.3/7.3
    "gpt-4o-mini":         (0.0109, 0.0436),  # $0.15/$0.6 per 1M
    "gpt-4-turbo":         (0.728,  2.183),   # $10/$30 per 1M
    "gpt-4":               (2.183,  4.366),   # $30/$60 per 1M
    "gpt-3.5-turbo":       (0.036,  0.109),   # $0.5/$1.5 per 1M
    "o1":                  (1.092,  4.366),   # $15/$60 per 1M
    "o1-mini":             (0.218,  0.872),   # $3/$12 per 1M
    "o3-mini":             (0.080,  0.318),   # $1.1/$4.4 per 1M [?]
}


# ══════════════════════════════════════════════════════════════════
# ASR 定价  cny_per_minute（实时流式或文件识别）
# ══════════════════════════════════════════════════════════════════

_ASR_PRICE: dict[str, float] = {
    # ── 阿里云 Paraformer（通义听悟/录音文件识别）─────────────────
    # https://help.aliyun.com/document_detail/2584228.html
    "aliyun-paraformer":    0.00267,  # ¥0.00267/分钟 = ¥0.16/小时（免费额度内）
    "qwen-asr":             0.00267,  # 同上，别名

    # ── 豆包 ASR（火山引擎 bigmodel 录音文件识别标准版）─────────────
    # https://www.volcengine.com/product/speech-to-text
    "doubao-asr":           0.0028,   # [?] ¥0.0028/分钟 待核查
    "doubao-asr-bigmodel":  0.0028,   # 同上，别名

    # ── MiniMax ASR（asr-01）─────────────────────────────────────
    # https://www.minimaxi.com/document/price-detail
    "minimax-asr":          0.0167,   # [?] 待核查（官网按小时）
    "minimax-asr-01":       0.0167,   # 别名

    # ── 腾讯云 ASR（录音文件识别）────────────────────────────────
    # https://cloud.tencent.com/product/asr/pricing
    "tencent-asr":          0.00250,  # [?] ¥0.0025/分钟 待核查

    # ── 百度 ASR（短语音识别）─────────────────────────────────────
    # https://cloud.baidu.com/product/speech/asr
    "baidu-asr":            0.00150,  # [?] ¥0.0015/分钟 待核查
}


# ══════════════════════════════════════════════════════════════════
# TTS 定价  cny_per_1k_chars（暂未接入，预留）
# ══════════════════════════════════════════════════════════════════

_TTS_PRICE: dict[str, float] = {
    # ── 阿里云 TTS（CosyVoice）───────────────────────────────────
    # https://help.aliyun.com/document_detail/2584228.html
    "aliyun-cosyvoice":     0.100,    # [?] ¥0.1/千字 待核查

    # ── 火山引擎 TTS（双语 / 大模型）────────────────────────────
    "doubao-tts":           0.080,    # [?] 待核查

    # ── MiniMax TTS（speech-02）──────────────────────────────────
    "minimax-tts":          0.060,    # [?] 待核查

    # ── OpenAI TTS（tts-1 / tts-1-hd）────────────────────────────
    "openai-tts-1":         0.109,    # $15/1M chars ≈ ¥0.109/千字
    "openai-tts-1-hd":      0.218,    # $30/1M chars
}


# ══════════════════════════════════════════════════════════════════
# 视觉/多模态 定价  (input_cny/1K_tokens, output_cny/1K_tokens)
# ══════════════════════════════════════════════════════════════════

_VISION_PRICE: dict[str, tuple[float, float]] = {
    # ── 豆包视觉（wiki-app 多模态 ingest）────────────────────────
    "doubao-vision-lite-32k":  (0.0003, 0.0006),  # [?] 待核查
    "doubao-vision-pro-32k":   (0.008,  0.008),   # [?] 待核查

    # ── Qwen-VL ──────────────────────────────────────────────────
    "qwen-vl-plus":            (0.008,  0.008),   # [?] 待核查
    "qwen-vl-max":             (0.030,  0.030),   # [?] 待核查

    # ── OpenAI GPT-4o（含视觉）────────────────────────────────────
    "gpt-4o":                  (0.182,  0.726),   # 与文本同价（含图片 token）
}


# ══════════════════════════════════════════════════════════════════
# 对外接口
# ══════════════════════════════════════════════════════════════════

def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """返回 LLM 调用的 CNY 成本。模型未知时返回 None（面板显示"未知"）"""
    if input_tokens is None or output_tokens is None:
        return None
    key = model.lower().strip()

    # 精确匹配
    price = _LLM_PRICE.get(key) or _VISION_PRICE.get(key)

    # 前缀匹配（应对带 snapshot 日期的版本号，如 qwen-turbo-2025-04-28）
    if price is None:
        for prefix, p in {**_LLM_PRICE, **_VISION_PRICE}.items():
            if key.startswith(prefix):
                price = p
                break

    if price is None:
        return None
    in_price, out_price = price
    cost = input_tokens / 1000 * in_price + output_tokens / 1000 * out_price
    return round(cost, 6)


def calc_asr_cost(provider_key: str, duration_minutes: float) -> float | None:
    """返回 ASR 调用的 CNY 成本。provider_key 不在表中时返回 None"""
    price = _ASR_PRICE.get(provider_key.lower().strip())
    if price is None:
        return None
    return round(duration_minutes * price, 6)


def calc_tts_cost(provider_key: str, char_count: int) -> float | None:
    """返回 TTS 调用的 CNY 成本。"""
    price = _TTS_PRICE.get(provider_key.lower().strip())
    if price is None:
        return None
    return round(char_count / 1000 * price, 6)
