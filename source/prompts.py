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
- CRITICAL BBOX FORMAT: All spatial coordinates MUST use a dictionary format: 
  {"x": left_x, "y": top_y, "w": absolute_width, "h": absolute_height}.
  NEVER output bbox as an array/list. 
  NEVER confuse x_max/y_max with w/h. 'w' is strictly the absolute width, 'h' is the absolute height.
""".strip()

# --- 新增 Pass 1.5: 字体排印与样式分析 ---
ANALYSIS_PROMPT_TYPOGRAPHY = """
Source image: {source_path}

TEXT CONTENT AND BOUNDING BOXES:
{text_context}

Task: You are an expert Typography Analyst. I have already extracted the text and their bounding boxes. 
Your ONLY job is to analyze the visual styling of each text block provided in the context. 
Output the exact same text blocks in the exact same order, but append their visual properties.

CRITICAL RULES:
1. "font_size_px": Estimate the font size in pixels. You can use the height of the bounding box as a reference (usually font size is slightly smaller than bbox height).
2. "color": MUST be a standard hex code (e.g., "#FFFFFF", "#333333").
3. "align": "left", "center", "right", or "justify".

Required Output Format Structure:
{{
  "titles": [
    {{
      "text": "Match the exact text from context",
      "font_size_px": 32,
      "color": "#FFFFFF",
      "bold": true,
      "italic": false,
      "align": "left"
    }}
  ],
  "body_text": [
    {{
      "text": "Match the exact text from context",
      "font_size_px": 16,
      "color": "#333333",
      "bold": false,
      "italic": false,
      "align": "left"
    }}
  ]
}}
""".strip()

ANALYSIS_PROMPT = """
Source image: {source_path}
Image Dimensions: {width}px (width) x {height}px (height)
Optional notes: {notes}

The image content is attached. Analyze the slide and output a JSON object with:

- canvas_width: {width}, canvas_height: {height} (Must match the provided dimensions exactly)
- background: object with type (color|gradient|image), color/gradient/image hints and bbox (x, y, w, h)
- titles: list of text blocks with text, bbox, font_family, font_size_px, color, bold, italic, align
- body_text: list of text blocks with the same fields as titles
- objects: list of visual objects with:
  name, type (icon|photo|chart|decoration|shadow|mask|texture|logo|shape),
  bbox (x, y, w, h), z_index, needs_image (true/false), needs_transparent
- shapes: list of simple shapes (rect|roundRect|ellipse|line) with bbox, fill,
  stroke, stroke_width_px

Also explicitly list any icons, photos, charts, decorations, shadows, and masks
in the objects list even if they overlap.

CRITICAL ROUTING RULES FOR 'objects':
1. NEVER classify text as an object. All visible text MUST be extracted natively into `titles` or `body_text`. If an icon contains text, extract the text to `titles`/`body_text` and classify the icon background/symbol as an object.

CRITICAL Z-INDEX RULES:
z_index MUST strictly follow this hierarchical order to prevent content occlusion:
- Background: -999 (Fixed)
- Shapes & Background decorations: 0 to 49
- Objects (Icons, Photos, Charts): 50 to 89
- Text (Titles, Body text): 90 to 100
""".strip()
ANALYSIS_PROMPT_LAYOUT = """
Source image: {source_path}
Image Dimensions: {width}px (width) x {height}px (height)

Task: Perform a macro-level Document Layout Analysis. 
Do not extract specific text content or exact icons. Instead, analyze the overall structure, grid system, and visual hierarchy of the slide.
Divide the slide into logical major regions.

SUPPORTED LAYOUT TYPES (Choose the closest match):
- [Text]: Title-Only, Title-and-Body
- [Columns]: Two-Column-Split, Three-Column-List, Left-Sidebar-Content, Right-Sidebar-Content
- [Grids]: Symmetric-Card-Grid, Masonry-Grid
- [Flows/Diagrams]: Horizontal-Process-Steps, Vertical-Process-Steps, Hub-and-Spoke, Comparison-VS, Pyramid-or-Funnel
- [Visual]: Full-Bleed-Image, Hero-Graphic-Centered, Freeform-Complex

SHAPE VOCABULARY REFERENCE:
[rect, roundRect, snipRoundRect, ellipse, triangle, rightTriangle, trapezoid, parallelogram, diamond, pentagon, hexagon, octagon, cross, teardrop, line, arrowLine, doubleArrowLine, rightArrow, leftArrow, upArrow, downArrow, leftRightArrow, chevron, bentArrow, uTurnArrow, circularArrow, star, bubble, cloudCallout, ribbon, frame, halfFrame, mathPlus, mathEqual, mathMultiply]

Required Output Format Structure:
{{
  "layout_type": "Horizontal-Process-Steps",
  "global_description": "A process flow moving from left to right, featuring three main sequential steps.",
  "major_regions": [
    {{
      "region_name": "Main Header Area",
      "description": "Contains the primary title and subtitle, located at the top.",
      "approximate_bbox": {{ "x": 0, "y": 0, "w": 1920, "h": 200 }},
      "suggested_shape_types": ["rect", "ribbon"]
    }},
    {{
      "region_name": "Process Step 1 (Left)",
      "description": "The first step in the sequence, containing a graphic and text.",
      "approximate_bbox": {{ "x": 100, "y": 300, "w": 500, "h": 400 }},
      "suggested_shape_types": ["chevron", "rightArrow", "roundRect"]
    }},
    {{
      "region_name": "Process Step 2 (Middle)",
      "description": "The second step in the sequence.",
      "approximate_bbox": {{ "x": 700, "y": 300, "w": 500, "h": 400 }},
      "suggested_shape_types": ["chevron", "rightArrow", "roundRect"]
    }}
  ]
}}
""".strip()
# --- 替换 prompts.py 中的 ANALYSIS_PROMPT ---

ANALYSIS_PROMPT_TEXT = """
Source image: {source_path}
Image Dimensions: {width}px (width) x {height}px (height)
Optional notes: {notes}

You are an expert Presentation Typography Analyst. 
Your ONLY job is to extract the canvas dimensions and all visible text elements (titles and body text) from the attached image.
DO NOT extract backgrounds, images, icons, or decorative shapes in this step.

Output a JSON object with:
- canvas_width: {width}, canvas_height: {height}
- titles: list of main heading text blocks with text, bbox (x, y, w, h), font_family, font_size_px, color, bold, italic, align
- body_text: list of secondary/paragraph text blocks with the same fields as titles

COLOR CONSTRAINT: For "fill" and "stroke" fields, ONLY use standard hexadecimal color codes (e.g., "#FFFFFF", "#1A1A1A") or "none". NEVER output web/SVG concepts like "url(#...)", "linear-gradient(...)", "rgba(...)" or CSS filter names. If a shape has a complex gradient effect, fallback to its dominant solid hex color.
CRITICAL BBOX FORMAT: All spatial coordinates MUST use a dictionary format: 
{{"x": left_x, "y": top_y, "w": absolute_width, "h": absolute_height}}.
""".strip()

ANALYSIS_PROMPT_OBJECTS = """
You are an expert in presentation design deconstruction. Please analyze the [Background], [Shapes], and [Visual Objects/Icons] in this image.
The original physical dimensions of the image are {width}px in width and {height}px in height.

GLOBAL LAYOUT CONTEXT:
{layout_context}

Task: Identify the background, simple vector shapes, and graphical objects (icons/photos/charts).
Use the GLOBAL LAYOUT CONTEXT to understand the major blocks
[Output Format Requirement]

{{
  "background": {{
    "type": "color/gradient/image",
    "color": "#HEXCODE",
    "bbox": {{"x": number, "y": number, "w": number, "h": number}}
  }},
  "shapes": [
    {{
      "type": "Enum: rect | roundRect | ellipse | triangle | rightTriangle | line | arrowLine | doubleArrowLine | rightArrow | leftArrow | upArrow | downArrow | chevron | parallelogram | diamond | hexagon | star | bubble",
      "name": "container_box",
      "bbox": {{ "x": 100, "y": 60, "w": 900, "h": 400 }},
      "fill": "#222222",
      "stroke": "none",
      "stroke_width_px": 0,
      "z_index": 10
    }}
  ],
    "objects": [
    {{
      "type": "image/icon",
      "name": "descriptive_name",
      "needs_image": true,
      "bbox": {{"x": number, "y": number, "w": number, "h": number}},
      "z_index": number
    }}
  ]
}}
CRITICAL RULES:
1. NEVER classify text as an object or shape. Ignore the text itself, focus on what is behind or around it.
2. CRITICAL BBOX FORMAT: {{"x": left_x, "y": top_y, "w": absolute_width, "h": absolute_height}}.
3.COLOR CONSTRAINT: For "fill" and "stroke" fields, ONLY use standard hexadecimal color codes (e.g., "#FFFFFF", "#1A1A1A") or "none". NEVER output web/SVG concepts like "url(#...)", "linear-gradient(...)", "rgba(...)" or CSS filter names. If a shape has a complex gradient effect, fallback to its dominant solid hex color.
4. SHAPE CLASSIFICATION: You MUST classify shapes strictly using the provided Enum list. If a shape is complex or custom, fallback to "rect" or extract it as an "object" (icon/image) instead.
""".strip()


COMPONENT_PLAN_PROMPT = """
You are an expert prompt engineer for an image generation AI.
I have attached the SOURCE IMAGE and a JSON list of specific elements extracted from it. 

Your task is to write highly accurate `prompt` and `negative_prompt` strings to recreate each element.

Rules:
- 1. EXHAUSTIVE MAPPING: You MUST review the "background" and the entire "objects" array from the Analysis JSON. 
- 2. ONLY include assets that should be generated or cleaned by imagegen (backgrounds, photos, icons, charts, textures, shadows, masks, decorations). Do NOT include native shapes or text.
- 3. DESCRIBE WHAT YOU SEE: Base your prompt ONLY on how that specific element looks in the source image (colors, art style, flat vs 3D, textures, gradients, context).
- 4. Set transparent=true for icons or assets that need alpha.

Format requirements (match this layout exactly, notice the array contains MULTIPLE items, your output must contain ALL necessary items):
{
  "assets": [
    {
      "name": "Background Image",
      "type": "texture",
      "bbox": { "x": 0, "y": 0, "w": 1920, "h": 1080 },
      "prompt": "...",
      "negative_prompt": "...",
      "transparent": false
    },
    {
      "name": "icon_example",
      "type": "icon",
      "bbox": { "x": 45, "y": 255, "w": 35, "h": 45 },
      "prompt": "...",
      "negative_prompt": "...",
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
Imagegen model: {imagegen_model}
No redraw: {no_redraw}
Assets generated: {assets}
Notes: {notes}
""".strip()
