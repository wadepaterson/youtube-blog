#!/usr/bin/env python3
"""
analyze_podcast.py — Send all Real Leverage podcast transcripts to Claude
for a comprehensive audit report saved as both Markdown and HTML.

Usage:
    python analyze_podcast.py
"""

import re
import time
import anthropic
from pathlib import Path

TRANSCRIPTS_DIR = Path.home() / "realleverage"
OUTPUT_MD   = Path.home() / "realleverage_audit.md"
OUTPUT_HTML = Path.home() / "realleverage_audit.html"

client = anthropic.Anthropic()


# ---------------------------------------------------------------------------
# VTT cleaning (same logic as build.py)
# ---------------------------------------------------------------------------

def clean_vtt(vtt_text: str) -> str:
    """Strip VTT timestamps and inline timing tags, deduplicate rolling captions."""
    lines = vtt_text.splitlines()
    processed = []

    for line in lines:
        if re.match(r"^(WEBVTT|Kind:|Language:)", line):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3} -->", line):
            continue
        line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
        line = re.sub(r"</?c>", "", line)
        line = line.strip()
        if line:
            processed.append(line)

    deduped = []
    prev = None
    for line in processed:
        if line != prev:
            deduped.append(line)
            prev = line

    return " ".join(deduped)


def episode_title(vtt_path: Path) -> str:
    """Extract a clean episode title from the filename."""
    stem = vtt_path.stem
    if stem.endswith(".en"):
        stem = stem[:-3]
    return stem


# ---------------------------------------------------------------------------
# Build combined transcript blob
# ---------------------------------------------------------------------------

def build_combined_transcript() -> tuple[list[str], list[str]]:
    """Returns (sections, titles) where sections is a list of per-episode strings."""
    vtt_files = sorted(TRANSCRIPTS_DIR.glob("*.vtt"))
    if not vtt_files:
        raise FileNotFoundError(f"No .vtt files found in {TRANSCRIPTS_DIR}")

    print(f"Found {len(vtt_files)} VTT files.")

    sections = []
    titles = []
    for i, vtt_path in enumerate(vtt_files, 1):
        title = episode_title(vtt_path)
        titles.append(title)
        vtt_text = vtt_path.read_text(encoding="utf-8", errors="replace")
        transcript = clean_vtt(vtt_text)
        sections.append(f"## Episode {i}: {title}\n\n{transcript}")
        print(f"  [{i:02d}] {title}")

    return sections, titles


# ---------------------------------------------------------------------------
# API calls — two-batch approach to stay under 200k token limit
# ---------------------------------------------------------------------------

BATCH_PROMPT = """\
You are a senior podcast strategist auditing the Real Leverage podcast. \
Below are transcripts for episodes {start}–{end} of {total} total episodes. \
Read them carefully and produce detailed structured analysis notes covering:

1. Content themes, topics, and notable gaps you observe
2. Episode format and structure patterns (intros, length, closings)
3. Host performance — energy, question quality, active listening, pacing, filler words
4. Guest quality, variety, and preparation level
5. Title effectiveness (click-worthiness, hooks, formulas)
6. Distribution and SEO opportunities you notice
7. Standout moments, quotes, or episodes — and weak spots
8. Any patterns in monetisation, CTAs, or sponsorship mentions

Be specific. Reference episode titles and actual content. These notes will be \
combined with analysis of the other half of episodes to write a full audit report.

---

{transcripts}
"""

SYNTHESIS_PROMPT = """\
You are a senior podcast strategist. You have analysed both halves of the \
Real Leverage podcast catalogue ({total} episodes total). Below are your \
detailed analysis notes from both batches.

## Batch 1 Analysis Notes (Episodes 1–{batch1_end})
{notes1}

## Batch 2 Analysis Notes (Episodes {batch2_start}–{total})
{notes2}

---

Now produce the final comprehensive audit report in Markdown. Use the \
following exact structure:

## Executive Summary
A 3–5 paragraph overview of the podcast's current state: its positioning, \
strengths, weaknesses, and the single most important opportunity the host \
should act on immediately.

---

## 1. Content Analysis
- **Core themes and topics covered** across the catalogue
- **Topic gaps** — important subjects the audience likely wants that are absent
- **Content patterns** — what formats, angles, and framings recur
- **Content quality distribution** — which episodes are strongest and why; which fall flat

---

## 2. Episode Format & Structure Assessment
- Typical episode structure (intro, body, outro patterns)
- Episode length analysis — are episodes too long, too short, inconsistent?
- Cold open effectiveness
- Transitions and segue quality
- Closing / call-to-action consistency

---

## 3. Host Performance Analysis
- **Energy and enthusiasm** — consistency across episodes
- **Question quality** — are questions sharp, follow-up-driven, or generic?
- **Active listening** — does the host pick up on what guests say and dig in?
- **Pacing and conversational flow**
- **Filler words and speaking habits** — any patterns worth addressing?
- **Host credibility and authority** — does the host position themselves well?

---

## 4. Guest Quality & Variety Assessment
- Who has been on the show? What types of guests?
- Guest calibre — are guests credible, specific, and story-rich?
- **Guest variety gaps** — types of guests missing that would strengthen the show
- How well are guests prepared / briefed?
- Most valuable guests and why

---

## 5. Title & Thumbnail Strategy Assessment
Based on the episode titles, assess:
- Clarity and click-worthiness of titles
- Use of numbers, power words, and emotional hooks
- Title consistency and branding
- Patterns in what works vs. what is generic
- Recommendations for stronger title formulas

---

## 6. Distribution & Discoverability Gaps
- SEO and keyword opportunities being missed
- Cross-promotion and repurposing gaps
- Clip and short-form content opportunities
- Platform diversification

---

## 7. Competitor Positioning
- Where does Real Leverage sit relative to other entrepreneurship / sales / personal development podcasts?
- What is the show's differentiated angle (or lack thereof)?
- What adjacent shows are winning that Real Leverage should study?

---

## 8. The 50 Recommendations

List exactly 50 specific, numbered, actionable recommendations. Group them \
under these seven sub-headings:

### A. Content Strategy (Recommendations 1–10)
### B. Host Skills (Recommendations 11–20)
### C. Guest Experience (Recommendations 21–27)
### D. Production Quality (Recommendations 28–33)
### E. Growth & Distribution (Recommendations 34–40)
### F. Monetization (Recommendations 41–45)
### G. Social Media & Clips (Recommendations 46–50)

Each recommendation must be a single, concrete, immediately actionable item — \
not a vague suggestion. Example of bad: "Improve your questions." \
Example of good: "Before each recording, write 3 follow-up questions per \
guest topic that start with 'What happened next…' or 'Walk me through…' \
to force specificity."

---

End with a **Priority Action Plan** — the top 5 recommendations the host \
should execute in the next 30 days, with a one-sentence rationale for each.
"""


def call_api(prompt: str, max_tokens: int, label: str) -> str:
    """Call Claude with retry-on-rate-limit. Waits 240s between retries."""
    wait = 240
    for attempt in range(6):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            if attempt == 5:
                raise
            print(f"  [{label}] Rate limited. Waiting {wait}s before retry {attempt + 2}/6...")
            time.sleep(wait)
            wait = min(wait + 120, 600)


def analyze_batch(transcripts: str, batch_num: int, start: int, end: int, total: int) -> str:
    print(f"\n  Batch {batch_num}: episodes {start}–{end} ({end - start + 1} episodes)...")
    prompt = BATCH_PROMPT.format(
        start=start,
        end=end,
        total=total,
        transcripts=transcripts,
    )
    return call_api(prompt, max_tokens=6000, label=f"batch{batch_num}")


def synthesize_report(notes1: str, notes2: str, total: int, batch1_end: int) -> str:
    print("\n  Synthesis: combining both batches into final report...")
    prompt = SYNTHESIS_PROMPT.format(
        total=total,
        batch1_end=batch1_end,
        batch2_start=batch1_end + 1,
        notes1=notes1,
        notes2=notes2,
    )
    return call_api(prompt, max_tokens=8000, label="synthesis")


def generate_audit(sections: list[str], n_episodes: int) -> str:
    """Split transcripts into two batches, analyse each, then synthesise."""
    print(f"\nProcessing {n_episodes} transcripts in 2 batches to stay under token limit...")

    mid = n_episodes // 2
    batch1_text = "\n\n---\n\n".join(sections[:mid])
    batch2_text = "\n\n---\n\n".join(sections[mid:])

    notes1 = analyze_batch(batch1_text, 1, 1, mid, n_episodes)
    print("\n  Waiting 240s for rate limit window to reset before batch 2...")
    time.sleep(240)
    notes2 = analyze_batch(batch2_text, 2, mid + 1, n_episodes, n_episodes)
    print("\n  Waiting 240s for rate limit window to reset before synthesis...")
    time.sleep(240)
    report = synthesize_report(notes1, notes2, n_episodes, mid)
    return report


# ---------------------------------------------------------------------------
# Markdown → HTML conversion (simple but clean)
# ---------------------------------------------------------------------------

def md_to_html_body(md: str) -> str:
    """
    Lightweight Markdown-to-HTML converter for the report.
    Handles headings, bold, italic, lists, horizontal rules, and paragraphs.
    """
    html_lines = []
    lines = md.splitlines()
    in_ul = False
    in_ol = False
    buffer = []

    def flush_paragraph():
        nonlocal buffer
        if buffer:
            text = " ".join(buffer).strip()
            if text:
                html_lines.append(f"<p>{inline(text)}</p>")
            buffer = []

    def close_list():
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    def inline(text: str) -> str:
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        # Italic
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        # Inline code
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        return text

    for line in lines:
        # Headings
        h_match = re.match(r"^(#{1,6})\s+(.*)", line)
        if h_match:
            flush_paragraph()
            close_list()
            level = len(h_match.group(1))
            text = inline(h_match.group(2).strip())
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^---+$", line.strip()):
            flush_paragraph()
            close_list()
            html_lines.append("<hr>")
            continue

        # Unordered list
        ul_match = re.match(r"^[\-\*]\s+(.*)", line)
        if ul_match:
            flush_paragraph()
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{inline(ul_match.group(1).strip())}</li>")
            continue

        # Ordered list
        ol_match = re.match(r"^\d+\.\s+(.*)", line)
        if ol_match:
            flush_paragraph()
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{inline(ol_match.group(1).strip())}</li>")
            continue

        # Blank line
        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        # Regular text — accumulate into paragraph
        buffer.append(line.strip())

    flush_paragraph()
    close_list()
    return "\n".join(html_lines)


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Real Leverage Podcast — Comprehensive Audit Report</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:        #0f0f13;
      --surface:   #1a1a24;
      --surface2:  #22222f;
      --border:    #2e2e40;
      --text:      #e8e8f0;
      --muted:     #8888a8;
      --accent:    #7b5ea7;
      --accent2:   #a078d0;
      --gold:      #c9a84c;
      --green:     #4caf7d;
      --red:       #e05252;
    }}

    html {{ font-size: 17px; scroll-behavior: smooth; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.75;
      padding: 2rem 1.25rem 5rem;
    }}

    .wrapper {{
      max-width: 820px;
      margin: 0 auto;
    }}

    /* Cover */
    .cover {{
      text-align: center;
      padding: 3.5rem 0 2.5rem;
      border-bottom: 2px solid var(--border);
      margin-bottom: 3rem;
    }}

    .cover .badge {{
      display: inline-block;
      background: var(--accent);
      color: #fff;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      padding: 0.3em 0.9em;
      border-radius: 999px;
      margin-bottom: 1.2rem;
    }}

    .cover h1 {{
      font-size: 2.5rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1.15;
      color: #fff;
      margin-bottom: 0.6rem;
    }}

    .cover .subtitle {{
      color: var(--muted);
      font-size: 1rem;
    }}

    /* Headings */
    h1 {{ font-size: 2rem; font-weight: 800; color: #fff; margin: 2.5rem 0 1rem; letter-spacing: -0.02em; }}
    h2 {{
      font-size: 1.45rem;
      font-weight: 700;
      color: var(--accent2);
      margin: 2.8rem 0 0.8rem;
      padding-bottom: 0.4rem;
      border-bottom: 1px solid var(--border);
    }}
    h3 {{
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--gold);
      margin: 2rem 0 0.6rem;
    }}
    h4 {{ font-size: 1rem; font-weight: 600; color: var(--muted); margin: 1.5rem 0 0.4rem; }}

    /* Body text */
    p {{ margin-bottom: 1rem; color: var(--text); }}

    strong {{ color: #fff; font-weight: 700; }}
    em {{ color: var(--accent2); font-style: italic; }}
    code {{
      font-family: "SF Mono", Menlo, monospace;
      font-size: 0.85em;
      background: var(--surface2);
      padding: 0.15em 0.4em;
      border-radius: 4px;
      color: var(--gold);
    }}

    /* Lists */
    ul, ol {{
      margin: 0.5rem 0 1rem 1.6rem;
    }}
    li {{
      margin-bottom: 0.45rem;
    }}
    ol li {{
      color: var(--text);
    }}
    ol li::marker {{
      color: var(--accent2);
      font-weight: 700;
    }}
    ul li::marker {{
      color: var(--accent);
    }}

    /* HR */
    hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 2.5rem 0;
    }}

    /* Section cards for major sections */
    h2 + p, h2 + ul, h2 + ol {{
      /* Slight indent on first element after an h2 */
    }}

    /* Priority action plan callout */
    h2:last-of-type {{
      color: var(--green);
    }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 8px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}

    /* Print */
    @media print {{
      body {{ background: #fff; color: #111; }}
      .cover .badge {{ background: #555; }}
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="cover">
      <div class="badge">Internal Document</div>
      <h1>Real Leverage Podcast<br>Comprehensive Audit Report</h1>
      <p class="subtitle">Generated by Claude &mdash; {n_episodes} Episodes Analysed</p>
    </div>
    <main>
{body}
    </main>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sections, titles = build_combined_transcript()
    n = len(titles)

    report_md = generate_audit(sections, n)

    print("\nSaving Markdown report...")
    OUTPUT_MD.write_text(report_md, encoding="utf-8")
    print(f"  -> {OUTPUT_MD}")

    print("Converting to HTML...")
    body_html = md_to_html_body(report_md)
    # Indent body content for readability
    indented_body = "\n".join("      " + line if line.strip() else line for line in body_html.splitlines())
    full_html = HTML_TEMPLATE.format(n_episodes=n, body=indented_body)
    OUTPUT_HTML.write_text(full_html, encoding="utf-8")
    print(f"  -> {OUTPUT_HTML}")

    print("\nDone.")


if __name__ == "__main__":
    main()
