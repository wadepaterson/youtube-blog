#!/usr/bin/env python3
"""
build_search_index.py — Build a Fuse.js search index from post HTML files.
Writes site/search-index.json used by the homepage search bar.
"""

import json
import re
from pathlib import Path

SITE_DIR = Path("site")
POSTS_DIR = SITE_DIR / "posts"
OUTPUT_FILE = SITE_DIR / "search-index.json"


def strip_tags(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", html)
    text = (
        text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def extract_post_data(html_path: Path) -> dict | None:
    html = html_path.read_text(encoding="utf-8")

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    if not title_match:
        return None
    title = title_match.group(1).strip()

    article_match = re.search(r"<article>(.*?)</article>", html, re.IGNORECASE | re.DOTALL)
    if article_match:
        article_html = article_match.group(1)
        # Strip h1 and author line — they're redundant with title
        article_html = re.sub(r"<h1[^>]*>.*?</h1>", "", article_html, flags=re.IGNORECASE | re.DOTALL)
        article_html = re.sub(r'<p[^>]*class="post-author"[^>]*>.*?</p>', "", article_html, flags=re.IGNORECASE | re.DOTALL)
        body_text = strip_tags(article_html)
    else:
        body_text = ""

    excerpt = body_text[:200].rstrip()
    if len(body_text) > 200:
        excerpt += "…"

    return {
        "title": title,
        "excerpt": excerpt,
        "url": f"posts/{html_path.name}",
    }


def get_index_data() -> list[dict]:
    """Return the search index as a list of dicts (without writing to disk)."""
    post_files = sorted(POSTS_DIR.glob("*.html"))
    index = []
    for post_file in post_files:
        data = extract_post_data(post_file)
        if data:
            index.append(data)
    return index


def build_index() -> None:
    index = get_index_data()
    if not index:
        print("No post HTML files found in site/posts/")
        return

    OUTPUT_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Search index written: {OUTPUT_FILE} ({len(index)} posts)")


if __name__ == "__main__":
    build_index()
