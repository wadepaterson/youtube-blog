#!/usr/bin/env python3
"""
build.py — Convert YouTube VTT transcripts to polished blog articles using Claude.

Usage:
    python build.py                  # Process all transcripts
    python build.py --limit 3        # Only generate 3 new posts (good for testing)
    python build.py --rebuild        # Rebuild all posts even if they already exist
    python build.py --rebuild --limit 3
"""

import json
import os
import re
import sys
import anthropic
from pathlib import Path
import build_search_index

TRANSCRIPTS_DIR = Path("transcripts")
SITE_DIR = Path("site")
POSTS_DIR = SITE_DIR / "posts"
MAPPING_FILE = Path("video_mapping.json")

client = anthropic.Anthropic()


# ---------------------------------------------------------------------------
# VTT cleaning
# ---------------------------------------------------------------------------

def clean_vtt(vtt_text: str) -> str:
    """Strip VTT timestamps and inline timing tags, deduplicate rolling captions."""
    lines = vtt_text.splitlines()
    processed = []

    for line in lines:
        # Skip header and metadata lines
        if re.match(r"^(WEBVTT|Kind:|Language:)", line):
            continue
        # Skip timestamp lines (e.g. "00:00:00.520 --> 00:00:03.429 …")
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3} -->", line):
            continue
        # Strip inline word-level timing tags like <00:00:01.079><c>word</c>
        line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
        line = re.sub(r"</?c>", "", line)
        line = line.strip()
        if line:
            processed.append(line)

    # VTT uses a rolling window — consecutive identical lines appear when the
    # caption window advances. Remove them so Claude sees clean prose.
    deduped = []
    prev = None
    for line in processed:
        if line != prev:
            deduped.append(line)
            prev = line

    return " ".join(deduped)


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a professional content writer who specialises in turning spoken-word \
transcripts into polished, engaging blog articles. You write with clarity, \
warmth, and authority. You restructure rambling speech into well-organised prose \
without losing the speaker's voice or key insights."""


def transcript_to_article_html(transcript: str, source_title: str) -> tuple[str, str]:
    """
    Call Claude to rewrite a raw transcript as a polished blog article.

    Returns:
        (title, html_body) — title is plain text; html_body is article HTML
        starting with <h1> and containing no <html>/<head>/<body> wrappers.
    """
    user_prompt = f"""\
The following is a raw transcript from a YouTube video originally titled:
"{source_title}"

Rewrite it as a polished blog article. Follow these rules exactly:

1. Output ONLY the article HTML — no code fences, no commentary, nothing else.
2. Start with an <h1> containing a compelling article title.
3. Follow with a strong intro paragraph.
4. Use <h2> subheadings to organise the body.
5. End with a conclusion paragraph.
6. Do NOT include <html>, <head>, <body>, or <style> tags.
7. Use <p>, <h2>, <ul>/<li>, <strong>, <em> as appropriate.

Raw transcript:
{transcript}"""

    html_body = ""
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            html_body += chunk

    # Strip accidental code fences Claude might add
    html_body = re.sub(r"^```(?:html)?\s*", "", html_body.strip())
    html_body = re.sub(r"\s*```$", "", html_body.strip())

    # Extract plain-text title from the first <h1>
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_body, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
    else:
        title = source_title  # fallback

    return title, html_body


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert an arbitrary string to a URL-safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


CTA_HTML = """\
  <section class="cta">
    <h2>Want to become a more confident speaker?</h2>
    <p>Get my free guide — 10 Public Speaking Mistakes and How to Fix Them</p>
    <a href="https://stan.store/wadepaterson" class="cta-btn">Get the Free Guide</a>
  </section>"""


def load_video_mapping() -> dict:
    """Load video_mapping.json if it exists, otherwise return empty dict."""
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    return {}


def write_post_html(title: str, html_body: str, filename: str, video_info: dict | None = None) -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    # Inject author line after the first </h1>
    html_body_with_author = re.sub(
        r"(</h1>\n)",
        r"\1<p class=\"post-author\">By Wade Paterson</p>\n",
        html_body,
        count=1,
    )

    thumbnail_html = ""
    if video_info:
        thumbnail_html = f"""    <a href="https://www.youtube.com/watch?v={video_info['video_id']}" target="_blank" rel="noopener noreferrer" class="post-thumbnail-link">
      <img src="{video_info['thumbnail_url']}" alt="{title}" class="post-thumbnail">
    </a>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <div class="post-banner"></div>
  <div class="container">
    <nav><a href="../index.html">&larr; All posts</a></nav>
{thumbnail_html}    <article>
{html_body_with_author}
    </article>
{CTA_HTML}
  </div>
</body>
</html>
"""
    (POSTS_DIR / filename).write_text(html, encoding="utf-8")


def write_index_html(posts: list[dict], search_index: list[dict]) -> None:
    SITE_DIR.mkdir(exist_ok=True)

    # Sort by playlist_index from channel_videos.jsonl (ascending; index 1 = newest)
    video_mapping = load_video_mapping()
    video_order: dict[str, int] = {}
    channel_videos_file = Path("channel_videos.jsonl")
    if channel_videos_file.exists():
        with open(channel_videos_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    vid_id = entry.get("id")
                    idx = entry.get("playlist_index")
                    if vid_id and idx is not None:
                        video_order[vid_id] = int(idx)
                except json.JSONDecodeError:
                    pass

    def _sort_key(p: dict) -> int:
        slug = p["filename"].replace(".html", "")
        vid_info = video_mapping.get(slug)
        if vid_info:
            vid_id = vid_info.get("video_id")
            if vid_id and vid_id in video_order:
                return video_order[vid_id]
        return 9999

    if video_order:
        posts = sorted(posts, key=_sort_key)
    else:
        posts = sorted(posts, key=lambda p: p["title"].lower())

    def _card(p: dict) -> str:
        thumbnail = p.get("thumbnail_url")
        img_html = (
            f'<img src="{thumbnail}" alt="" class="card-thumbnail" loading="lazy">'
            if thumbnail
            else '<div class="card-thumbnail"></div>'
        )
        return (
            f'        <li class="post-card">\n'
            f'          <a href="posts/{p["filename"]}" class="card-link">\n'
            f'            {img_html}\n'
            f'            <span class="card-title">{p["title"]}</span>\n'
            f'          </a>\n'
            f'        </li>'
        )

    items = "\n".join(_card(p) for p in posts)
    search_json = json.dumps(search_index, ensure_ascii=False, separators=(',', ':'))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wade Paterson — I help you speak with confidence.</title>
  <link rel="stylesheet" href="style.css">
  <style>
    .search-wrapper {{ position: relative; }}
    .search-dropdown {{
      display: none;
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-top: none;
      border-radius: 0 0 8px 8px;
      z-index: 100;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
      overflow: hidden;
    }}
    .dropdown-item {{
      padding: 0.7rem 1rem;
      font-family: 'Inter', -apple-system, sans-serif;
      font-size: 0.9rem;
      color: #e2e2e2;
      cursor: pointer;
      border-bottom: 1px solid #2a2a2a;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      transition: background 0.1s;
    }}
    .dropdown-item:last-child {{ border-bottom: none; }}
    .dropdown-item:hover, .dropdown-item.active {{
      background: #7B2FBE;
      color: #fff;
    }}
  </style>
</head>
<body>
  <a href="https://www.youtube.com/@wadepaterson" target="_blank" rel="noopener noreferrer" class="site-hero-link">
    <section class="site-hero" aria-label="Wade Paterson hero">
      <video class="hero-video" autoplay muted loop playsinline>
        <source src="banner-video.mp4" type="video/mp4">
      </video>
      <div class="hero-overlay"></div>
      <div class="hero-content">
        <h1 class="hero-title">WADE PATERSON</h1>
        <p class="hero-subtitle">YOUTUBE BLOG</p>
      </div>
    </section>
  </a>
  <div class="container container--wide">
    <header>
      <h1>Wade Paterson</h1>
      <p class="subtitle">I help you speak with confidence.</p>
    </header>
    <div class="search-wrapper">
      <input type="search" id="search-input" placeholder="Search posts\u2026" autocomplete="off" spellcheck="false">
      <div id="search-dropdown" class="search-dropdown"></div>
    </div>
    <div class="cta-cards">
      <a href="https://www.youtube.com/@wadepaterson" target="_blank" rel="noopener noreferrer" class="cta-card">
        <div class="cta-card__icon">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <circle cx="20" cy="20" r="19" stroke="#7B2FBE" stroke-width="2"/>
            <polygon points="16,13 30,20 16,27" fill="#7B2FBE"/>
          </svg>
        </div>
        <div class="cta-card__body">
          <h2 class="cta-card__heading">Watch on YouTube</h2>
          <p class="cta-card__sub">Impactful videos on public speaking &amp; communication</p>
        </div>
      </a>
      <a href="/speechready.html" class="cta-card">
        <div class="cta-card__icon">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <rect x="14" y="4" width="12" height="20" rx="6" fill="#7B2FBE"/>
            <path d="M8 22c0 6.627 5.373 12 12 12s12-5.373 12-12" stroke="#7B2FBE" stroke-width="2" stroke-linecap="round" fill="none"/>
            <line x1="20" y1="34" x2="20" y2="38" stroke="#7B2FBE" stroke-width="2" stroke-linecap="round"/>
            <circle cx="31" cy="9" r="3" fill="#7B2FBE"/>
            <line x1="31" y1="5" x2="31" y2="4" stroke="#7B2FBE" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="31" y1="13" x2="31" y2="14" stroke="#7B2FBE" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="27" y1="9" x2="26" y2="9" stroke="#7B2FBE" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="35" y1="9" x2="36" y2="9" stroke="#7B2FBE" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="cta-card__body">
          <h2 class="cta-card__heading">Try SpeechReady — Free</h2>
          <p class="cta-card__sub">Get your personalized speech prep plan in seconds</p>
        </div>
      </a>
    </div>
    <main>
      <ul class="post-grid">
{items}
      </ul>
    </main>
    <p class="search-no-results" id="search-no-results">No results found.</p>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/fuse.js@7/dist/fuse.min.js"></script>
  <script>
    const SEARCH_INDEX = {search_json};

    const fuse = new Fuse(SEARCH_INDEX, {{
      keys: ['title', 'excerpt'],
      threshold: 0.35,
      minMatchCharLength: 2,
    }});

    const input = document.getElementById('search-input');
    const dropdown = document.getElementById('search-dropdown');
    const grid = document.querySelector('.post-grid');
    const noResults = document.getElementById('search-no-results');
    const cards = Array.from(grid.querySelectorAll('.post-card'));

    let activeIndex = -1;
    let currentResults = [];

    function setActive(index) {{
      const items = dropdown.querySelectorAll('.dropdown-item');
      items.forEach(el => el.classList.remove('active'));
      activeIndex = index;
      if (index >= 0 && index < items.length) {{
        items[index].classList.add('active');
      }}
    }}

    function showDropdown(results) {{
      currentResults = results.slice(0, 8);
      activeIndex = -1;
      if (!currentResults.length) {{
        dropdown.style.display = 'none';
        return;
      }}
      dropdown.innerHTML = currentResults.map((r, i) =>
        `<div class="dropdown-item" data-index="${{i}}" data-url="${{r.item.url}}">${{r.item.title}}</div>`
      ).join('');
      dropdown.style.display = 'block';
      dropdown.querySelectorAll('.dropdown-item').forEach(item => {{
        item.addEventListener('mouseover', e => setActive(parseInt(e.currentTarget.dataset.index)));
        item.addEventListener('mousedown', e => {{
          e.preventDefault();
          window.location.href = e.currentTarget.dataset.url;
        }});
      }});
    }}

    function filterGrid(results) {{
      const matchedUrls = new Set(results.map(r => r.item.url));
      let visible = 0;
      cards.forEach(card => {{
        const url = card.querySelector('.card-link').getAttribute('href');
        if (matchedUrls.has(url)) {{
          card.style.display = '';
          visible++;
        }} else {{
          card.style.display = 'none';
        }}
      }});
      noResults.style.display = visible === 0 ? 'block' : 'none';
    }}

    input.addEventListener('input', () => {{
      const query = input.value.trim();
      if (!query) {{
        cards.forEach(c => c.style.display = '');
        noResults.style.display = 'none';
        dropdown.style.display = 'none';
        currentResults = [];
        return;
      }}
      const results = fuse.search(query);
      showDropdown(results);
      filterGrid(results);
    }});

    input.addEventListener('keydown', e => {{
      if (e.key === 'ArrowDown') {{
        e.preventDefault();
        setActive(Math.min(activeIndex + 1, currentResults.length - 1));
      }} else if (e.key === 'ArrowUp') {{
        e.preventDefault();
        setActive(Math.max(activeIndex - 1, -1));
      }} else if (e.key === 'Enter') {{
        const target = activeIndex >= 0 ? currentResults[activeIndex] : currentResults[0];
        if (target) window.location.href = target.item.url;
      }} else if (e.key === 'Escape') {{
        dropdown.style.display = 'none';
        activeIndex = -1;
      }}
    }});

    input.addEventListener('focus', () => {{
      if (currentResults.length) dropdown.style.display = 'block';
    }});

    document.addEventListener('click', e => {{
      if (!e.target.closest('.search-wrapper')) {{
        dropdown.style.display = 'none';
      }}
    }});
  </script>
</body>
</html>
"""
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")


def write_style_css() -> None:
    """Write style.css only if it does not already exist (hand-crafted file takes precedence)."""
    SITE_DIR.mkdir(exist_ok=True)
    css_path = SITE_DIR / "style.css"
    if css_path.exists():
        return
    css = """\
/* ------------------------------------------------------------------ */
/* Reset                                                               */
/* ------------------------------------------------------------------ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* ------------------------------------------------------------------ */
/* Design tokens                                                       */
/* ------------------------------------------------------------------ */
:root {
  --bg:           #fafaf8;
  --surface:      #ffffff;
  --text:         #1a1a1a;
  --text-muted:   #6b7280;
  --accent:       #2563eb;
  --accent-hover: #1d4ed8;
  --border:       #e5e7eb;

  --font-sans:  -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-serif: Georgia, "Times New Roman", serif;

  --measure:    680px;   /* comfortable reading width */
  --lh:         1.8;
}

/* ------------------------------------------------------------------ */
/* Base                                                                */
/* ------------------------------------------------------------------ */
html { font-size: 18px; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-serif);
  line-height: var(--lh);
  padding: 2.5rem 1.25rem 4rem;
}

.container {
  max-width: var(--measure);
  margin: 0 auto;
}

a {
  color: var(--accent);
  text-decoration: none;
}
a:hover { text-decoration: underline; color: var(--accent-hover); }

/* ------------------------------------------------------------------ */
/* Navigation (back link on post pages)                                */
/* ------------------------------------------------------------------ */
nav {
  margin-bottom: 2.5rem;
  font-family: var(--font-sans);
  font-size: 0.875rem;
  color: var(--text-muted);
}

/* ------------------------------------------------------------------ */
/* Site header (index page)                                            */
/* ------------------------------------------------------------------ */
header {
  padding-bottom: 2rem;
  margin-bottom: 2.5rem;
  border-bottom: 2px solid var(--border);
}

header h1 {
  font-family: var(--font-sans);
  font-size: 2.25rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 0.4rem;
}

.subtitle {
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 1rem;
}

/* ------------------------------------------------------------------ */
/* Post list (index page)                                              */
/* ------------------------------------------------------------------ */
.post-list {
  list-style: none;
  display: flex;
  flex-direction: column;
}

.post-list li {
  padding: 1rem 0;
  border-bottom: 1px solid var(--border);
}
.post-list li:first-child { border-top: 1px solid var(--border); }

.post-list a {
  font-family: var(--font-sans);
  font-size: 1.05rem;
  font-weight: 500;
  color: var(--text);
  transition: color 0.15s;
}
.post-list a:hover { color: var(--accent); text-decoration: none; }

/* ------------------------------------------------------------------ */
/* Article (post pages)                                                */
/* ------------------------------------------------------------------ */
article h1 {
  font-family: var(--font-sans);
  font-size: 2rem;
  font-weight: 800;
  line-height: 1.2;
  letter-spacing: -0.02em;
  margin-bottom: 1.75rem;
}

article h2 {
  font-family: var(--font-sans);
  font-size: 1.3rem;
  font-weight: 700;
  margin-top: 2.5rem;
  margin-bottom: 0.75rem;
  color: #111;
}

article p { margin-bottom: 1.25rem; }

/* Lead paragraph — slightly larger */
article p:first-of-type {
  font-size: 1.15rem;
  color: #374151;
}

article ul, article ol {
  margin: 0 0 1.25rem 1.75rem;
}
article li { margin-bottom: 0.35rem; }

article strong { font-weight: 700; }
article em     { font-style: italic; }

/* ------------------------------------------------------------------ */
/* Post thumbnail (post pages)                                         */
/* ------------------------------------------------------------------ */
.post-thumbnail-link {
  display: block;
  margin-bottom: 2rem;
}

.post-thumbnail {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 6px;
}

/* ------------------------------------------------------------------ */
/* Card thumbnail (index page)                                         */
/* ------------------------------------------------------------------ */
.card-link {
  display: flex;
  align-items: center;
  gap: 1rem;
  color: var(--text);
  text-decoration: none;
}
.card-link:hover { color: var(--accent); text-decoration: none; }
.card-link:hover .card-title { color: var(--accent); }

.card-thumbnail {
  flex-shrink: 0;
  width: 120px;
  height: 68px;
  object-fit: cover;
  border-radius: 4px;
  background: var(--border);
}

.card-title {
  font-family: var(--font-sans);
  font-size: 1.05rem;
  font-weight: 500;
  color: var(--text);
  transition: color 0.15s;
}

/* ------------------------------------------------------------------ */
/* Responsive                                                          */
/* ------------------------------------------------------------------ */
@media (max-width: 600px) {
  html { font-size: 16px; }
  article h1 { font-size: 1.65rem; }
  header h1  { font-size: 1.75rem; }
  .card-thumbnail { width: 80px; height: 45px; }
}
"""
    (SITE_DIR / "style.css").write_text(css, encoding="utf-8")


# ---------------------------------------------------------------------------
# Thumbnail patching (for already-built posts)
# ---------------------------------------------------------------------------

def patch_thumbnails(video_mapping: dict) -> None:
    """
    Inject thumbnails into existing post HTML files without regenerating content.
    Safe to re-run — skips posts that already contain a thumbnail.
    """
    patched = 0
    skipped = 0
    for slug, video_info in video_mapping.items():
        post_file = POSTS_DIR / f"{slug}.html"
        if not post_file.exists():
            continue

        html = post_file.read_text(encoding="utf-8")

        # Skip if thumbnail already present
        if "post-thumbnail-link" in html:
            skipped += 1
            continue

        thumbnail_block = (
            f'    <a href="https://www.youtube.com/watch?v={video_info["video_id"]}"'
            f' target="_blank" rel="noopener noreferrer" class="post-thumbnail-link">\n'
            f'      <img src="{video_info["thumbnail_url"]}" class="post-thumbnail"'
            f' alt="" loading="lazy">\n'
            f'    </a>\n'
        )

        # Insert before <article>
        patched_html = html.replace("    <article>", thumbnail_block + "    <article>", 1)
        if patched_html == html:
            continue  # replace had no effect

        post_file.write_text(patched_html, encoding="utf-8")
        patched += 1

    print(f"Thumbnails: {patched} posts patched, {skipped} already had thumbnails.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_limit() -> int | None:
    """Return the integer value of --limit N, or None if not provided."""
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--limit" and i < len(sys.argv):
            try:
                return int(sys.argv[i + 1])
            except (IndexError, ValueError):
                print("Usage: --limit <number>")
                sys.exit(1)
    return None


def main() -> None:
    rebuild        = "--rebuild" in sys.argv
    add_thumbnails = "--add-thumbnails" in sys.argv
    limit          = _parse_limit()

    vtt_files = sorted(TRANSCRIPTS_DIR.glob("*.vtt"))
    if not vtt_files:
        print("No .vtt files found in transcripts/")
        return

    print(f"Found {len(vtt_files)} transcripts{f' (limiting to {limit})' if limit else ''}.")

    POSTS_DIR.mkdir(exist_ok=True)
    SITE_DIR.mkdir(exist_ok=True)
    write_style_css()
    print("Wrote site/style.css")

    video_mapping = load_video_mapping()
    if video_mapping:
        print(f"Loaded thumbnail mapping for {len(video_mapping)} posts.")

    if add_thumbnails:
        patch_thumbnails(video_mapping)

    posts: list[dict] = []
    skipped = 0
    generated = 0

    for vtt_path in vtt_files:
        if limit is not None and generated >= limit:
            break
        # Derive a human-readable source title from the filename
        source_title = vtt_path.stem
        if source_title.endswith(".en"):
            source_title = source_title[:-3]

        slug = slugify(source_title)
        post_filename = f"{slug}.html"
        post_file = POSTS_DIR / post_filename
        video_info = video_mapping.get(slug)

        # Skip already-built posts unless --rebuild
        if post_file.exists() and not rebuild:
            existing = post_file.read_text(encoding="utf-8")
            title_match = re.search(r"<title>(.*?)</title>", existing)
            title = title_match.group(1) if title_match else source_title
            post_entry: dict = {"title": title, "filename": post_filename}
            if video_info:
                post_entry["thumbnail_url"] = video_info["thumbnail_url"]
            posts.append(post_entry)
            skipped += 1
            continue

        print(f"\n→ {source_title}")

        vtt_text = vtt_path.read_text(encoding="utf-8", errors="replace")
        transcript = clean_vtt(vtt_text)

        if len(transcript.split()) < 50:
            print("  [skip] Transcript too short — skipping.")
            continue

        try:
            title, html_body = transcript_to_article_html(transcript, source_title)
            write_post_html(title, html_body, post_filename, video_info)
            post_entry = {"title": title, "filename": post_filename}
            if video_info:
                post_entry["thumbnail_url"] = video_info["thumbnail_url"]
            posts.append(post_entry)
            generated += 1
            print(f'  ✓ "{title}"')
        except anthropic.APIError as exc:
            print(f"  [API error] {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] {exc}")

    # Sort newest-first using playlist_index from channel_videos.jsonl
    channel_videos_file = Path("channel_videos.jsonl")
    video_order: dict[str, int] = {}
    if channel_videos_file.exists():
        with open(channel_videos_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    vid_id = entry.get("id")
                    idx = entry.get("playlist_index")
                    if vid_id and idx is not None:
                        video_order[vid_id] = int(idx)
                except json.JSONDecodeError:
                    pass

    def _sort_key(p: dict) -> int:
        slug = p["filename"].replace(".html", "")
        vid_info = video_mapping.get(slug)
        if vid_info:
            vid_id = vid_info.get("video_id")
            if vid_id and vid_id in video_order:
                return video_order[vid_id]
        return 9999

    if video_order:
        posts.sort(key=_sort_key)
    else:
        # Fallback: alphabetical order
        posts.sort(key=lambda p: p["title"].lower())

    search_index = build_search_index.get_index_data()
    write_index_html(posts, search_index)
    build_search_index.build_index()

    print(f"\nDone. {generated} new posts generated, {skipped} skipped (already built).")
    print(f"Index: site/index.html  ({len(posts)} total posts)")


if __name__ == "__main__":
    main()
