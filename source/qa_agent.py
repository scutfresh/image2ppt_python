import json
import base64
import mimetypes
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw

# JSON 安全解析器
try:
    from tools import parse_llm_json
except ImportError:
    import re
    def parse_llm_json(raw_text: str) -> dict:
        cleaned = re.sub(r'^```json\s*', '', raw_text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r'^```\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        match = re.search(r'(\{.*\})', cleaned.strip(), re.DOTALL)
        return json.loads(match.group(1)) if match else json.loads(cleaned)

# ==========================================
# 1. 优化版 QA Prompt：在源头上锁定文字，只调图形
# ==========================================
ANALYSIS_PROMPT_QA_REFLECTION = """
You are an expert Art Director. We are refining a presentation slide layout.
I will provide TWO images:
1. The Original Source Image (Target design).
2. The Wireframe Mockup (Current positions. Text boxes are GREEN, Shapes/Images are BLUE/ORANGE).

CURRENT LAYOUT JSON (Ground Truth):
{manifest_context}

CRITICAL RULES FOR ART DIRECTOR:
1. TEXT LOCKED (GROUND TRUTH): All GREEN text boxes have 100% PERFECT coordinates extracted via an ultra-precise hardware OCR engine. DO NOT propose any adjustments (delta) for text elements. 
2. SHAPE/IMAGE ADAPTATION: Your ONLY task is to look at the BLUE/ORANGE boxes (Shapes, Container Cards, Icons, Images) and adjust their positions/sizes so that they perfectly align with, support, or encapsulate the GREEN text boxes as seen in the original image.
3. If a container shape is too narrow or shifted, calculating the correct delta to move or expand it so the text fits comfortably inside with proper padding.

Provide relative deltas for SHAPES and IMAGES only:
- Negative 'delta_x' moves left, positive moves right.
- Negative 'delta_y' moves up, positive moves down.
- Output 0 if no adjustment is needed.

Required Output Format Structure:
{{
  "adjustments": [
    {{
      "element_id": "ID_5", // Must ONLY be the ID of a shape or image element
      "reasoning": "The background container card ID_5 needs to expand rightwards by 60px to fully contain its OCR text.",
      "delta_x": 0,
      "delta_y": 0,
      "delta_w": 60,
      "delta_h": 0
    }}
  ]
}}
""".strip()

# ==========================================
# 2. 草图渲染器（保持直观的颜色区隔）
# ==========================================
def render_manifest_preview(manifest: dict, output_path: Path) -> Path:
    w = manifest.get("slide_width", 1920)
    h = manifest.get("slide_height", 1080)
    
    img = Image.new("RGB", (w, h), color="#1E1E1E")
    draw = ImageDraw.Draw(img, "RGBA")
    
    # 绘制坐标网格
    for x in range(0, w, 100):
        color = "#555555" if x % 500 == 0 else "#333333"
        draw.line([(x, 0), (x, h)], fill=color, width=2 if x % 500 == 0 else 1)
        if x % 200 == 0: draw.text((x + 2, 2), str(x), fill="#888888")
            
    for y in range(0, h, 100):
        color = "#555555" if y % 500 == 0 else "#333333"
        draw.line([(0, y), (w, y)], fill=color, width=2 if y % 500 == 0 else 1)
        if y % 200 == 0: draw.text((2, y + 2), str(y), fill="#888888")
    
    for el in manifest.get("elements", []):
        qa_id = el.get("_qa_id", "ID_?") 
        bbox = el.get("bbox")
        if not bbox: continue
        
        x, y, ew, eh = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)
        
        # 绿色代表无可撼动的 OCR 纯文本
        if el["type"] == "text":
            draw.rectangle([x, y, x+ew, y+eh], fill=(0, 255, 0, 30), outline="#00FF00", width=2)
            draw.rectangle([x, y, x+40, y+15], fill="#000000")
            draw.text((x+2, y+2), qa_id, fill="#00FF00")
        # 蓝色/橙色代表可以动态调整移动的图形与视觉组件
        elif el["type"] in ["shape", "image"]: 
            draw.rectangle([x, y, x+ew, y+eh], fill=(0, 150, 255, 40), outline="#00A0FF", width=2)
            draw.rectangle([x, y, x+40, y+15], fill="#000000")
            draw.text((x+2, y+2), qa_id, fill="#00A0FF")
            
    img.save(output_path)
    return output_path

def _encode_image(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"

# ==========================================
# 3. 主执行模块：代码层强力拦截机制
# ==========================================
def run_qa_reflection_loop(
    manifest: dict, 
    source_image_path: Path, 
    project_dir: Path, 
    vision_client: Any, 
    temperature: float = 0.01
) -> dict:
    print("\n🔍 Initiating Visual QA Reflection Loop...")
    
    qa_dir = project_dir / "diagnostics"
    qa_dir.mkdir(parents=True, exist_ok=True)
    preview_path = qa_dir / "qa_preview.png"
    
    # 前置显式注入临时通信短 ID
    for i, el in enumerate(manifest.get("elements", [])):
        el["_qa_id"] = f"ID_{i}"
    
    # 1. 渲染草图
    render_manifest_preview(manifest, preview_path)
    print(f"   [+] Rendered ID-anchored mockup preview to {preview_path.name}")
    
    source_url = _encode_image(source_image_path)
    preview_url = _encode_image(preview_path)
    
    # 2. 提取精简的真理 JSON 传给模型
    qa_context_elements = []
    for el in manifest.get("elements", []):
        if "_qa_id" in el:
            qa_context_elements.append({
                "element_id": el["_qa_id"],
                "type": el.get("type"),
                "name": el.get("name"),
                "bbox": el.get("bbox")
            })
    manifest_context_str = json.dumps(qa_context_elements, ensure_ascii=False, indent=2)
    
    # 3. 格式化提示词并组装请求
    qa_prompt_text = ANALYSIS_PROMPT_QA_REFLECTION.format(
        manifest_context=manifest_context_str
    )
    
    qa_messages = [
        {"role": "system", "content": "You are a precise JSON-only extraction engine."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": qa_prompt_text},
                {"type": "image_url", "image_url": {"url": source_url, "detail": "high"}},
                {"type": "image_url", "image_url": {"url": preview_url, "detail": "high"}},
            ],
        },
    ]
    
    print("   [+] Asking Art Director (VLM) for layout alignments...")
    try:
        response_qa = vision_client.chat(qa_messages, temperature=temperature, response_format={'type': 'json_object'})
        qa_payload = parse_llm_json(response_qa)
        
        qa_json_path = qa_dir / "qa_adjustments.json"
        qa_json_path.write_text(json.dumps(qa_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"   [+] Saved middle QA payload to {qa_json_path.relative_to(project_dir.parent)}")

    except Exception as e:
        print(f"   [!] QA Loop failed: {e}. Skipping adjustments.")
        return manifest
        
    adjustments = qa_payload.get("adjustments", [])
    if not adjustments:
        print("   [+] VLM reported no adjustments needed.")
        for el in manifest.get("elements", []):
            el.pop("_qa_id", None)
        return manifest
        
    print(f"   [+] Applying valid adjustments...")
    
    # 4. 精确匹配与类型安全过滤
    element_map = {el["_qa_id"]: el for el in manifest.get("elements", []) if "_qa_id" in el}
    
    applied_count = 0
    for adj in adjustments:
        target_id = adj.get("element_id")
        if target_id in element_map:
            el = element_map[target_id]
            
            # 💡 【核心修改：黄金卫语句】强行拦截并屏蔽任何针对 text 类型的坐标篡改
            if el.get("type") == "text":
                print(f"       -> [🔒 锁定拦截] 拒绝修改文字元素 [{target_id}] ({el.get('name')[:10]})。OCR 坐标已强制固化。")
                continue
                
            if "bbox" in el:
                # 只有 shape 和 image 类型能走到这里被真正执行 delta 计算
                el["bbox"]["x"] += int(adj.get("delta_x", 0))
                el["bbox"]["y"] += int(adj.get("delta_y", 0))
                el["bbox"]["w"] += int(adj.get("delta_w", 0))
                el["bbox"]["h"] += int(adj.get("delta_h", 0))
                
                el["bbox"]["w"] = max(10, el["bbox"]["w"])
                el["bbox"]["h"] = max(10, el["bbox"]["h"])
                
                print(f"       -> [🔧 已调整] 视觉元素 [{target_id}] ({el.get('name')[:10]}): {adj.get('reasoning')}")
                applied_count += 1

    print(f"   [+] Successfully applied {applied_count} shape/image adjustments. Text elements remained untouched.")
    
    # 5. 清理内存临时标记
    for el in manifest.get("elements", []):
        el.pop("_qa_id", None)

    return manifest