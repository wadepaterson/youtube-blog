#!/usr/bin/env python3
"""
map_thumbnails.py — Match YouTube videos to blog posts using fuzzy title matching.

Usage:
    python map_thumbnails.py

Reads:  channel_videos.jsonl  (yt-dlp --flat-playlist --dump-json output)
Writes: video_mapping.json    ({slug: {video_id, thumbnail_url, youtube_title}})
"""

import json
import re
from pathlib import Path

from thefuzz import process

POSTS_DIR = Path("site/posts")
VIDEOS_FILE = Path("channel_videos.jsonl")
MAPPING_FILE = Path("video_mapping.json")

MATCH_THRESHOLD = 60  # minimum fuzz score to accept a match


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def main() -> None:
    if not VIDEOS_FILE.exists():
        print(f"Error: {VIDEOS_FILE} not found.")
        print("Run: yt-dlp --flat-playlist --dump-json 'https://www.youtube.com/@wadepaterson' > channel_videos.jsonl")
        return

    # Load videos from JSONL
    videos = []
    with open(VIDEOS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("id") and d.get("title"):
                videos.append({"id": d["id"], "title": d["title"]})

    print(f"Loaded {len(videos)} videos from {VIDEOS_FILE}")

    # Collect all post slugs
    post_files = sorted(POSTS_DIR.glob("*.html"))
    post_slugs = [p.stem for p in post_files]

    if not post_slugs:
        print(f"No posts found in {POSTS_DIR}. Run build.py first.")
        return

    print(f"Found {len(post_slugs)} posts in {POSTS_DIR}")
    print()

    mapping: dict = {}
    no_match: list = []

    for video in videos:
        video_id = video["id"]
        youtube_title = video["title"]
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

        # Slugify the video title to compare against post slugs
        video_slug = slugify(youtube_title)

        result = process.extractOne(video_slug, post_slugs)
        if result is None:
            no_match.append(youtube_title)
            continue

        best_slug, score = result[0], result[1]

        if score >= MATCH_THRESHOLD:
            # If multiple videos match the same slug, keep the highest-scoring one
            if best_slug not in mapping or score > mapping[best_slug]["match_score"]:
                mapping[best_slug] = {
                    "video_id": video_id,
                    "thumbnail_url": thumbnail_url,
                    "youtube_title": youtube_title,
                    "match_score": score,
                }
            print(f"  {score:3d}%  {youtube_title[:55]:55s} → {best_slug}")
        else:
            no_match.append(youtube_title)
            print(f"  {score:3d}%  [SKIP] {youtube_title}")

    # Strip match_score from final output (it's internal bookkeeping)
    clean_mapping = {
        slug: {k: v for k, v in info.items() if k != "match_score"}
        for slug, info in mapping.items()
    }

    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_mapping, f, indent=2, ensure_ascii=False)

    print()
    print(f"Matched:   {len(mapping)}")
    print(f"No match:  {len(no_match)}")
    print(f"Wrote {MAPPING_FILE}")


if __name__ == "__main__":
    main()
