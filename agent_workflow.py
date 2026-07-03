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
from source.qa_agent import run_qa_reflection_loop
from source.imagegen import ImageGenConfig, generate_image, safe_filename
from source.openai_client import OpenAICompatClient
from source.prompts import (
    ANALYSIS_PROMPT,
    COMPONENT_PLAN_PROMPT,
    MANIFEST_PROMPT,
    PROCESS_NOTES_TEMPLATE,
    SYSTEM_PROMPT,
    ANALYSIS_PROMPT_TEXT,
    ANALYSIS_PROMPT_OBJECTS,
    ANALYSIS_PROMPT_LAYOUT,
    ANALYSIS_PROMPT_TYPOGRAPHY,
)
from source.tools import build_vision_report, init_project, parse_llm_json, verify_pptx, write_process_notes, convert_analysis_bboxes, save_bg_removed_image, validate_and_fix_component_plan, align_image_to_ppt
from source.image2pptx import build_pptx

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


def build_client(base_url: str | None) -> OpenAICompatClient:
    return OpenAICompatClient(base_url=base_url or "")


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
                {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
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
    temperature: float,
    source_path: str,
    image_path: Path,
    notes: str | None,
    seperate_analysis: bool = False,
    use_ocr: bool = False,
) -> dict[str, Any]:
    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    with Image.open(image_path) as img:
        img_w, img_h = img.size
    print(f"Source image dimensions: {img_w}x{img_h}")
    image_url = encode_image_to_data_url(image_path)
    if seperate_analysis:
        # ==========================================
        # PASS 0: 宏观排版与结构分析 (Macro Layout)
        # ==========================================
        print("Running Analysis Pass 0: Analyzing Macro Layout...")
        layout_prompt = ANALYSIS_PROMPT_LAYOUT.format(
            source_path=source_path,
            width=img_w,
            height=img_h
        )
        response_text_pass0 = client.chat(build_vision_messages(layout_prompt, image_url), temperature=0.2, response_format={'type': 'json_object'})
        layout_payload = parse_llm_json(response_text_pass0)

        # 提取排版摘要作为后续上下文
        layout_context_summary = json.dumps(layout_payload, ensure_ascii=False)
        print(f"Layout detected: {layout_payload.get('layout_type', 'Unknown')}")
        # ==========================================
        # PASS 1: 提取文字与基础排版 (Text & Typography)
        # ==========================================
        if use_ocr:
            # ==========================================
            # PASS 1 (OCR): 使用本地 OCR 提取绝对精确的文字和坐标
            # ==========================================
            print("Running Analysis Pass 1 (OCR): Extracting Text via Local OCR...")
            from source.ocr import OCREngine, convert_ocr_to_vlm_format

            ocr_result = OCREngine().recognize(image_path)
            vlm_elements = convert_ocr_to_vlm_format(ocr_result)

            # 初始拆分（基于 OCR 可能粗略计算的 font_size）
            titles = [e for e in vlm_elements if e.get("font_size_px", 0) >= 24]
            body_text = [e for e in vlm_elements if e.get("font_size_px", 0) < 24]

            # 构造传递给 VLM 的纯净上下文（只给 text 和 bbox，不给 OCR 猜错的颜色等）
            text_only_context = json.dumps({
                "titles": [{"text": t.get("text"), "bbox": t.get("bbox")} for t in titles],
                "body_text": [{"text": b.get("text"), "bbox": b.get("bbox")} for b in body_text]
            }, ensure_ascii=False)

            # ==========================================
            # PASS 1.5 (VLM): 专职分析文字样式 (颜色、准确字号、对齐)
            # ==========================================
            print("Running Analysis Pass 1.5: Analyzing Typography Styles via VLM...")
            typography_prompt = ANALYSIS_PROMPT_TYPOGRAPHY.format(
                source_path=source_path,
                text_context=text_only_context
            )
            
            response_text_pass1_5 = client.chat(
                build_vision_messages(typography_prompt, image_url),
                temperature=0.1,
                # preserve_thinking=True,
                top_p=0.05
            )
            typography_payload = parse_llm_json(response_text_pass1_5)

            # 💡 缝合数据：将 VLM 提取的颜色和大小，合并回 OCR 的高精度元素中
            def merge_typography(ocr_list, vlm_style_list):
                for i, base_item in enumerate(ocr_list):
                    if i < len(vlm_style_list):
                        style_item = vlm_style_list[i]
                        for key, value in style_item.items():
                            # 绝对防御：禁止 VLM 覆盖 OCR 提取的精准文字和坐标
                            if key not in ["bbox", "text"]: 
                                base_item[key] = value
                return ocr_list

            titles = merge_typography(titles, typography_payload.get("titles", []))
            body_text = merge_typography(body_text, typography_payload.get("body_text", []))

            # 重新组装完整的 text_payload
            text_payload = {
                "canvas_width": img_w,
                "canvas_height": img_h,
                "titles": titles,
                "body_text": body_text,
            }
        else:
            # --- VLM 路径：使用视觉模型提取文字 ---
            print("Running Analysis Pass 1: Extracting Text and Typography...")
            text_prompt = ANALYSIS_PROMPT_TEXT.format(
                source_path=source_path,
                width=img_w,
                height=img_h,
                notes=notes or "none",
            )

            response_text_pass1 = client.chat(build_vision_messages(text_prompt, image_url), temperature, response_format={'type': 'json_object'})
            text_payload = parse_llm_json(response_text_pass1)

        # 提取文字摘要，用于 Pass 2 的上下文感知
        text_context_summary = {
            "titles_bbox": [t.get("bbox") for t in text_payload.get("titles", [])],
            "body_text_bbox": [b.get("bbox") for b in text_payload.get("body_text", [])]
        }
    
        # ==========================================
        # PASS 2: 提取图形与视觉对象 (Shapes & Objects)
        # ==========================================
        print("Running Analysis Pass 2: Extracting Shapes and Graphics...")
        object_prompt = ANALYSIS_PROMPT_OBJECTS.format(
            source_path=source_path,
            width=img_w,
            height=img_h,
            notes=notes or "none",
            layout_context=layout_context_summary,
            text_context=json.dumps(text_context_summary) # 将第一步的坐标喂给第二步
        )
        
        response_text_pass2 = client.chat(build_vision_messages(object_prompt, image_url), temperature, response_format={'type': 'json_object'})
        object_payload = parse_llm_json(response_text_pass2)
    
        # ==========================================
        # PASS 3: 合并 (Merge)
        # ==========================================
        print("Merging Analysis Passes...")
        merged_payload = {
            "canvas_width": text_payload.get("canvas_width", img_w),
            "canvas_height": text_payload.get("canvas_height", img_h),
            "layout_meta": layout_payload, 
            # 来自 Pass 1
            "titles": text_payload.get("titles", []),
            "body_text": text_payload.get("body_text", []),
            # 来自 Pass 2
            "background": object_payload.get("background", {}),
            "shapes": object_payload.get("shapes", []),
            "objects": object_payload.get("objects", [])
        }
    
        # 可选: payload = convert_analysis_bboxes(merged_payload)
    
        return merged_payload

    analysis_text = ANALYSIS_PROMPT.format(
        source_path=source_path,
        width=img_w,
        height=img_h,
        notes=notes or "none",
    )
    image_url = encode_image_to_data_url(image_path)
    response_text = client.chat(build_vision_messages(analysis_text, image_url), temperature)
    # if raw_output_path:
    #     raw_output_path.write_text(response_text, encoding="utf-8")
    payload = parse_llm_json(response_text)

    # payload = convert_analysis_bboxes(payload)

    return payload

@retry_llm_call(max_retries=2)
def generate_component_plan(
    client: OpenAICompatClient,
    temperature: float,
    analysis: dict[str, Any],
    image_path: Path,
) -> dict[str, Any]:
    
# 1. 提取全局背景信息（新增逻辑）
    bg_data = analysis.get("background", {})
    bg_type = bg_data.get("type", "color")
    # 获取背景的颜色、渐变或图片线索
    bg_hints = bg_data.get("color") or bg_data.get("gradient") or bg_data.get("image") or "unknown background"
    global_bg_context = f"Type: {bg_type}, Style/Color Hints: {bg_hints}"
    
    # 2. 过滤需要生成图片的元素
    items_need_prompt = []
    if bg_type == "image":
        items_need_prompt.append({
            "name": "Background Image",
            "type": "image",
            "bbox": bg_data.get("bbox")
        })
        
    for obj in analysis.get("objects", []):
        if obj.get("needs_image"):
            items_need_prompt.append({
                "name": obj.get("name"),
                "type": obj.get("type"),
                "bbox": obj.get("bbox")})
    expected_count = len(items_need_prompt)    
    print(f"Component plan will include {expected_count} items that need images.")
    #保存分析结果中需要生成图片的元素，供后续检查使用
    save_json(Path("diagnostics") / "items_need_prompt.json", {"items": items_need_prompt})
    # 2. 组装 Prompt
    prompt_text = COMPONENT_PLAN_PROMPT.replace(
        "{filtered_json}", json.dumps(items_need_prompt, indent=2)
    ).replace(
        "{global_background}", global_bg_context
    )

    # 3. 将原图转为 base64 数据
    image_url = encode_image_to_data_url(image_path)
    
    # 4. 关键修改：使用 build_vision_messages 发送视觉分析请求
    response_text = client.chat(build_vision_messages(prompt_text, image_url), temperature, response_format={'type': 'json_object'})

    payload = parse_llm_json(response_text)
    generated_assets = payload.get("assets", [])
    if expected_count > 0 and len(generated_assets) < expected_count*0.8:
        raise ValueError(f"AI generated {len(generated_assets)} assets, but {expected_count} were expected.")
    return payload

@retry_llm_call(max_retries=2)
def generate_manifest(
    client: OpenAICompatClient,
    temperature: float,
    analysis: dict[str, Any],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt_text = MANIFEST_PROMPT.replace(
        "{analysis_json}", json.dumps(analysis, indent=2)
    ).replace(
        "{asset_json}", json.dumps(assets, indent=2)
    )
    response_text = client.chat(build_text_messages(prompt_text), temperature)
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
            # [修改]: 强制限制图像/图标的 Z-index 在 50-89 之间
            z_index = obj.get("z_index", 50)
            z_index = max(50, min(89, z_index)) # 强制收敛到区间
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
    parser.add_argument("--no_redraw", action="store_true", help="crop from source instead of imagegen")
    parser.add_argument("--skip-verify", action="store_true", help="skip pptx verification")
    parser.add_argument("--vision_base_url", help="override vision base url")
    parser.add_argument("--imagegen_base_url", help="override imagegen base url")
    parser.add_argument(
        "--resume_analysis",
        help="project folder name under langchain/projects to reuse diagnostics",
    )
    parser.add_argument(
        "--resume_imagegen",
        help="project folder name under langchain/projects to reuse assets and resume from manifest generation",
    )
    parser.add_argument(
        "--remove_bg", action="store_true",
        help="remove background from generated component images using rembg. If --resume_imagegen is used, will attempt to remove bg from existing assets in the project folder.",
    )
    parser.add_argument(
        "--seperate_analysis", action="store_true",
        help="generate analysis separately from image.",
    )
    parser.add_argument(
        "--vision_temperature", type=float, default=0.4, help="temperature for vision model"
    )
    parser.add_argument(
        "--ocr", action="store_true",
        help="use local OCR for text extraction (requires --seperate_analysis)",
    )
    parser.add_argument("--resize_input", action="store_true", help="resize image input")
    parser.add_argument("--qa_loop", action="store_true", help="run QA loop for manifest refinement")
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

    if resume_project:
        project_dir = PROJECTS_ROOT / resume_project
        if not project_dir.exists():
            raise FileNotFoundError(f"project not found: {project_dir}")
        project_info = {
            "project_dir": str(project_dir),
            "sources": [args.source],
        }
    else:
        slug = "image2ppt_local"
        if args.test_vision:
            slug = "image2ppt_test_vision"
        if args.no_redraw:
            slug = "image2ppt_no_redraw"
        project_info = init_project(PROJECTS_ROOT, slug, [args.source], args.date)
        project_dir = Path(project_info["project_dir"])

    if args.resize_input:
        # 设定标准的 PPT 尺寸
        PPT_WIDTH = 1920
        PPT_HEIGHT = 1080
        # 1. 执行输入端的对齐处理
        standardized_source_path = project_dir / "standardized_input.png"
        align_image_to_ppt(
            source_path=Path(args.source), 
            output_path=standardized_source_path,
            target_w=PPT_WIDTH,
            target_h=PPT_HEIGHT,
            bg_color="#FFFFFF" # 默认白底，也可以通过 args 传入
        )
        print(f"Input image standardized to {PPT_WIDTH}x{PPT_HEIGHT}")
    else:
        standardized_source_path = Path(args.source)
    manifest_path = project_dir / "manifest.json"
    diagnostics_dir = project_dir / "diagnostics"
    vision_base_url = args.vision_base_url 
    vision_temperature = args.vision_temperature 
    vision_client = build_client(vision_base_url)
    print(f"Vision client ready: {vision_base_url}")
    if args.resume_imagegen:
        analysis = load_json_file(diagnostics_dir / "analysis.json")
        asset_catalog = load_json_file(diagnostics_dir / "asset_catalog.json")
        asset_records = asset_catalog.get("assets") or []
        if not asset_records:
            raise ValueError("asset_catalog.json contains no assets; cannot resume_imagegen")
        print("Analysis loaded: diagnostics/analysis.json")
        print(f"Asset catalog loaded: {len(asset_records)} assets")
        if args.remove_bg:
            original_component_dir = project_dir / "original_component_images"
            original_component_dir.mkdir(parents=True, exist_ok=True)
            component_dir = project_dir / "component_images"
            save_bg_removed_image(component_dir, original_component_dir)
        manifest = generate_manifest_python(
                # vision_client,
                # vision_model,
                # vision_temperature,
                analysis,
                asset_records,
                # raw_output_path=diagnostics_dir / "manifest_raw.txt",
            )
        canvas_w = int(analysis.get("canvas_width", 0) or 0)
        canvas_h = int(analysis.get("canvas_height", 0) or 0)
        if canvas_w and canvas_h:
            ensure_deck(manifest, canvas_w, canvas_h)
        if args.qa_loop:
            manifest = run_qa_reflection_loop(
                manifest=manifest,
                source_image_path=Path(args.source),
                project_dir=project_dir,
                vision_client=vision_client
            )
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
        if args.seperate_analysis:
            analysis = generate_analysis(
                vision_client,
                vision_temperature,
                str(standardized_source_path),
                standardized_source_path,
                args.notes,
                seperate_analysis=True,
                use_ocr=args.ocr,
            )
        else:
            analysis = generate_analysis(
                vision_client,
                vision_temperature,
                str(standardized_source_path), 
                standardized_source_path,
                args.notes,
            )
        save_json(diagnostics_dir / "analysis.json", analysis)
        print("Analysis complete: diagnostics/analysis.json")
        component_plan = generate_component_plan(
            vision_client,
            vision_temperature,
            analysis,
            Path(args.source),
        )
        # 👇 插入这行校验修复逻辑
        component_plan = validate_and_fix_component_plan(analysis, component_plan)
        save_json(diagnostics_dir / "component_plan.json", component_plan)
        assets = component_plan.get("assets") or []
        print(f"Component plan ready: {len(assets)} assets")
    if args.test_vision:
        report = build_vision_report(analysis, component_plan, vision_base_url or "local")
        report_path = diagnostics_dir / "vision_report.json"
        save_json(report_path, report)
        print(f"Vision report written: {report_path}")
        return 0
    if not args.resume_imagegen:
        asset_records: list[dict[str, Any]] = []
        source_image = None
        imagegen_base_url = ""
        if args.no_redraw:
            source_image = Image.open(args.source)
            print(f"Source image loaded for cropping: {args.source}")
        else:
            imagegen_base_url = args.imagegen_base_url or os.getenv("IMAGE2PPT_IMAGEGEN_BASE_URL")
            imagegen_size = os.getenv("IMAGE2PPT_IMAGEGEN_SIZE", "1024x1024")
            imagegen_config = ImageGenConfig(
                base_url=imagegen_base_url or "",
                model="local",
                size=imagegen_size,
            )
            print(f"Imagegen ready: {imagegen_base_url}")
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
            if args.no_redraw:
                # crop_from_source(source_image, bbox, output_path)
                # print(f"Asset cropped: {output_path}")
                continue
            else:
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
            if args.remove_bg:
                original_component_dir = project_dir / "original_component_images"
                original_component_dir.mkdir(parents=True, exist_ok=True)
                save_bg_removed_image(component_dir, original_component_dir)

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
            if args.qa_loop:
                manifest = run_qa_reflection_loop(
                manifest=manifest,
                source_image_path=Path(args.source),
                project_dir=project_dir,
                vision_client=vision_client
            )
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Manifest generated: manifest.json")
    build_pptx(manifest_path, project_dir / "output.pptx", project_dir / "summary.json")
    print("PPTX build complete")

    verify_result = {}
    if not args.skip_verify:
        verify_result = verify_pptx(project_dir / "output.pptx")

    notes = PROCESS_NOTES_TEMPLATE.format(
        mode="local",
        sources=project_info.get("sources"),
        vision_model=vision_base_url or "local",
        component_model=vision_base_url or "local",
        imagegen_model=args.imagegen_base_url if not args.no_redraw else "no_redraw",
        no_redraw=args.no_redraw,
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
