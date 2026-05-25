"""
generate_carousels.py
Generates 6-slide Instagram carousel PNGs from blog posts using Claude + Pillow.

Usage:
    python3 generate_carousels.py --posts site/posts --output carousel_output --limit 30
"""

import os
import re
import sys
import json
import argparse
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import anthropic

# ── Brand ────────────────────────────────────────────────────────────────────
BG          = (15, 15, 15)           # #0f0f0f
PURPLE      = (123, 47, 190)         # #7B2FBE
WHITE       = (255, 255, 255)
LIGHT_GRAY  = (180, 180, 180)
DARK_GRAY   = (120, 120, 120)

# ── Slide dimensions (1080x1080 square) ──────────────────────────────────────
W, H = 1080, 1080
EDGE_BAR_W  = 8     # left purple bar width
MARGIN_L    = 72    # left content margin (after bar)
MARGIN_R    = 60    # right margin
MARGIN_T    = 60    # top margin
CONTENT_W   = W - MARGIN_L - MARGIN_R


# ── Fonts ────────────────────────────────────────────────────────────────────
def load_font(size, bold=False):
    """Try to load a system font, fall back to default."""
    candidates_bold = [
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    candidates_reg = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    candidates = candidates_bold if bold else candidates_reg
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── HTML stripping ────────────────────────────────────────────────────────────
def strip_html(html):
    """Remove HTML tags and decode common entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
               .replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"') \
               .replace('&ldquo;', '"').replace('&rdquo;', '"') \
               .replace('&lsquo;', "'").replace('&rsquo;', "'") \
               .replace('&mdash;', '—').replace('&ndash;', '–') \
               .replace('\\\"', '"')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_post_text(html_path):
    """Read an HTML post and return its title + body text."""
    raw = html_path.read_text(encoding='utf-8', errors='ignore')
    # Title from <title> or <h1>
    title_match = re.search(r'<title>(.*?)</title>', raw, re.IGNORECASE | re.DOTALL)
    h1_match    = re.search(r'<h1[^>]*>(.*?)</h1>', raw, re.IGNORECASE | re.DOTALL)
    title = strip_html((h1_match or title_match).group(1)) if (h1_match or title_match) else html_path.stem
    # Body: content inside <article> if present, otherwise <body>
    article_match = re.search(r'<article[^>]*>(.*?)</article>', raw, re.IGNORECASE | re.DOTALL)
    body_html = article_match.group(1) if article_match else raw
    body = strip_html(body_html)
    return title, body


# ── Claude content extraction ─────────────────────────────────────────────────
def extract_carousel_content(client, post_title, post_body):
    """Ask Claude to extract structured carousel content from a blog post."""
    prompt = f"""You are creating an Instagram carousel about public speaking for Wade Paterson's brand.

Post title: {post_title}

Post body (first 4000 chars):
{post_body[:4000]}

Extract carousel content and return ONLY valid JSON (no markdown, no extra text) in this exact structure:
{{
  "topic_label": "short 1-3 word category label (e.g. PUBLIC SPEAKING, STORYTELLING, MINDSET)",
  "hook_title": "short punchy uppercase title (max 8 words) capturing the core insight",
  "teaser": "one engaging sentence (max 20 words) teasing the value inside",
  "tips": [
    {{"title": "tip title (max 6 words)", "body": "tip explanation (max 30 words)"}},
    {{"title": "tip title (max 6 words)", "body": "tip explanation (max 30 words)"}},
    {{"title": "tip title (max 6 words)", "body": "tip explanation (max 30 words)"}}
  ],
  "quote": "a single powerful quote from the post (max 25 words), in quotes"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    text = re.sub(r'^```json\s*|^```\s*|```$', '', text, flags=re.MULTILINE).strip()
    return json.loads(text)


# ── Drawing helpers ───────────────────────────────────────────────────────────
def new_slide():
    """Create a blank dark slide with the purple left-edge bar."""
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, EDGE_BAR_W, H], fill=PURPLE)
    return img, draw


def draw_chrome(draw, slide_num):
    """Draw 'WADE PATERSON' top-left and slide number top-right."""
    font_sm = load_font(28, bold=False)
    brand = "WADE PATERSON"
    draw.text((MARGIN_L, MARGIN_T), brand, font=font_sm, fill=DARK_GRAY)
    num_text = f"{slide_num} / 6"
    nbbox = draw.textbbox((0, 0), num_text, font=font_sm)
    nw = nbbox[2] - nbbox[0]
    draw.text((W - MARGIN_R - nw, MARGIN_T), num_text, font=font_sm, fill=DARK_GRAY)


def wrap_text(draw, text, font, max_width):
    """Word-wrap text to fit within max_width pixels. Returns list of lines."""
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = ' '.join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines


def draw_wrapped(draw, text, font, x, y, max_width, fill, line_spacing=1.25):
    """Draw word-wrapped text, return the y position after the last line."""
    lines = wrap_text(draw, text, font, max_width)
    bbox = draw.textbbox((0, 0), 'A', font=font)
    line_h = int((bbox[3] - bbox[1]) * line_spacing)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


# ── Slide generators ──────────────────────────────────────────────────────────
def make_slide_1(content, out_path):
    """Hook slide: topic label, big title, teaser."""
    img, draw = new_slide()
    draw_chrome(draw, 1)

    font_label = load_font(30, bold=True)
    font_title = load_font(74, bold=True)
    font_teaser = load_font(36, bold=False)

    y = 200

    # Topic label in purple
    label = content['topic_label'].upper()
    draw.text((MARGIN_L, y), label, font=font_label, fill=PURPLE)
    y += 52

    # Thin purple underline under label
    lbbox = draw.textbbox((0, 0), label, font=font_label)
    lw = lbbox[2] - lbbox[0]
    draw.rectangle([MARGIN_L, y, MARGIN_L + lw, y + 3], fill=PURPLE)
    y += 28

    # Big white uppercase title
    title = content['hook_title'].upper()
    y = draw_wrapped(draw, title, font_title, MARGIN_L, y, CONTENT_W, WHITE, line_spacing=1.15)
    y += 40

    # Gray teaser line
    draw_wrapped(draw, content['teaser'], font_teaser, MARGIN_L, y, CONTENT_W, LIGHT_GRAY)

    img.save(out_path, 'PNG')


def make_slide_tip(content, tip_index, slide_num, out_path):
    """Tip slide: big number, tip title, tip body."""
    img, draw = new_slide()
    draw_chrome(draw, slide_num)

    font_num   = load_font(160, bold=True)
    font_title = load_font(56, bold=True)
    font_body  = load_font(36, bold=False)

    tip = content['tips'][tip_index]
    number = f"0{tip_index + 1}"

    y = 160

    # Big purple number
    draw.text((MARGIN_L, y), number, font=font_num, fill=PURPLE)
    nbbox = draw.textbbox((0, 0), number, font=font_num)
    y += (nbbox[3] - nbbox[1]) + 20

    # White bold tip title
    y = draw_wrapped(draw, tip['title'].upper(), font_title, MARGIN_L, y, CONTENT_W, WHITE, line_spacing=1.2)
    y += 32

    # Gray body text
    draw_wrapped(draw, tip['body'], font_body, MARGIN_L, y, CONTENT_W, LIGHT_GRAY, line_spacing=1.5)

    img.save(out_path, 'PNG')


def make_slide_5(content, out_path):
    """Quote slide: quote in a purple-left-bordered box."""
    img, draw = new_slide()
    draw_chrome(draw, 5)

    font_label = load_font(28, bold=True)
    font_quote = load_font(42, bold=False)

    y = 220

    # Small label
    draw.text((MARGIN_L, y), "KEY INSIGHT", font=font_label, fill=PURPLE)
    y += 48

    # Calculate quote box height first
    lines = wrap_text(draw, content['quote'], font_quote, CONTENT_W - 40)
    lbbox = draw.textbbox((0, 0), 'A', font=font_quote)
    line_h = int((lbbox[3] - lbbox[1]) * 1.55)
    box_pad_v = 36
    box_h = len(lines) * line_h + box_pad_v * 2

    box_x = MARGIN_L
    box_y = y
    box_w = CONTENT_W

    # Dark background box
    draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h],
                   fill=(25, 10, 40))

    # Purple left border on the quote box (thick, inside left edge)
    draw.rectangle([box_x, box_y, box_x + 6, box_y + box_h], fill=PURPLE)

    # Quote text
    text_x = box_x + 36
    text_y = box_y + box_pad_v
    for line in lines:
        draw.text((text_x, text_y), line, font=font_quote, fill=WHITE)
        text_y += line_h

    img.save(out_path, 'PNG')


def make_slide_6(out_path):
    """Save prompt slide."""
    img, draw = new_slide()
    draw_chrome(draw, 6)

    font_main   = load_font(54, bold=True)
    font_sub    = load_font(32, bold=False)

    main_text = "SAVE THIS FOR\nYOUR NEXT SPEECH"
    sub_text  = "Follow for more public speaking tips"

    # Center vertically
    lines = main_text.split('\n')
    lbbox = draw.textbbox((0, 0), 'A', font=font_main)
    line_h = int((lbbox[3] - lbbox[1]) * 1.25)
    total_h = len(lines) * line_h
    start_y = (H - total_h) // 2 - 40

    for i, line in enumerate(lines):
        lbx = draw.textbbox((0, 0), line, font=font_main)
        lw = lbx[2] - lbx[0]
        x = (W - lw) // 2
        draw.text((x, start_y + i * line_h), line, font=font_main, fill=WHITE)

    after_y = start_y + total_h + 24

    # Small purple underline accent
    accent_w = 80
    accent_x = (W - accent_w) // 2
    draw.rectangle([accent_x, after_y, accent_x + accent_w, after_y + 4], fill=PURPLE)
    after_y += 28

    # Subtext
    sbbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    sw = sbbox[2] - sbbox[0]
    draw.text(((W - sw) // 2, after_y), sub_text, font=font_sub, fill=LIGHT_GRAY)

    img.save(out_path, 'PNG')


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Generate Instagram carousel slides from blog posts.')
    parser.add_argument('--posts',  default='site/posts', help='Path to posts folder')
    parser.add_argument('--output', default='carousel_output', help='Output directory')
    parser.add_argument('--limit',  type=int, default=30, help='Max posts to process')
    args = parser.parse_args()

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    posts_dir  = Path(args.posts)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    post_files = sorted(posts_dir.glob('*.html'))
    if not post_files:
        print(f"No .html files found in {posts_dir}")
        sys.exit(1)

    post_files = post_files[:args.limit]
    print(f"Found {len(post_files)} posts (limit: {args.limit})")
    print(f"Output: {output_dir}\n")

    success = 0
    skipped = 0

    for post_path in post_files:
        slug = post_path.stem
        print(f"→ {slug}")

        try:
            post_title, post_body = extract_post_text(post_path)

            if len(post_body.split()) < 80:
                print("  [skip] Post too short")
                skipped += 1
                continue

            content = extract_carousel_content(client, post_title, post_body)

            # Validate structure
            required = ['topic_label', 'hook_title', 'teaser', 'tips', 'quote']
            for field in required:
                if field not in content:
                    raise ValueError(f"Missing field: {field}")
            if len(content['tips']) < 3:
                raise ValueError(f"Expected 3 tips, got {len(content['tips'])}")

            # Create output folder for this post
            post_out = output_dir / slug
            post_out.mkdir(parents=True, exist_ok=True)

            make_slide_1(content, post_out / 'slide-1.png')
            make_slide_tip(content, 0, 2, post_out / 'slide-2.png')
            make_slide_tip(content, 1, 3, post_out / 'slide-3.png')
            make_slide_tip(content, 2, 4, post_out / 'slide-4.png')
            make_slide_5(content, post_out / 'slide-5.png')
            make_slide_6(post_out / 'slide-6.png')

            print(f"  ✓ 6 slides → {post_out}/")
            success += 1

        except Exception as e:
            print(f"  [error] {e} — skipping")
            skipped += 1
            continue

    print(f"\nDone. {success} carousels generated, {skipped} skipped.")
    print(f"Output: {output_dir.resolve()}")


if __name__ == '__main__':
    main()
