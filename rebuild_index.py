#!/usr/bin/env python3
"""
rebuild_index.py — Rebuild site/index.html from existing posts only.
Does NOT call the API or generate new posts.
Posts are sorted newest-first using playlist_index from channel_videos.jsonl.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_search_index

SITE_DIR = Path("site")
POSTS_DIR = SITE_DIR / "posts"
MAPPING_FILE = Path("video_mapping.json")
CHANNEL_VIDEOS_FILE = Path("channel_videos.jsonl")


def load_video_mapping() -> dict:
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    return {}


def load_video_order() -> dict[str, int]:
    """Map video_id -> playlist_index from channel_videos.jsonl."""
    order: dict[str, int] = {}
    if not CHANNEL_VIDEOS_FILE.exists():
        return order
    with open(CHANNEL_VIDEOS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                vid_id = entry.get("id")
                idx = entry.get("playlist_index")
                if vid_id and idx is not None:
                    order[vid_id] = int(idx)
            except json.JSONDecodeError:
                pass
    return order


def collect_posts(video_mapping: dict) -> list[dict]:
    posts = []
    for post_file in sorted(POSTS_DIR.glob("*.html")):
        html = post_file.read_text(encoding="utf-8")
        title_match = re.search(r"<title>(.*?)</title>", html)
        title = title_match.group(1).strip() if title_match else post_file.stem

        slug = post_file.stem
        entry: dict = {"title": title, "filename": post_file.name}
        video_info = video_mapping.get(slug)
        if video_info and video_info.get("thumbnail_url"):
            entry["thumbnail_url"] = video_info["thumbnail_url"]
        posts.append(entry)
    return posts


def sort_posts(posts: list[dict], video_mapping: dict, video_order: dict[str, int]) -> list[dict]:
    def _key(p: dict) -> int:
        slug = p["filename"].replace(".html", "")
        vid_info = video_mapping.get(slug)
        if vid_info:
            vid_id = vid_info.get("video_id")
            if vid_id and vid_id in video_order:
                return video_order[vid_id]
        return 9999  # unmapped posts sort to the end

    if video_order:
        # playlist_index 1 = newest — sort ascending, unmapped posts last
        posts.sort(key=_key)
    else:
        posts.sort(key=lambda p: p["title"].lower())
    return posts


def write_index_html(posts: list[dict], search_index: list[dict]) -> None:
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


def main() -> None:
    video_mapping = load_video_mapping()
    video_order = load_video_order()

    posts = collect_posts(video_mapping)
    posts = sort_posts(posts, video_mapping, video_order)

    thumbnails_count = sum(1 for p in posts if p.get("thumbnail_url"))
    print(f"Collected {len(posts)} posts ({thumbnails_count} with thumbnails)")

    if posts:
        first = posts[0]
        last = posts[-1]
        print(f"First (newest): {first['filename']}")
        print(f"Last  (oldest): {last['filename']}")

    search_index = build_search_index.get_index_data()
    write_index_html(posts, search_index)
    build_search_index.build_index()

    print(f"Wrote site/index.html ({len(posts)} posts)")


if __name__ == "__main__":
    main()
