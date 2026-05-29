SYSTEM_PROMPT = """
You are an expert agent that converts a single visual design into an editable
PowerPoint slide using the bggg-creator-image2ppt manifest format.

Rules:
- Use the attached image as the source of truth.
- Output JSON only. No prose, no markdown.
- Prefer native PPT text and shapes whenever possible.
- Only use image layers for photos, illustrations, icons, complex charts,
  textures, shadows, masks, and any content that cannot be reconstructed
  as native PPT elements.
- CRITICAL: If any string value (especially the "text" field) contains quotes,
  you MUST escape them (e.g., \\"word\\") or use single quotes (e.g., 'word').
  Do NOT use unescaped double quotes inside a string.
""".strip()

ANALYSIS_PROMPT = """
Source image: {source_path}
Optional notes: {notes}

The image content is attached. Analyze the slide and output a JSON object with:

- canvas_width, canvas_height (numbers)
- background: object with type (color|gradient|image), color/gradient/image hints
  and bbox (x, y, w, h)
- titles: list of text blocks with text, bbox, font_family, font_size_px,
  color, bold, italic, align
- body_text: list of text blocks with the same fields as titles
- objects: list of visual objects with:
  name, type (icon|photo|chart|decoration|shadow|mask|texture|logo|shape),
  bbox (x, y, w, h), z_index, needs_image (true/false), needs_transparent
- shapes: list of simple shapes (rect|roundRect|ellipse|line) with bbox, fill,
  stroke, stroke_width_px

Also explicitly list any icons, photos, charts, decorations, shadows, and masks
in the objects list even if they overlap.
""".strip()

COMPONENT_PLAN_PROMPT = """
You are preparing image generation tasks for non-text components.

Using the Format requirements below, output a JSON object with the exact format below.

Rules:
- Only include assets that should be generated or cleaned by imagegen.
- Include background, photos, icons, charts, textures, shadows, masks,
  and any complex decoration that should be a separate image.
- Use short, direct prompts. Describe style and colors from the source.
- Set transparent=true for icons or assets that need alpha.
- CRITICAL: If any string value (especially the "text" field) contains quotes,
  you MUST escape them (e.g., \\"word\\") or use single quotes (e.g., 'word').
  Do NOT use unescaped double quotes inside a string.

Format requirements (match this layout exactly):
{
  "assets": [
    {
      "name": "Background Image",
      "type": "texture",
      "bbox": { "x": 0, "y": 0, "w": 1920, "h": 1080 },
      "prompt": "...",
      "negative_prompt": "...",
      "transparent": false
    }
  ]
}

""".strip()

MANIFEST_PROMPT = """
Using the analysis JSON and asset list below, output a valid
bggg-creator-image2ppt manifest.json for one slide.

Rules:
- Output JSON only.
- Use coordinates in source pixel space.
- Use native text and shapes whenever possible.
- For image elements, reference files in component_images/ using the asset list.
- Elements must be ordered from back to front.

Format requirements (match this layout exactly):
{
  "slide_width": 1920,
  "slide_height": 1080,
  "elements": [
    {
      "type": "image|shape|text",
      "name": "...",
      "file": "component_images/...png",
      "shape_type": "rect|roundRect|round_rect|ellipse|line|custom",
      "fill": "#RRGGBB" | "none",
      "stroke": "#RRGGBB" | "none",
      "stroke_width_px": 1,
      "text": "...",
      "font_family": "Microsoft YaHei",
      "font_size_px": 16,
      "color": "#RRGGBB",
      "bold": true,
      "italic": false,
      "align": "left|center|right|justify",
      "bbox": { "x": 0, "y": 0, "w": 100, "h": 100 }
    }
  ],
  "deck": {
    "canvas_width": 1920,
    "canvas_height": 1080,
    "slide_width_in": 13.333,
    "slide_height_in": 7.5,
    "name": "Image2PPT Deck"
  }
}

Notes:
- Always include slide_width, slide_height, elements, and deck.
- For each element, include only the fields relevant to its type.
- Keep bbox for every element.
- If any string value (especially the "text" field) contains quotes,
  you MUST escape them (e.g., \\"word\\") or use single quotes (e.g., 'word').
  Do NOT use unescaped double quotes inside a string.
Analysis JSON:
{analysis_json}

Asset list JSON:
{asset_json}
""".strip()

PROCESS_NOTES_TEMPLATE = """
Workflow: openai-compat agent (vision + imagegen)
Mode: {mode}
Sources: {sources}
Vision model: {vision_model}
Manifest model: {manifest_model}
Imagegen model: {imagegen_model}
No redraw: {no_redraw}
Assets generated: {assets}
Notes: {notes}
""".strip()
