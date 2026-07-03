SYSTEM_PROMPT = """
You are an expert AI agent that converts a single visual design or document into an editable PowerPoint slide using a specific JSON manifest format.

Rules:
- Use the attached image as the source of truth.
- Output JSON only. No prose, no markdown formatting (e.g., do not wrap output in ```json ... ```).
- Prefer native PPT text and shapes whenever possible.
- CRITICAL JSON ESCAPING: If any string value (especially the "text" field) contains quotes, you MUST escape them (e.g., \\"word\\") or use single quotes (e.g., 'word'). Do NOT use unescaped double quotes inside a string.
- CRITICAL BBOX FORMAT: All spatial coordinates MUST use a dictionary format: {"x": left_x, "y": top_y, "w": absolute_width, "h": absolute_height}. NEVER output bbox as an array/list. 'w' is strictly the absolute width, 'h' is the absolute height.
""".strip()

ANALYSIS_PROMPT = """
Source image: {source_path}
Image Dimensions: {width}px (width) x {height}px (height)
Optional notes: {notes}

The image content is attached. Analyze the slide deeply and output a JSON object with the exact following structure:

- canvas_width: {width}, canvas_height: {height} (Must match the provided dimensions exactly)
- background: object with type (color|gradient|image), color/gradient/image hints and bbox (x, y, w, h)
- titles: list of text blocks with text, bbox, font_family, font_size_px, color, bold, italic, align
- body_text: list of text blocks with the same fields as titles
- objects: list of visual objects with:
  name (string),
  type (icon|photo|chart|decoration|shadow|mask|texture|logo),
  bbox (x, y, w, h),
  z_index (integer),
  needs_transparent (true/false),
  style_tags (string, output 3-5 keywords describing color/style, e.g., 'flat, minimalist, blue')
- shapes: list of simple shapes (rect|roundRect|ellipse|line) with bbox, fill, stroke, stroke_width_px



CRITICAL ROUTING RULES FOR 'objects':
1. NEVER classify text as an object. All visible text MUST be extracted natively into `titles` or `body_text`. If an icon contains text, extract the text to `titles`/`body_text` and classify the icon background/symbol as an object.

CRITICAL Z-INDEX RULES:
z_index MUST strictly follow this hierarchical order to prevent content occlusion:
- Background: -999 (Fixed)
- Shapes & Background decorations: 0 to 49
- Objects (Icons, Photos, Charts): 50 to 89
- Text (Titles, Body text): 90 to 100
""".strip()

COMPONENT_PLAN_PROMPT = """
You are an expert SVG illustrator and frontend developer.
I have attached the SOURCE IMAGE and a JSON list of specific graphical elements extracted from it. 

Your task is to generate highly accurate SVG code ONLY for the elements provided in the Input JSON list.

CRITICAL RULES FOR SVG GENERATION:
1. EXHAUSTIVE MAPPING: Generate an asset for EVERY item in the Input JSON. Do not omit any.
2. PURE VECTOR ONLY: 
   - NO TEXT: Do NOT use the <text> tag under any circumstances. (Text is handled elsewhere).
   - NO RASTER EMBEDS: Do NOT use <image href="data:image...>. The SVG must be mathematically drawn using <path>, <rect>, <circle>, etc.
3. SVG CONSTRAINTS:
   - Canvas: Use viewBox="0 0 w h" with unitless numbers based on the element's w and h.
   - Styling: Use presentation attributes (e.g., fill="#ffffff", stroke="#000000"). Do NOT use `<style>` blocks or CSS classes.
   - Colors: Solid hex/RGB only. NO `<linearGradient>`, `<radialGradient>`, or `<filter>`.
   - Geometry: Prefer absolute path commands (M, L, C). Flatten all transforms (do not use transform="translate(...)").
4. JSON INTEGRITY: Output RAW JSON. Escape all double quotes inside the `svg_code` string using backslashes (\\").

Format requirements (match this layout exactly):
{
  "assets": [
    {
      "name": "icon_example",
      "type": "icon",
      "bbox": { "x": 45, "y": 255, "w": 35, "h": 45 },
      "transparent": true,
      "svg_code": "<svg viewBox=\\"0 0 35 45\\" xmlns=\\"http://www.w3.org/2000/svg\\"><path d=\\"M4 4 L31 4 L31 41 L4 41 Z\\" fill=\\"#f5c542\\" stroke=\\"#a67c00\\"/></svg>"
    }
  ]
}

Input JSON (Elements needing SVG generation):
{filtered_json}
""".strip()

MANIFEST_PROMPT = """
Using the Analysis JSON and the generated Asset List JSON below, output a valid manifest.json for one slide.

Rules:
- Output JSON only. No markdown formatting.
- Coordinates remain in source pixel space.
- Elements must be ordered from back to front (based on z_index and natural flow).
- Asset Mapping: 
  - If an object was routed to "svg", its file path must be "component_images/[name].svg".
  - If an object was routed to "crop" (or previously raster), its file path must be "component_images/[name].png".
- Native text (`titles`, `body_text`) and `shapes` do not use file paths.

Format requirements (match this layout exactly):
{
  "slide_width": <match canvas_width from Analysis JSON>,
  "slide_height": <match canvas_height from Analysis JSON>,
  "elements": [
    {
      "type": "image|shape|text",
      "name": "...",
      "file": "component_images/icon.svg", 
      "shape_type": "rect|roundRect|ellipse|line|custom",
      "fill": "#RRGGBB" | "none",
      "stroke": "#RRGGBB" | "none",
      "stroke_width_px": 1,
      "text": "...",
      "font_family": "Arial",
      "font_size_px": 16,
      "color": "#RRGGBB",
      "bold": true,
      "italic": false,
      "align": "left|center|right|justify",
      "bbox": { "x": 0, "y": 0, "w": 100, "h": 100 }
    }
  ],
  "deck": {
    "canvas_width": <match canvas_width>,
    "canvas_height": <match canvas_height>,
    "slide_width_in": 13.333,
    "name": "Vector-First PPTX Deck"
  }
}

Analysis JSON:
{analysis_json}

Asset list JSON:
{asset_json}
""".strip()

PROCESS_NOTES_TEMPLATE = """
Workflow: Vector-First PPTX Pipeline
Mode: {mode}
Sources: {sources}
Vision model: {vision_model}
SVG/Component model: {component_model}
Assets generated: {assets} (SVGs: {svg_count}, Crops/PNGs: {crop_count})
Notes: {notes}
""".strip()