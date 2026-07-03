from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 将 source 目录加入 sys.path，以便导入 source 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "source"))
try:
    from ocr import OCREngine  # noqa: E402
    from tools import align_image_to_ppt  # noqa: E402
    from image2pptx import build_pptx  # noqa: E402
except ImportError as e:
    print(f"错误: 模块导入失败，请检查路径。详细信息: {e}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR → VLM JSON → PPTX 端到端测试")
    parser.add_argument("image", type=str, help="输入图片路径")
    parser.add_argument(
        "--json", type=str, default=None,
        help="跳过 OCR，直接使用已有的 VLM JSON 文件生成 PPTX",
    )
    parser.add_argument(
        "--output", type=str, default="ocr_test_output.pptx", help="输出 PPTX 路径"
    )
    parser.add_argument(
        "--work-dir", type=str, default="ocr_test_work", help="工作目录（存放中间文件）"
    )
    parser.add_argument(
        "--target-w", type=int, default=1920, help="目标画布宽度 (默认 1920)"
    )
    parser.add_argument(
        "--target-h", type=int, default=1080, help="目标画布高度 (默认 1080)"
    )
    parser.add_argument(
        "--width-buffer", type=float, default=1.15, help="文本框宽度冗余系数，防止因字体渲染导致不够长换行 (默认 1.15)"
    )
    args = parser.parse_args()

    image_path = Path(args.image).resolve()
    if not image_path.exists():
        print(f"错误: 图片文件不存在: {image_path}")
        sys.exit(1)

    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    target_w = args.target_w
    target_h = args.target_h

    # ── 核心修复：无论是否跳过 OCR，背景图都需要被处理并对齐到标准画布 ──
    print(f"[1/4] 对齐输入图片到 {target_w}x{target_h} 画布作为背景 ...")
    aligned_path = work_dir / "aligned.png"
    align_image_to_ppt(image_path, aligned_path, target_w=target_w, target_h=target_h)
    print(f"       背景图已保存: {aligned_path}")

    if args.json:
        # ── 快捷路径：从已有 JSON 直接加载文本元素 ──
        json_path = Path(args.json).resolve()
        if not json_path.exists():
            print(f"错误: JSON 文件不存在: {json_path}")
            sys.exit(1)
        print(f"[2/4] 加载已有 VLM JSON: {json_path}")
        
        raw_json_data = json.loads(json_path.read_text(encoding="utf-8"))
        
        # 兼容左边字典嵌套结构与右边纯数组结构
        if isinstance(raw_json_data, dict):
            vlm_elements = raw_json_data.get("titles") or raw_json_data.get("elements")
            if vlm_elements is None:
                print(f"错误: JSON字典结构中未找到 'titles' 或 'elements' 数组字段。")
                sys.exit(1)
            # 如果外层指定了画布大小，动态同步更新画布尺寸
            target_w = raw_json_data.get("canvas_width", target_w)
            target_h = raw_json_data.get("canvas_height", target_h)
            # 如果画布尺寸变了，重新对齐一下背景图以保证比例一致
            align_image_to_ppt(image_path, aligned_path, target_w=target_w, target_h=target_h)
        elif isinstance(raw_json_data, list):
            vlm_elements = raw_json_data
        else:
            print("错误: 不支持的 JSON 根节点类型（必须是对象或数组）")
            sys.exit(1)

        print(f"       成功提取到 {len(vlm_elements)} 个文本元素")
    else:
        # ── 正常路径：调用 OCR 引擎识别并转换为 VLM 格式 ──
        print("[2/4] 调用 OCR 引擎识别并转换为 VLM 格式 ...")
        engine = OCREngine()
        ocr_vlm_path = work_dir / "ocr_vlm.json"
        vlm_elements = engine.recognize_to_vlm_file(aligned_path, ocr_vlm_path)
        print(f"       识别到 {len(vlm_elements)} 个文本元素 → {ocr_vlm_path}")

    if not vlm_elements:
        print("警告: 未识别到任何文字，将生成仅含背景图的 PPTX")

    # ── Step 3: 构建 manifest（背景图 + 文字叠加） ──
    print("[3/4] 构建 manifest ...")
    elements: list[dict] = []
    
    # 将刚刚对齐好的公共背景图塞进元素列表的底层
    elements.append({
        "type": "image",
        "name": "background",
        "file": str(aligned_path),
        "bbox": {"x": 0, "y": 0, "w": target_w, "h": target_h},
        "z_index": 0,
    })
    
    # 构造并转换文本元素
    for elem in vlm_elements:
        if not isinstance(elem, dict):
            continue
            
        orig_bbox = elem.get("bbox", {"x": 0, "y": 0, "w": 100, "h": 30})
        
        if isinstance(orig_bbox, list) and len(orig_bbox) == 4:
            x, y = float(orig_bbox[0]), float(orig_bbox[1])
            w, h = float(orig_bbox[2]) - x, float(orig_bbox[3]) - y
        elif isinstance(orig_bbox, dict):
            x = float(orig_bbox.get("x", 0))
            y = float(orig_bbox.get("y", 0))
            w = float(orig_bbox.get("w", orig_bbox.get("width", 100)))
            h = float(orig_bbox.get("h", orig_bbox.get("height", 30)))
        else:
            x, y, w, h = 0, 0, 100, 30

        # 文本框长度加宽优化
        optimized_w = w * args.width_buffer

        elements.append({
            "type": "text",
            "name": elem.get("name", "ocr_text"),
            "text": elem.get("text", ""),
            "bbox": {"x": x, "y": y, "w": optimized_w, "h": h},
            "font_size_px": elem.get("font_size_px", 24),
            "font_family": elem.get("font_family") or "Microsoft YaHei",
            "color": "#FF0000",  # 红色测试文字
            "bold": True,
            "italic": False,
            "align": elem.get("align") or "left",
            "z_index": 100,
        })

    manifest = {
        "slide_width": target_w,
        "slide_height": target_h,
        "deck": {
            "canvas_width": target_w,
            "canvas_height": target_h,
            "slide_width_in": 13.333,
            "name": "OCR Test",
        },
        "elements": elements,
    }

    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"       已保存: {manifest_path}")

    # ── Step 4: 生成 PPTX ──
    print("[4/4] 生成 PPTX ...")
    output_path = Path(args.output).resolve()
    
    try:
        summary = build_pptx(manifest_path, output_path, work_dir / "summary.json")
        print(f"\n✅ PPTX 已生成: {output_path}")
        print(f"   幻灯片: {summary['counts']['slides']} 页")
        print(f"   图片元素: {summary['counts']['image']} 个")
        print(f"   文字元素: {summary['counts']['text']} 个")
        print(f"   形状元素: {summary['counts']['shape']} 个")
    except Exception as e:
        print(f"\n❌ PPTX 生成失败! 错误信息: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()