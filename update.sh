#!/bin/bash
set -e

# Check for ANTHROPIC_API_KEY
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set."
  echo "Export it first: export ANTHROPIC_API_KEY=your_key_here"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATE=$(date +"%Y-%m-%d")

echo "========================================"
echo " Blog refresh - $DATE"
echo "========================================"

# Step 1: Download new transcripts
echo ""
echo "[1/6] Downloading transcripts for 20 most recent videos..."
yt-dlp \
  --write-auto-sub \
  --sub-lang en \
  --skip-download \
  --playlist-end 20 \
  -o "transcripts/%(title)s.%(ext)s" \
  "https://www.youtube.com/@wadepaterson/videos"
echo "      Done."

# Step 2: Refresh channel_videos.jsonl
echo ""
echo "[2/6] Refreshing channel_videos.jsonl with latest video metadata..."
yt-dlp \
  --flat-playlist \
  --playlist-end 20 \
  --print-json \
  "https://www.youtube.com/@wadepaterson/videos" > channel_videos_new.jsonl

# Merge: keep existing entries not in the new batch, prepend the new ones
python3 - <<'PYEOF'
import json, os

new_file = "channel_videos_new.jsonl"
existing_file = "channel_videos.jsonl"

with open(new_file) as f:
    new_entries = [json.loads(line) for line in f if line.strip()]

new_ids = {e["id"] for e in new_entries}

existing_entries = []
if os.path.exists(existing_file):
    with open(existing_file) as f:
        for line in f:
            if line.strip():
                entry = json.loads(line)
                if entry["id"] not in new_ids:
                    existing_entries.append(entry)

merged = new_entries + existing_entries

with open(existing_file, "w") as f:
    for entry in merged:
        f.write(json.dumps(entry) + "\n")

print(f"      channel_videos.jsonl updated: {len(new_entries)} new + {len(existing_entries)} existing = {len(merged)} total")
os.remove(new_file)
PYEOF
echo "      Done."

# Step 3: Update thumbnail mapping
echo ""
echo "[3/6] Running map_thumbnails.py..."
python3 map_thumbnails.py
echo "      Done."

# Step 4: Generate new blog posts
echo ""
echo "[4/6] Running build.py to generate new posts..."
python3 build.py
echo "      Done."

# Step 5: Regenerate homepage (newest-first)
echo ""
echo "[5/6] Running rebuild_index.py..."
python3 rebuild_index.py
echo "      Done."

# Step 6: Update search index
echo ""
echo "[6/6] Running build_search_index.py..."
python3 build_search_index.py
echo "      Done."

# Git commit and push
echo ""
echo "[git] Staging all changes..."
git add -A

if git diff --cached --quiet; then
  echo "[git] Nothing to commit - blog is already up to date."
else
  echo "[git] Committing..."
  git commit -m "Blog refresh - $DATE"
  echo "[git] Pushing to origin..."
  git push
  echo "[git] Done."
fi

echo ""
echo "========================================"
echo " Blog refresh complete!"
echo "========================================"
