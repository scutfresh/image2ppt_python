# Image2PPT OpenAI-Compatible Workflow (Vision + ImageGen)

This folder contains an OpenAI-compatible workflow that follows the
bggg-creator-image2ppt process for bitmap inputs. It adds:

- Vision analysis (Qwen-VL or any OpenAI-compatible vision model).
- Image generation for non-text components (DashScope Z-Image-Turbo or any
  OpenAI-compatible image endpoint).
- Manifest generation and PPTX build via the existing skill scripts.

## Install

```bash
pip install -r requirements.txt
```

## Run (bitmap)

```bash
python agent_workflow.py --slug demo_cover --source D:\path\to\slide.png
```

Example with DashScope:

```bash
python agent_workflow.py --slug demo_cover --source D:\Desktop\南网\ppt图片.png --vision-model Qwen35-35b-a3b --vision-base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --imagegen-model Z-Image-Turbo --imagegen-base-url https://dashscope.aliyuncs.com/compatible-mode/v1
```

## Environment

Vision (analysis):
- IMAGE2PPT_VISION_MODEL (default: qwen-vl)
- IMAGE2PPT_VISION_BASE_URL (required)
- IMAGE2PPT_VISION_API_KEY (optional, falls back to DASHSCOPE_API_KEY or OPENAI_API_KEY)
- IMAGE2PPT_VISION_TEMPERATURE (default: 0.2)

Manifest generation uses the same model as vision analysis.

Image generation (Z-Image-Turbo via OpenAI-compatible API):
- IMAGE2PPT_IMAGEGEN_MODEL (default: z-image-turbo)
- IMAGE2PPT_IMAGEGEN_BASE_URL (required)
- IMAGE2PPT_IMAGEGEN_API_KEY (optional, falls back to DASHSCOPE_API_KEY or OPENAI_API_KEY)
- IMAGE2PPT_IMAGEGEN_SIZE (default: 1024x1024)
- IMAGE2PPT_IMAGEGEN_BACKGROUND (optional, set if provider supports transparent)

## Outputs

Projects are created under:
- bggg-creator-image2ppt/projects/YYYYMMDD_slug/

Artifacts:
- manifest.json
- output.pptx
- summary.json
- process_notes.md
- diagnostics/analysis.json
- diagnostics/component_plan.json
- diagnostics/asset_catalog.json

## Notes

- Use --no-redraw to crop components from the source instead of imagegen.
- The workflow currently supports bitmap inputs only (PNG/JPEG/WebP).
