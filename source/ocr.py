from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


class OCREngine:
    """OCR 文字识别接口的 Python 封装。

    对应 API: POST /ai/service/v2/recognize/multipage
    请求体: 图片二进制数据 (Content-Type: application/octet-stream)
    响应: JSON
    """

    def __init__(
        self,
        host: str = "192.168.210.128",
        port: int = 50623,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    @property
    def endpoint(self) -> str:
        return f"http://{self._host}:{self._port}/ai/service/v2/recognize/multipage"

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        """识别图片中的文字，返回 JSON 结果。

        Args:
            image_path: 图片文件路径。

        Returns:
            API 返回的 JSON 对象（dict）。
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {image_path}")

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        return self.recognize_bytes(image_bytes)

    def recognize_bytes(self, image_bytes: bytes) -> dict[str, Any]:
        """识别图片二进制数据中的文字，返回 JSON 结果。

        Args:
            image_bytes: 图片的二进制数据。

        Returns:
            API 返回的 JSON 对象（dict）。
        """
        resp = requests.post(
            self.endpoint,
            data=image_bytes,
            headers={"Content-Type": "application/octet-stream"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def recognize_to_file(
        self, image_path: str | Path, output_path: str | Path
    ) -> dict[str, Any]:
        """识别图片文字并将结果保存为 JSON 文件。

        Args:
            image_path: 图片文件路径。
            output_path: 输出 JSON 文件路径。

        Returns:
            API 返回的 JSON 对象（dict）。
        """
        result = self.recognize(image_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def recognize_to_vlm_file(
        self, image_path: str | Path, output_path: str | Path
    ) -> list[dict[str, Any]]:
        """OCR 识别图片文字，转换为 VLM 格式，保存为 JSON 文件。

        一次调用完成：OCR 识别 → convert_ocr_to_vlm_format → 写入 JSON。

        Args:
            image_path: 图片文件路径。
            output_path: 输出 JSON 文件路径。

        Returns:
            转换后的 VLM 格式元素列表。
        """
        ocr_result = self.recognize(image_path)
        vlm_elements = convert_ocr_to_vlm_format(ocr_result)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(vlm_elements, f, ensure_ascii=False, indent=2)
        return vlm_elements



# 模块级便捷函数
_default_engine: OCREngine | None = None


def recognize(image_path: str | Path) -> dict[str, Any]:
    """便捷函数：使用默认配置识别图片文字。"""
    global _default_engine
    if _default_engine is None:
        _default_engine = OCREngine()
    return _default_engine.recognize(image_path)


def recognize_to_file(
    image_path: str | Path, output_path: str | Path
) -> dict[str, Any]:
    """便捷函数：识别图片文字并保存到 JSON 文件。"""
    global _default_engine
    if _default_engine is None:
        _default_engine = OCREngine()
    return _default_engine.recognize_to_file(image_path, output_path)


def recognize_to_vlm_file(
    image_path: str | Path, output_path: str | Path
) -> list[dict[str, Any]]:
    """便捷函数：OCR 识别 → VLM 格式 → JSON 文件，一次调用完成。"""
    global _default_engine
    if _default_engine is None:
        _default_engine = OCREngine()
    return _default_engine.recognize_to_vlm_file(image_path, output_path)



def convert_ocr_to_vlm_format(ocr_result: dict[str, Any]) -> list[dict[str, Any]]:
    """
    将 OCR API 输出的 JSON 格式转换为 VLM 输出的 UI 元素 JSON 格式。
    
    Args:
        ocr_result: 原始 OCR 返回的完整 JSON 字典。
        
    Returns:
        包含 VLM 格式元素的列表。
    """
    vlm_elements = []
    
    # 获取页数据，兼容可能为空的情况
    pages = ocr_result.get("result", {}).get("pages", [])
    
    for page_idx, page in enumerate(pages):
        lines = page.get("lines", [])
        
        for line_idx, line in enumerate(lines):
            text = line.get("text", "")
            position = line.get("position", [])
            
            # 确保 position 包含完整的 4 个点 (8 个坐标)
            if not position or len(position) != 8:
                continue
            
            # 分离 X 和 Y 坐标点
            # position 格式: [左上x, 左上y, 右上x, 右上y, 右下x, 右下y, 左下x, 左下y]
            x_coords = position[0::2]
            y_coords = position[1::2]
            
            # 计算正交外接矩形 (Bounding Box)
            x = min(x_coords)
            y = min(y_coords)
            w = max(x_coords) - x
            h = max(y_coords) - y
            
            # 构造目标 VLM 格式
            vlm_element = {
                # 自动生成具有唯一性的 name
                "name": f"page_{page_idx}_item_{line_idx}",
                "text": text,
                "bbox": {
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h
                },
                # OCR 无法直接提取字体样式，采用基于 bbox 和常规排版的推断与默认值
                "font_size_px": h,                  # 粗略使用文本框高度作为字体大小参考
                "font_family": "Microsoft YaHei",   # 默认字体
                "color": "#000000",                 # 默认黑色
                "bold": False,
                "italic": False,
                "align": "center",
                "z_index": 99                 # 使用行号作为堆叠层级参考
            }
            
            vlm_elements.append(vlm_element)
            
    return vlm_elements





# 使用示例 —— 与 PowerShell 版本等价：
# Invoke-RestMethod -Uri "http://192.168.210.128:50623/ai/service/v2/recognize/multipage"
#                   -Method Post
#                   -InFile "图片.png"
#                   -ContentType "application/octet-stream"
#                   -OutFile "50623-手写体文字.json"
if __name__ == "__main__":
    engine = OCREngine()
    engine.recognize_to_file("图片.png", "50623-手写体文字.json")
    