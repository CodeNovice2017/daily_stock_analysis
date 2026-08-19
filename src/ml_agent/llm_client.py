# -*- coding: utf-8 -*-
"""中长线模块 LLM 客户端。

从 .env 读取 LLM 配置，用 openai SDK 走 zhipu endpoint。
独立于 DSA 的 Agent runner / litellm router，避免短线逻辑泄露。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_CLIENT: Optional[OpenAI] = None
_MODEL: Optional[str] = None


def _load_env() -> dict:
    """从项目根目录 .env 读取 LLM 配置。"""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    config = {}
    if not env_path.exists():
        return config
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                config[key.strip()] = val.strip()
    return config


def get_client() -> OpenAI:
    """惰性初始化 OpenAI 客户端（走 zhipu endpoint）。"""
    global _CLIENT, _MODEL
    if _CLIENT is not None:
        return _CLIENT

    env = _load_env()

    # 优先用 zhipu channel
    api_key = env.get("LLM_ZHIPU_API_KEY", "")
    base_url = env.get("LLM_ZHIPU_BASE_URL", "")
    _MODEL = env.get("LLM_ZHIPU_MODELS", "glm-5.2").split(",")[0].strip()

    if not api_key:
        raise RuntimeError("LLM_ZHIPU_API_KEY 未配置")

    _CLIENT = OpenAI(api_key=api_key, base_url=base_url)
    logger.info(f"[ML-LLM] 初始化完成: model={_MODEL}, base_url={base_url}")
    return _CLIENT


def get_model() -> str:
    """返回配置的模型名。"""
    if _MODEL is None:
        get_client()
    return _MODEL or "glm-5.2"


def chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
) -> str:
    """简单 LLM 调用，返回文本内容。

    .. note::
        glm-5.2 是推理模型，会先生成 reasoning_content（不计入最终输出），
        再生成 content（实际回复）。``max_tokens`` 需要足够大（建议 >=4000），
        否则 reasoning 阶段就用完 token，content 为空。

    Args:
        system_prompt: 系统提示词。
        user_prompt: 用户提示词（含上下文数据）。
        temperature: 温度。
        max_tokens: 最大输出 token（含 reasoning token）。

    Returns:
        LLM 回复的文本内容（content 字段）。
    """
    client = get_client()
    model = get_model()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    msg = resp.choices[0].message
    return msg.content or ""
