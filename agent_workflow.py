from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
import time                  
from functools import wraps
from PIL import Image

from imagegen import ImageGenConfig, generate_image, safe_filename
from openai_client import OpenAICompatClient
from prompts import (
    ANALYSIS_PROMPT,
    COMPONENT_PLAN_PROMPT,
    MANIFEST_PROMPT,
    PROCESS_NOTES_TEMPLATE,
    SYSTEM_PROMPT,
)
from tools import build_vision_report, init_project, parse_llm_json, verify_pptx, write_process_notes
from image2pptx import build_pptx

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "bggg-creator-image2ppt"
PROJECTS_ROOT = Path(__file__).resolve().parent / "projects"

def retry_llm_call(max_retries=3, delay=2):
    """
    用于拦截 LLM 调用的重试装饰器。
    当遇到 JSON 解析失败时，自动重新发起请求。
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    # 尝试执行原函数
                    return func(*args, **kwargs)
                except (ValueError, json.JSONDecodeError) as e:
                    if attempt == max_retries - 1:
                        print(f"\n❌ [彻底失败] 连续 {max_retries} 次无法生成合法的 JSON，放弃重试。")
                        raise  # 最后一次仍然失败，把报错抛出终止程序
                    print(f"\n⚠️ [触发重试] 模型输出了损坏的 JSON ({e})。正在进行第 {attempt + 1}/{max_retries} 次重试...")
                    time.sleep(delay)
        return wrapper
    return decorator

def encode_image_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def build_client(base_url: str | None, api_key: str | None) -> OpenAICompatClient:
    return OpenAICompatClient(base_url=base_url or "", api_key=api_key)


def build_text_messages(prompt: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def build_vision_messages(prompt: str, image_url: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]


def list_assets(assets_dir: Path) -> list[str]:
    if not assets_dir.exists():
        return []
    return sorted([item.name for item in assets_dir.iterdir() if item.is_file()])


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

@retry_llm_call(max_retries=2)
def generate_analysis(
    client: OpenAICompatClient,
    model: str,
    temperature: float,
    source_path: str,
    image_path: Path,
    notes: str | None,
    # raw_output_path: Path | None = None,
) -> dict[str, Any]:
    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    with Image.open(image_path) as img:
        img_w, img_h = img.size
    print(f"Source image dimensions: {img_w}x{img_h}")

    analysis_text = ANALYSIS_PROMPT.format(
        source_path=source_path,
        width=img_w,
        height=img_h,
        notes=notes or "none",
    )
    image_url = encode_image_to_data_url(image_path)
    response_text = client.chat(model, build_vision_messages(analysis_text, image_url), temperature)
    # if raw_output_path:
    #     raw_output_path.write_text(response_text, encoding="utf-8")
    payload = parse_llm_json(response_text)
    return payload

@retry_llm_call(max_retries=2)
def generate_component_plan(
    client: OpenAICompatClient,
    model: str,
    temperature: float,
    analysis: dict[str, Any],
    image_path: Path, # 新增参数：接收原图路径
    # raw_output_path: Path | None = None,
) -> dict[str, Any]:
    
# 1. 构建精简版的输入列表，大幅缩减 Token，防止截断
    items_need_prompt = []
    
    # 加入背景（如果是图片）
    if analysis.get("background", {}).get("type") == "image":
        bg = analysis["background"]
        items_need_prompt.append({
            "name": "Background Image",
            "type": bg.get("type"),
            "bbox": bg.get("bbox"),
            "style_tags": bg.get("image_hints", "background texture")
        })
        
    # 加入所有 needs_image 为 true 的对象
    for obj in analysis.get("objects", []):
        if obj.get("needs_image"):
            items_need_prompt.append({
                "name": obj.get("name"),
                "type": obj.get("type"),
                "bbox": obj.get("bbox"),
                "style_tags": obj.get("style_tags", "") # 接收第一步打的标签
            })
            
    expected_count = len(items_need_prompt)    
    print(f"Component plan will include {expected_count} items that need images.")
    # 2. 组装 Prompt
    prompt_text = COMPONENT_PLAN_PROMPT.replace(
        "{filtered_json}", json.dumps(items_need_prompt, indent=2)
    )
    # prompt_text = COMPONENT_PLAN_PROMPT.replace(
    #     "{analysis_json}", json.dumps(analysis, indent=2)
    # )

    # 3. 将原图转为 base64 数据
    image_url = encode_image_to_data_url(image_path)
    
    # 4. 关键修改：使用 build_vision_messages 发送视觉分析请求
    response_text = client.chat(model, build_vision_messages(prompt_text, image_url), temperature)

    # response_text = client.chat(model, build_text_messages(prompt_text), temperature)
    # if raw_output_path:
    #     raw_output_path.write_text(response_text, encoding="utf-8")
    payload = parse_llm_json(response_text)
    generated_assets = payload.get("assets", [])
    if expected_count > 0 and len(generated_assets) < expected_count*0.8:
        raise ValueError(f"AI generated {len(generated_assets)} assets, but {expected_count} were expected.")
    return payload

@retry_llm_call(max_retries=2)
def generate_manifest(
    client: OpenAICompatClient,
    model: str,
    temperature: float,
    analysis: dict[str, Any],
    assets: list[dict[str, Any]],
    # raw_output_path: Path | None = None,
) -> dict[str, Any]:
    prompt_text = MANIFEST_PROMPT.replace(
        "{analysis_json}", json.dumps(analysis, indent=2)
    ).replace(
        "{asset_json}", json.dumps(assets, indent=2)
    )
    response_text = client.chat(model, build_text_messages(prompt_text), temperature)
    # if raw_output_path:
    #     raw_output_path.write_text(response_text, encoding="utf-8")
    manifest = parse_llm_json(response_text)
    return manifest
def generate_manifest_python(analysis: dict, assets: list) -> dict:
    elements = []
    
    # 1. 建立资产映射表 (通过 name 快速查找对应的文件路径)
    asset_map = {item["name"]: item["file"] for item in assets if "name" in item and "file" in item}

    # 2. 处理 Background
    bg = analysis.get("background", {})
    if bg:
        bg_element = {
            "type": "image" if bg.get("type") == "image" else "shape",
            "name": "background",
            "bbox": bg.get("bbox", {"x": 0, "y": 0, "w": analysis.get("canvas_width"), "h": analysis.get("canvas_height")}),
            "z_index": -999 # 确保背景在最底层
        }
        if bg.get("type") == "image":
            # 如果背景是图片，从资产中匹配
            bg_element["file"] = asset_map.get("Background Image") or asset_map.get("background")
        else:
            bg_element["shape_type"] = "rect"
            bg_element["fill"] = bg.get("color") or bg.get("fill")
        elements.append(bg_element)

    # 3. 处理 Shapes
    for shape in analysis.get("shapes", []):
        elements.append({
            "type": "shape",
            "shape_type": shape.get("type", "rect"),
            "name": shape.get("name", "shape"),
            "bbox": shape.get("bbox"),
            "fill": shape.get("fill", "none"),
            "stroke": shape.get("stroke", "none"),
            "stroke_width_px": shape.get("stroke_width_px", 1),
            "z_index": shape.get("z_index", 0)
        })

    # 4. 处理 Objects (需要图片的视觉元素)
    for obj in analysis.get("objects", []):
        if obj.get("needs_image"):
            elements.append({
                "type": "image",
                "name": obj.get("name"),
                "file": asset_map.get(obj.get("name")), # 从刚才生成的资源中读取路径
                "bbox": obj.get("bbox"),
                "z_index": obj.get("z_index", 0)
            })

    # 5. 处理 Text (titles & body_text)
    for text_type in ["titles", "body_text"]:
        for text_block in analysis.get(text_type, []):
            elements.append({
                "type": "text",
                "name": text_block.get("name", text_type),
                "text": text_block.get("text", ""),
                "bbox": text_block.get("bbox"),
                "font_family": text_block.get("font_family", "Microsoft YaHei"),
                "font_size_px": text_block.get("font_size_px", 16),
                "color": text_block.get("color", "#000000"),
                "bold": text_block.get("bold", False),
                "italic": text_block.get("italic", False),
                "align": text_block.get("align", "left"),
                "z_index": text_block.get("z_index", 100) # 文字通常在较上层
            })

    # 6. 按照 z_index 从后到前排序
    elements.sort(key=lambda e: e.get("z_index", 0))

    # 7. 组装最终的 Manifest
    canvas_w = analysis.get("canvas_width", 1920)
    canvas_h = analysis.get("canvas_height", 1080)
    
    manifest = {
        "slide_width": canvas_w,
        "slide_height": canvas_h,
        "elements": elements,
        "deck": {
            "canvas_width": canvas_w,
            "canvas_height": canvas_h,
            "slide_width_in": 13.333,
            "name": "Image2PPT Deck"
        }
    }
    
    return manifest

def ensure_deck(manifest: dict[str, Any], canvas_w: int, canvas_h: int) -> None:
    deck = manifest.setdefault("deck", {})
    deck.setdefault("canvas_width", canvas_w)
    deck.setdefault("canvas_height", canvas_h)
    deck.setdefault("slide_width_in", 13.333)
    if "slide_height_in" not in deck:
        deck["slide_height_in"] = round(13.333 * float(canvas_h) / float(canvas_w), 3)
    deck.setdefault("name", "Image2PPT Deck")


def normalize_bbox(item: dict[str, Any]) -> tuple[int, int, int, int]:
    bbox = item.get("bbox") or {}
    return (
        int(bbox.get("x", 0)),
        int(bbox.get("y", 0)),
        int(bbox.get("w", 0)),
        int(bbox.get("h", 0)),
    )


def crop_from_source(source_img: Image.Image, bbox: tuple[int, int, int, int], output_path: Path) -> Path:
    x, y, w, h = bbox
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop = source_img.crop((x, y, x + w, y + h))
    crop.save(output_path, format="PNG")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the image2ppt OpenAI-compatible workflow (bitmap).")
    parser.add_argument("--source", required=True, help="input image file")
    parser.add_argument("--date", help="YYYYMMDD override")
    parser.add_argument("--notes", help="extra analysis notes")
    parser.add_argument("--resume_manifest", help="use existing manifest.json instead of LLM")
    parser.add_argument(
        "--test_vision",
        action="store_true",
        help="only run vision analysis and component plan, then emit a report",
    )
    parser.add_argument(
        "--analysis_temperature",
        type=float,
        default=0.4,
        help="temperature for analysis (default: 0.2)",
    )
    parser.add_argument(
        "--component_temperature",
        type=float,
        default=0.3,
        help="temperature for component plan and manifest (default: 0.2)",
    )
    parser.add_argument("--skip-verify", action="store_true", help="skip pptx verification")
    parser.add_argument("--vision-model", help="override vision model")
    parser.add_argument("--vision-base-url", help="override vision base url")
    parser.add_argument("--imagegen-model", help="override imagegen model")
    parser.add_argument("--imagegen-base-url", help="override imagegen base url")
    parser.add_argument("--imagegen-api-style",
        choices=["openai", "qwen"],
        default="openai",
        help="imagegen api style (openai or qwen)",
    )
    parser.add_argument(
        "--resume_analysis",
        help="project folder name under langchain/projects to reuse diagnostics",
    )
    parser.add_argument(
        "--resume_imagegen",
        help="project folder name under langchain/projects to reuse assets and resume from manifest generation",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    resume_flags = [args.resume_analysis, args.resume_imagegen, args.resume_manifest]
    if sum(bool(flag) for flag in resume_flags) > 1:
        raise ValueError("resume_analysis, resume_imagegen, resume_manifest cannot be used together")
    if args.test_vision and args.resume_imagegen:
        raise ValueError("test_vision cannot be used with --resume_imagegen")
    if args.test_vision and args.resume_manifest:
        raise ValueError("test_vision cannot be used with --resume_manifest")

    resume_project = args.resume_analysis or args.resume_imagegen or args.resume_manifest

    vision_model = args.vision_model or os.getenv("IMAGE2PPT_VISION_MODEL", "qwen-vl")
    imagegen_model = args.imagegen_model or os.getenv("IMAGE2PPT_IMAGEGEN_MODEL", "z-image-turbo")

    if resume_project:
        project_dir = PROJECTS_ROOT / resume_project
        if not project_dir.exists():
            raise FileNotFoundError(f"project not found: {project_dir}")
        project_info = {
            "project_dir": str(project_dir),
            "sources": [args.source],
        }
    else:
        slug = f"{vision_model}_and_{imagegen_model}"
        if args.test_vision:
            slug = f"{vision_model}_test_vision"
        project_info = init_project(PROJECTS_ROOT, slug, [args.source], args.date)
        project_dir = Path(project_info["project_dir"])
    manifest_path = project_dir / "manifest.json"
    diagnostics_dir = project_dir / "diagnostics"
    vision_base_url = args.vision_base_url or os.getenv("IMAGE2PPT_VISION_BASE_URL")
    vision_api_key = (
        os.getenv("IMAGE2PPT_VISION_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    analysis_temperature = float(args.analysis_temperature)
    component_temperature = float(args.component_temperature)
    vision_client = build_client(vision_base_url, vision_api_key)
    print(f"Vision client ready: {vision_model}")
    if args.resume_imagegen:
        analysis = load_json_file(diagnostics_dir / "analysis.json")
        asset_catalog = load_json_file(diagnostics_dir / "asset_catalog.json")
        asset_records = asset_catalog.get("assets") or []
        if not asset_records:
            raise ValueError("asset_catalog.json contains no assets; cannot resume_imagegen")
        print("Analysis loaded: diagnostics/analysis.json")
        print(f"Asset catalog loaded: {len(asset_records)} assets")
        manifest = generate_manifest(
            vision_client,
            vision_model,
            component_temperature,
            analysis,
            asset_records,
            # raw_output_path=diagnostics_dir / "manifest_raw.txt",
        )
        canvas_w = int(analysis.get("canvas_width", 0) or 0)
        canvas_h = int(analysis.get("canvas_height", 0) or 0)
        if canvas_w and canvas_h:
            ensure_deck(manifest, canvas_w, canvas_h)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("Manifest generated: manifest.json")
    elif args.resume_analysis:
        analysis = load_json_file(diagnostics_dir / "analysis.json")
        component_plan = load_json_file(diagnostics_dir / "component_plan.json")
        assets = component_plan.get("assets") or []
        print("Analysis loaded: diagnostics/analysis.json")
        print(f"Component plan loaded: {len(assets)} assets")
    elif args.resume_manifest:
        manifest_path = project_dir / "manifest.json"
        build_pptx(manifest_path, project_dir / "output.pptx", project_dir / "summary.json")
        print("PPTX build complete")
        return 0
    else:
        analysis = generate_analysis(
            vision_client,
            vision_model,
            analysis_temperature,
            args.source,
            Path(args.source),
            args.notes,
            # raw_output_path=diagnostics_dir / "analysis_raw.txt",
        )
        save_json(diagnostics_dir / "analysis.json", analysis)
        print("Analysis complete: diagnostics/analysis.json")
        component_plan = generate_component_plan(
            vision_client,
            vision_model,
            component_temperature,
            analysis,
            Path(args.source),  # 新增：传入原图路径
            # raw_output_path=diagnostics_dir / "component_plan_raw.txt",
        )
        save_json(diagnostics_dir / "component_plan.json", component_plan)
        assets = component_plan.get("assets") or []
        print(f"Component plan ready: {len(assets)} assets")
    if args.test_vision:
        report = build_vision_report(analysis, component_plan, vision_model)
        report_path = diagnostics_dir / f"vision_report_{vision_model}.json"
        save_json(report_path, report)
        print(f"Vision report written: {report_path}")
        return 0
    if not args.resume_imagegen:
        asset_records: list[dict[str, Any]] = []
        imagegen_base_url = args.imagegen_base_url or os.getenv("IMAGE2PPT_IMAGEGEN_BASE_URL")
        imagegen_api_key = (
            os.getenv("IMAGE2PPT_IMAGEGEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        imagegen_size = os.getenv("IMAGE2PPT_IMAGEGEN_SIZE", "1024x1024")
        imagegen_config = ImageGenConfig(
            base_url=imagegen_base_url or "",
            api_key=imagegen_api_key,
            model=imagegen_model,
            size=imagegen_size,
            api_style=args.imagegen_api_style,
        )
        print(f"Imagegen model loaded: {imagegen_model}")
        component_dir = project_dir / "component_images"
        for item in assets:
            name = str(item.get("name") or item.get("type") or "asset")
            bbox = normalize_bbox(item)
            x, y, w, h = bbox
            if w <= 0 or h <= 0:
                print(f"Skip asset with invalid size: {name} ({w}x{h})")
                continue
            filename = safe_filename(name, suffix=".png")
            output_path = component_dir / filename
            prompt = str(item.get("prompt") or "")
            negative_prompt = str(item.get("negative_prompt") or "") or None
            transparent = bool(item.get("transparent", False))
            request_size = f"{w}x{h}"
            generate_image(
                imagegen_config,
                prompt,
                negative_prompt,
                transparent,
                component_dir,
                name,
                output_path,
                request_size,
                None,
            )
            print(f"Image generated: {output_path}")
            asset_records.append(
                {
                    "name": name,
                    "type": item.get("type"),
                    "file": f"component_images/{filename}",
                    "bbox": {"x": x, "y": y, "w": w, "h": h},
                }
            )

            save_json(diagnostics_dir / "asset_catalog.json", {"assets": asset_records})
            print("Asset catalog written: diagnostics/asset_catalog.json")

            manifest = generate_manifest_python(
                # vision_client,
                # vision_model,
                # vision_temperature,
                analysis,
                asset_records,
                # raw_output_path=diagnostics_dir / "manifest_raw.txt",
            )
            # canvas_w = int(analysis.get("canvas_width", 0) or 0)
            # canvas_h = int(analysis.get("canvas_height", 0) or 0)
            # if canvas_w and canvas_h:
            #     ensure_deck(manifest, canvas_w, canvas_h)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print("Manifest generated: manifest.json")
    build_pptx(manifest_path, project_dir / "output.pptx", project_dir / "summary.json")
    print("PPTX build complete")

    verify_result = {}
    if not args.skip_verify:
        verify_result = verify_pptx(project_dir / "output.pptx")

    notes = PROCESS_NOTES_TEMPLATE.format(
        mode="bitmap",
        sources=project_info.get("sources"),
        vision_model=vision_model,
        manifest_model=vision_model,
        imagegen_model=imagegen_model,
        assets=list_assets(project_dir / "component_images"),
        notes=args.notes or "none",
    )
    if verify_result:
        notes += f"\nVerify: slides={verify_result['slides']}, shapes={verify_result['shapes']}\n"
    if args.resume_analysis:
        notes += f"\nResume analysis: {args.resume_analysis}\n"
    if args.resume_manifest:
        notes += f"\nResume manifest: {args.resume_manifest}\n"

    write_process_notes(project_dir / "process_notes.md", notes)
    print(json.dumps({"project_dir": str(project_dir), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
