from __future__ import annotations

import base64
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import warnings
import requests
from PIL import Image
import time                 
from functools import wraps

@dataclass
class ImageGenConfig:
    base_url: str
    model: str
    size: str
    timeout: int = 200
    api_style: str = "openai"


class ImageGenError(RuntimeError):
    pass

def retry_on_rate_limit(max_retries=5, initial_delay=3.0, backoff_factor=2.0):
    """
    专门针对 429 限流报错的指数退避重试装饰器。
    如果遇到限流，会按 initial_delay * (backoff_factor ^ attempt) 的时间递增等待。
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except ImageGenError as e:
                    error_msg = str(e)
                    # 检查是否是 429 或限流相关的报错
                    if "429" in error_msg or "Throttling" in error_msg:
                        if attempt == max_retries - 1:
                            print(f"\n❌ [彻底失败] 连续 {max_retries} 次触发图片生成限流，放弃。")
                            raise
                        print(f"\n⏳ [触发限流 429] 阿里云并发保护。休眠 {delay} 秒后重试 ({attempt + 1}/{max_retries})...")
                        time.sleep(delay)
                        delay *= backoff_factor  # 下一次重试等待更长的时间
                    else:
                        # 如果是其他错误（比如 400 参数错误、401 鉴权失败），直接抛出，不重试
                        raise
        return wrapper
    return decorator

def join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def normalize_dashscope_size(size: str) -> str:
    if "x" in size or "X" in size:
        return size.replace("x", "*").replace("X", "*")
    return size

@retry_on_rate_limit(max_retries=5, initial_delay=3.0)
def request_image(
    config: ImageGenConfig,
    prompt: str,
    negative_prompt: str | None,
    transparent: bool,
    size_override: str | None = None,
) -> dict[str, Any]:
    if not config.base_url:
        raise ImageGenError("IMAGE2PPT_IMAGEGEN_BASE_URL is required")

    # 从 size_override 或 config.size 解析宽高 (保留 image_size 处理)
    size_str = size_override or config.size
    parsed = parse_size_spec(size_str)
    if parsed:
        w, h = parsed
    else:
        w, h = 1024, 1024

    # 确保宽高为 64 的倍数且不超出模型尺寸范围 [512, 2048]
    w = snap_to_multiple(w, min_val=512, max_val=2048)
    h = snap_to_multiple(h, min_val=512, max_val=2048)

    api_style = (config.api_style or "openai").strip().lower()

    # 本地直连生成服务 (如 http://192.168.210.1:9011/v1/generate)
    # 接收相同 prompt/height/width 输入，直接返回 {"image_base64": "..."} 
    if api_style == "zimage":
        payload_data = json.dumps({
            "prompt": prompt,
            "height": h,
            "width": w,
            "num_inference_steps": 8,
            "seed": 42,
        }).encode("utf-8")
        req = urllib.request.Request(
            config.base_url.rstrip("/"),
            data=payload_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=config.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    # 默认 OpenAI 兼容的 Chat API
    url = config.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    payload = {
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "extra_body": {
            "height": h,
            "width": w,
            "num_inference_steps": 50,
            "true_cfg_scale": 4.0,
            "seed": 42,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=config.timeout)
    if resp.status_code >= 400:
        raise ImageGenError(f"imagegen failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def parse_size_spec(size: str | None) -> tuple[int, int] | None:
    if not size:
        return None
    value = size.strip().lower().replace("*", "x")
    if "x" not in value:
        return None
    parts = value.split("x", 1)
    if len(parts) != 2:
        return None
    try:
        width = int(float(parts[0]))
        height = int(float(parts[1]))
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def snap_to_multiple(
    value: int,
    min_val: int = 16,
    max_val: int | None = None,
) -> int:
    """将尺寸值取整到最接近的 value 的倍数，并钳位到 [min_val, max_val] 区间。

    Args:
        value: 原始像素尺寸。
        min_val: 最小允许值（默认 16）。
        max_val: 最大允许值，None 表示不限制上限。
    """
    if value <= 0:
        return min_val
    snapped = int(round(value / 16)) * 16
    if snapped < min_val:
        snapped = min_val
    if max_val is not None and snapped > max_val:
        snapped = max_val
    return snapped


def adjust_qwen_size(size: str) -> tuple[str, tuple[int, int] | None, float | None]:
    original = parse_size_spec(size)
    if not original:
        return size, None, None
    orig_width, orig_height = original
    width = float(orig_width)
    height = float(orig_height)
    min_size = 512
    max_size = 2048

    if max(width, height) > max_size:
        scale_down = max_size / max(width, height)
        width *= scale_down
        height *= scale_down

    if min(width, height) < min_size:
        ideal_scale = min_size / min(width, height)
        max_allowed_scale = max_size / max(width, height)
        safe_scale = min(ideal_scale, max_allowed_scale)
        width *= safe_scale
        height *= safe_scale

    new_width = max(1, int(round(width)))
    new_height = max(1, int(round(height)))

    crop_ratio = None
    if min(new_width, new_height) < min_size or max(new_width, new_height) > max_size:
        new_width = min(max(new_width, min_size), max_size)
        new_height = min(max(new_height, min_size), max_size)
        crop_ratio = orig_width / orig_height

    # 将宽高对齐到 64 的倍数并钳位到 [min_size, max_size]，确保不超出模型限制
    new_width = snap_to_multiple(new_width, min_val=min_size, max_val=max_size)
    new_height = snap_to_multiple(new_height, min_val=min_size, max_val=max_size)

    if new_width == orig_width and new_height == orig_height:
        return size, None, None
    return f"{new_width}x{new_height}", (orig_width, orig_height), crop_ratio


def extract_image_bytes(payload: dict[str, Any]) -> bytes:
    """从大模型 API 的返回结果中提取图片的二进制数据"""

    # 本地直连生成服务格式: {"image_base64": "..."}
    if "image_base64" in payload:
        return base64.b64decode(payload["image_base64"])

    # 本地 OpenAI 兼容服务格式: choices[0].message.content[0].image_url.url (data:image/png;base64,...)
    choices = payload.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content") or []
        if content and isinstance(content, list):
            img_info = content[0].get("image_url") or {}
            data_uri = img_info.get("url", "")
            if data_uri and "," in data_uri:
                b64 = data_uri.split(",", 1)[1]
                return base64.b64decode(b64)

    # 兼容百炼、Replicate 等格式 (output -> choices / results)
    output = payload.get("output") or {}
    results = output.get("results") or output.get("choices") or []
    
    if results:
        item = results[0]
        
        # 专门适配 Z-Image 的多模态消息结构 (message -> content -> image)
        if "message" in item and "content" in item["message"]:
            content = item["message"]["content"]
            if content and isinstance(content, list) and "image" in content[0]:
                url = content[0]["image"]
                # 请求图片 URL 获取二进制内容
                resp = requests.get(url, timeout=120)
                if resp.status_code >= 400:
                    raise ImageGenError(f"图片下载失败，HTTP状态码: {resp.status_code}")
                return resp.content
        
        # 兼容其他带有 base64 或直接提供 url 的模型返回格式
        if "b64_json" in item:
            return base64.b64decode(item["b64_json"])
        if "base64" in item:
            return base64.b64decode(item["base64"])
        if "url" in item:
            url = item["url"]
            resp = requests.get(url, timeout=120)
            if resp.status_code >= 400:
                raise ImageGenError(f"图片下载失败，HTTP状态码: {resp.status_code}")
            return resp.content
            
    # 兼容标准 OpenAI 等格式 (data -> b64_json / url)
    data = payload.get("data") or []
    if data:
        item = data[0]
        if "b64_json" in item:
            return base64.b64decode(item["b64_json"])
        if "url" in item:
            url = item["url"]
            resp = requests.get(url, timeout=120)
            if resp.status_code >= 400:
                raise ImageGenError(f"图片下载失败，HTTP状态码: {resp.status_code}")
            return resp.content

    raise ImageGenError("imagegen response missing image data")


def center_crop_to_ratio(image: Image.Image, ratio: float) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        return image
    current_ratio = width / height
    if abs(current_ratio - ratio) < 1e-4:
        return image
    if current_ratio > ratio:
        new_width = max(1, int(round(height * ratio)))
        left = max(0, (width - new_width) // 2)
        return image.crop((left, 0, left + new_width, height))
    new_height = max(1, int(round(width / ratio)))
    top = max(0, (height - new_height) // 2)
    return image.crop((0, top, width, top + new_height))


def ensure_png(
    image_path: Path,
    output_path: Path,
    size: tuple[int, int] | None,
    crop_ratio: float | None,
) -> Path:
    with Image.open(image_path) as image:
        image = image.convert("RGBA")
        if crop_ratio:
            image = center_crop_to_ratio(image, crop_ratio)
        if size and size[0] > 0 and size[1] > 0:
            image = image.resize(size, Image.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG")
    return output_path


def safe_filename(name: str, suffix: str = ".png") -> str:
    keep = []
    for ch in name.lower().strip():
        if ch.isalnum() or ch in {"-", "_"}:
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    base = "".join(keep).strip("_") or "asset"
    return base + suffix


def save_raw_image(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(extract_image_bytes(payload))
    return output_path



def generate_image(
    config: ImageGenConfig,
    prompt: str,
    negative_prompt: str | None,
    transparent: bool,
    raw_dir: Path,
    name_hint: str,
    output_path: Path,
    request_size: str | None,
    resize: tuple[int, int] | None,
) -> Path:
    size_override = request_size
    resize_target = resize
    crop_ratio = None
    api_style = (config.api_style or "openai").strip().lower()
    if request_size:
        adjusted_size, resize_back, crop_ratio = adjust_qwen_size(request_size)
        if adjusted_size != request_size:
            print(f"Image size adjusted: {request_size} -> {adjusted_size}")
        size_override = adjusted_size
        if resize_target is None:
            resize_target = resize_back
    payload = request_image(config, prompt, negative_prompt, transparent, size_override=size_override)
    raw_name = safe_filename(name_hint, suffix=".png")
    raw_path = raw_dir / raw_name
    save_raw_image(payload, raw_path)
    
    return ensure_png(raw_path, output_path, resize_target, crop_ratio)
