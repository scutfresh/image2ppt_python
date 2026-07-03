from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

# 将 source 目录加入 sys.path，以便导入 openai_client
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "source"))
from openai_client import OpenAICompatClient  # noqa: E402
from prompts import SYSTEM_PROMPT  # noqa: E402


def encode_image_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def build_vision_messages(prompt: str, image_url: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
            ],
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="VLM 图像识别测试脚本 (本地调用)")
    parser.add_argument("image", type=str, help="输入图片路径")
    parser.add_argument(
        "--prompt",
        type=str,
        default="请详细描述这张图片的内容，包括其中出现的所有文字。",
        help="发送给 VLM 的提示词",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.getenv("IMAGE2PPT_VISION_BASE_URL", ""),
        help="VLM API base URL（默认从 IMAGE2PPT_VISION_BASE_URL 环境变量读取）",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="采样温度 (默认: 0.1)",
    )
    args = parser.parse_args()

    if not args.base_url:
        print("错误: 未提供 base_url，请通过 --base-url 或环境变量 IMAGE2PPT_VISION_BASE_URL 指定")
        sys.exit(1)

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"错误: 图片文件不存在: {args.image}")
        sys.exit(1)

    # 编码图片
    print(f"[1/3] 正在编码图片: {args.image}")
    image_url = encode_image_to_data_url(image_path)
    print(f"       编码完成，长度: {len(image_url)} 字符")

    # 构建客户端与消息（与 agent_workflow.py 一致的调用方式）
    client = OpenAICompatClient(base_url=args.base_url)
    messages = build_vision_messages(args.prompt, image_url)

    # 调用 VLM
    print(f"[2/3] 正在调用 VLM ...")
    result = client.chat(messages, args.temperature)

    # 输出结果
    print(f"[3/3] 识别完成\n")
    print("=" * 60)
    print(result)
    print("=" * 60)


if __name__ == "__main__":
    main()
