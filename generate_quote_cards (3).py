"""
generate_quote_cards.py
Extracts best quotes from VTT transcripts and generates branded 9:16 PNG quote cards.

Usage:
    python3 generate_quote_cards.py --transcripts ~/youtube-blog/transcripts \
                                    --image path/to/mic-image.jpeg \
                                    --output ~/youtube-blog/quote_cards \
                                    --limit 20
"""

import os
import re
import sys
import json
import argparse
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import anthropic

# ── Brand ────────────────────────────────────────────────────────────────────
PURPLE      = (123, 47, 190)        # #7B2FBE
PURPLE_DARK = (61, 0, 102)          # #3D0066
WHITE       = (255, 255, 255)
BLACK       = (0, 0, 0)

# ── Card dimensions (1080x1920 = 9:16) ───────────────────────────────────────
W, H = 1080, 1920

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


def clean_vtt(vtt_text):
    """Strip VTT timestamps and return clean text."""
    lines = vtt_text.split('\n')
    clean = []
    seen = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue
        if re.match(r'^\d+$', line):
            continue
        if re.match(r'\d{2}:\d{2}', line):
            continue
        line = re.sub(r'<[^>]+>', '', line)
        line = re.sub(r'\s+', ' ', line).strip()
        if line and line not in seen:
            seen.add(line)
            clean.append(line)
    return ' '.join(clean)


def extract_quotes_from_transcript(client, transcript_text, source_title, n=3):
    """Ask Claude to pull the best quotable lines from a transcript."""
    prompt = f"""You are extracting highly shareable, standalone quotes from a public speaking YouTube video transcript.

Video title: {source_title}

Transcript:
{transcript_text[:4000]}

Extract the {n} most powerful, quotable, standalone sentences or short passages (max 20 words each) that:
- Stand alone without context
- Are actionable, inspiring, or surprising
- Sound like something worth posting on Instagram
- Are in first or second person ("You...", "The best speakers...", "If you want to...")
- Do NOT include filler, meta-commentary, or transcript artifacts

Return ONLY a JSON array of strings, no other text. Example:
["Quote one here.", "Quote two here.", "Quote three here."]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        text = re.sub(r'^```json|^```|```$', '', text, flags=re.MULTILINE).strip()
        quotes = json.loads(text)
        return [q.strip() for q in quotes if isinstance(q, str) and len(q) > 10]
    except Exception as e:
        print(f"    [quote extraction error] {e}")
        return []


def make_quote_card(quote, author, background_img_path, output_path):
    """Generate a single 1080x1920 quote card PNG."""
    # Load and process background
    bg = Image.open(background_img_path).convert("RGB")
    bg = bg.resize((W, H), Image.LANCZOS)

    # Convert to B&W
    bg = bg.convert("L").convert("RGB")

    # Darken
    enhancer = ImageEnhance.Brightness(bg)
    bg = enhancer.enhance(0.62)

    # Slight blur
    bg = bg.filter(ImageFilter.GaussianBlur(radius=0.8))

    draw = ImageDraw.Draw(bg)

    # ── Fonts ────────────────────────────────────────────────────────────────
    font_quote = load_font(72, bold=True)

    # ── Wrap quote text ──────────────────────────────────────────────────────
    max_chars = 14
    words = quote.upper().split()
    lines = []
    current = []
    for word in words:
        test = ' '.join(current + [word])
        if len(test) <= max_chars:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))

    # ── Layout: center vertically ────────────────────────────────────────────
    bar_h = 90
    bar_gap = 12
    total_h = len(lines) * (bar_h + bar_gap) - bar_gap
    start_y = (H - total_h) // 2 - 60

    bar_pad_x = 40
    bar_pad_y = 14

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_quote)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        bar_w = text_w + bar_pad_x * 2
        bar_x = (W - bar_w) // 2
        bar_y = start_y + i * (bar_h + bar_gap)

        # Purple bar
        draw.rectangle(
            [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
            fill=PURPLE
        )

        # White text centered on bar
        text_x = bar_x + bar_pad_x
        text_y = bar_y + (bar_h - text_h) // 2 - bbox[1]

        # Outline shadow for extra pop
        for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2)]:
            draw.text((text_x+dx, text_y+dy), line, font=font_quote, fill=PURPLE_DARK)
        draw.text((text_x, text_y), line, font=font_quote, fill=WHITE)


    # ── Purple top bar ───────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, 8], fill=PURPLE)
    draw.rectangle([0, H-8, W, H], fill=PURPLE)

    bg.save(output_path, "PNG", quality=95)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--transcripts', default=os.path.expanduser('~/youtube-blog/transcripts'))
    parser.add_argument('--image', default=None, help='Path to background image')
    parser.add_argument('--output', default=os.path.expanduser('~/youtube-blog/quote_cards'))
    parser.add_argument('--limit', type=int, default=200, help='Max cards to generate')
    parser.add_argument('--quotes-per-video', type=int, default=2)
    parser.add_argument('--author', default='Wade Paterson')
    args = parser.parse_args()

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    transcripts_dir = Path(args.transcripts)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    vtt_files = sorted(transcripts_dir.glob('*.vtt'))
    if not vtt_files:
        print(f"No .vtt files found in {transcripts_dir}")
        sys.exit(1)

    # Find background image
    if args.image:
        bg_path = args.image
    else:
        # Look for image in common locations
        candidates = [
            os.path.expanduser('~/Desktop/image0.jpeg'),
            os.path.expanduser('~/Downloads/image0.jpeg'),
        ]
        bg_path = next((p for p in candidates if os.path.exists(p)), None)
        if not bg_path:
            print("Error: No background image found. Use --image path/to/image.jpeg")
            sys.exit(1)

    print(f"Found {len(vtt_files)} transcripts")
    print(f"Background image: {bg_path}")
    print(f"Output directory: {output_dir}")
    print(f"Generating up to {args.limit} quote cards...\n")

    card_count = 0
    all_quotes = []

    for vtt_path in vtt_files:
        if card_count >= args.limit:
            break

        title = vtt_path.stem
        if title.endswith('.en'):
            title = title[:-3]

        print(f"→ {title[:60]}")
        transcript = clean_vtt(vtt_path.read_text(encoding='utf-8', errors='ignore'))

        if len(transcript.split()) < 50:
            print("  [skip] Too short")
            continue

        quotes = extract_quotes_from_transcript(
            client, transcript, title, n=args.quotes_per_video)

        for quote in quotes:
            if card_count >= args.limit:
                break
            all_quotes.append({'quote': quote, 'source': title})
            slug = re.sub(r'[^a-z0-9]+', '-', quote.lower())[:40].strip('-')
            out_path = output_dir / f"card_{card_count+1:03d}_{slug}.png"
            make_quote_card(quote, args.author, bg_path, str(out_path))
            print(f"  ✓ Card {card_count+1}: \"{quote[:50]}...\"" if len(quote) > 50 else f"  ✓ Card {card_count+1}: \"{quote}\"")
            card_count += 1

    # Save quotes log
    log_path = output_dir / 'quotes.json'
    with open(log_path, 'w') as f:
        json.dump(all_quotes, f, indent=2)

    print(f"\n✅ Done! {card_count} quote cards saved to {output_dir}")
    print(f"📋 All quotes logged to {log_path}")


if __name__ == '__main__':
    main()
