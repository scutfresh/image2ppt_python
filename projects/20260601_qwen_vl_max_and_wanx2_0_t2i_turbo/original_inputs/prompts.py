SYSTEM_PROMPT = """
You are an expert agent that converts a single visual design into an editable
PowerPoint slide using the specified manifest format.

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
Image Dimensions: {width}px (width) x {height}px (height)
Optional notes: {notes}

The image content is attached. Analyze the slide and output a JSON object with:

- canvas_width: {width}, canvas_height: {height} (Must match the provided dimensions exactly)
- background: object with type (color|gradient|image), color/gradient/image hints
  and bbox (x, y, w, h)
- titles: list of text blocks with text, bbox, font_family, font_size_px,
  color, bold, italic, align
- body_text: list of text blocks with the same fields as titles
- objects: list of visual objects with:
  name, type (icon|photo|chart|decoration|shadow|mask|texture|logo|shape),
  bbox (x, y, w, h), z_index, needs_image (true/false), needs_transparent,
  style_tags (string, ONLY if needs_image is true: output 3-5 keywords describing 
  color, texture, and visual style, e.g., 'neon green, glowing, 3d, flat, metallic')
- shapes: list of simple shapes (rect|roundRect|ellipse|line) with bbox, fill,
  stroke, stroke_width_px

Also explicitly list any icons, photos, charts, decorations, shadows, and masks
in the objects list even if they overlap.
""".strip()

COMPONENT_PLAN_PROMPT = """
You are an expert prompt engineer for an image generation AI.
I have attached the SOURCE IMAGE and a JSON list of specific elements extracted from it. 

Your task is to write highly accurate `prompt` and `negative_prompt` strings to recreate each element.

CRITICAL RULES:
1. EXHAUSTIVE MAPPING: You MUST generate an asset for EVERY single item provided in the Input JSON list. Do not omit any.
2. USE THE BOUNDING BOX (bbox): Look at the attached image. Use the provided "bbox" [x, y, w, h] to locate the exact element in the image.
3. DESCRIBE WHAT YOU SEE: Base your prompt ONLY on how that specific element looks in the source image (colors, art style, flat vs 3D, textures, gradients, context).
4. Set transparent=true for icons or assets that need alpha.
5. CRITICAL: If any string value contains quotes, you MUST escape them (e.g., \\"word\\") or use single quotes. Do NOT use unescaped double quotes.

Format requirements (match this layout exactly, output MUST contain ALL items):
{
  "assets": [
    {
      "name": "Background Image",
      "type": "texture",
      "bbox": { "x": 0, "y": 0, "w": 1920, "h": 1080 },
      "prompt": "soft gradient background, light blue to white transition, subtle texture",
      "negative_prompt": "dark colors, text, logos",
      "transparent": false
    },
    {
      "name": "icon_example",
      "type": "icon",
      "bbox": { "x": 45, "y": 255, "w": 35, "h": 45 },
      "prompt": "golden, flat, outline style icon...",
      "negative_prompt": "3d, realistic, cluttered",
      "transparent": true
    }
    // ... ADD ALL OTHER OBJECTS HERE ...
  ]
}

Input JSON (Elements needing images):
{filtered_json}

""".strip()

MANIFEST_PROMPT = """
Using the analysis JSON and asset list below, output a valid
specified manifest.json for one slide.

Rules:
- Output JSON only.
- Use coordinates in source pixel space.
- Use native text and shapes whenever possible.
- For image elements, reference files in component_images/ using the asset list.
- Elements must be ordered from back to front.

Format requirements (match this layout exactly):
{
  "slide_width": "MUST strictly match the canvas_width provided in Analysis JSON",
  "slide_height": "MUST strictly match the canvas_height provided in Analysis JSON",
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
    "canvas_width": "MUST strictly match the canvas_width provided in Analysis JSON",
    "canvas_height": "MUST strictly match the canvas_height provided in Analysis JSON",
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
