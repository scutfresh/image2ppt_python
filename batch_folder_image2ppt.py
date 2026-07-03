from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from source.image2pptx import build_pptx


def _load_workflow_symbols():
    try:
        from agent_workflow import (  # type: ignore
            build_client,
            generate_analysis,
            generate_component_plan,
            generate_manifest_python,
            normalize_bbox,
            safe_filename,
        )
        from source.imagegen import ImageGenConfig, generate_image  # type: ignore
        from source.tools import align_image_to_ppt, slugify, unique_project_dir, validate_and_fix_component_plan  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Missing runtime dependency while loading workflow modules: {exc}. "
            "Install the project requirements before running batch generation."
        ) from exc

    return {
        "build_client": build_client,
        "generate_analysis": generate_analysis,
        "generate_component_plan": generate_component_plan,
        "generate_manifest_python": generate_manifest_python,
        "normalize_bbox": normalize_bbox,
        "safe_filename": safe_filename,
        "ImageGenConfig": ImageGenConfig,
        "generate_image": generate_image,
        "align_image_to_ppt": align_image_to_ppt,
        "slugify": slugify,
        "unique_project_dir": unique_project_dir,
        "validate_and_fix_component_plan": validate_and_fix_component_plan,
    }


ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECTS_ROOT = ROOT / "projects"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def iter_image_files(folder: Path) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"input folder not found: {folder}")
    files = [item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(files, key=lambda item: item.name.lower())


def resolve_base_url(value: str | None, env_name: str) -> str:
    return (value or os.getenv(env_name) or "").strip()


def local_slugify(value: str) -> str:
    text = value.strip().lower()
    allowed = []
    last_was_sep = False
    for char in text:
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            allowed.append(char)
            last_was_sep = False
        elif not last_was_sep:
            allowed.append("_")
            last_was_sep = True
    slug = "".join(allowed).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "image2ppt"


def build_batch_root(input_dir: Path, output_root: str | None) -> Path:
    if output_root:
        return Path(output_root).expanduser().resolve()
    return DEFAULT_PROJECTS_ROOT / f"batch_{local_slugify(input_dir.name)}"


def process_single_image(
    source_image: Path,
    batch_root: Path,
    vision_client,
    vision_temperature: float,
    imagegen_config: ImageGenConfig,
    date_override: str | None,
) -> Path:
    symbols = _load_workflow_symbols()
    date_prefix = date_override or datetime.now().strftime("%Y%m%d")
    project_dir = symbols["unique_project_dir"](batch_root, date_prefix, symbols["slugify"](source_image.stem))
    project_dir.mkdir(parents=True, exist_ok=True)
    component_dir = project_dir / "component_images"
    diagnostics_dir = project_dir / "diagnostics"
    component_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"{source_image.stem}_", dir=str(project_dir)) as temp_dir:
        standardized_path = Path(temp_dir) / "standardized_input.png"
        symbols["align_image_to_ppt"](source_image, standardized_path, target_w=1920, target_h=1080)

        analysis = symbols["generate_analysis"](
            vision_client,
            vision_temperature,
            str(source_image),
            standardized_path,
            None,
            seperate_analysis=True,
            use_ocr=True,
        )
        save_json(diagnostics_dir / "analysis.json", analysis)

        component_plan = symbols["generate_component_plan"](
            vision_client,
            vision_temperature,
            analysis,
            standardized_path,
        )
        component_plan = symbols["validate_and_fix_component_plan"](analysis, component_plan)
        save_json(diagnostics_dir / "component_plan.json", component_plan)

        asset_records: list[dict[str, Any]] = []
        for item in component_plan.get("assets") or []:
            name = str(item.get("name") or item.get("type") or "asset")
            bbox = symbols["normalize_bbox"](item)
            x, y, w, h = bbox
            if w <= 0 or h <= 0:
                print(f"Skip asset with invalid size: {name} ({w}x{h})")
                continue

            filename = symbols["safe_filename"](name, suffix=".png")
            output_path = component_dir / filename
            prompt = str(item.get("prompt") or "")
            negative_prompt = str(item.get("negative_prompt") or "") or None
            transparent = bool(item.get("transparent", False))
            request_size = f"{w}x{h}"
            symbols["generate_image"](
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
            asset_records.append(
                {
                    "name": name,
                    "type": item.get("type"),
                    "file": f"component_images/{filename}",
                    "bbox": {"x": x, "y": y, "w": w, "h": h},
                }
            )
            save_json(diagnostics_dir / "asset_catalog.json", {"assets": asset_records})

        manifest = symbols["generate_manifest_python"](analysis, asset_records)
        manifest_path = project_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        build_pptx(manifest_path, project_dir / "output.pptx", project_dir / "summary.json")

    return project_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch process a folder of images into editable PPTX files.")
    parser.add_argument("input_dir", help="folder containing input images")
    parser.add_argument("--output_root", help="batch output root folder; defaults to projects/batch_<folder>")
    parser.add_argument("--date", help="YYYYMMDD override for project naming")
    parser.add_argument("--vision_base_url", help="OpenAI-compatible vision API base URL")
    parser.add_argument("--imagegen_base_url", help="image generation API base URL")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    image_files = iter_image_files(input_dir)
    if not image_files:
        raise ValueError(f"no images found in: {input_dir}")

    batch_root = build_batch_root(input_dir, args.output_root)
    batch_root.mkdir(parents=True, exist_ok=True)

    vision_base_url = resolve_base_url(args.vision_base_url, "IMAGE2PPT_VISION_BASE_URL")
    imagegen_base_url = resolve_base_url(args.imagegen_base_url, "IMAGE2PPT_IMAGEGEN_BASE_URL")
    if not vision_base_url:
        raise RuntimeError("vision base url is required via --vision_base_url or IMAGE2PPT_VISION_BASE_URL")
    if not imagegen_base_url:
        raise RuntimeError("imagegen base url is required via --imagegen_base_url or IMAGE2PPT_IMAGEGEN_BASE_URL")

    symbols = _load_workflow_symbols()
    vision_client = symbols["build_client"](vision_base_url)
    imagegen_config = symbols["ImageGenConfig"](base_url=imagegen_base_url, model="local", size="1024x1024")

    failures: list[tuple[Path, str]] = []
    for index, source_image in enumerate(image_files, start=1):
        print(f"[{index}/{len(image_files)}] Processing {source_image.name}")
        try:
            project_dir = process_single_image(
                source_image=source_image,
                batch_root=batch_root,
                vision_client=vision_client,
                vision_temperature=0.4,
                imagegen_config=imagegen_config,
                date_override=args.date,
            )
            print(f"  -> done: {project_dir}")
        except Exception as exc:
            failures.append((source_image, str(exc)))
            print(f"  -> failed: {exc}")

    if failures:
        print("Batch finished with failures:")
        for source_image, message in failures:
            print(f"- {source_image.name}: {message}")
        return 1

    print(f"Batch finished successfully: {batch_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())