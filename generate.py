#!/usr/bin/env python3
"""
Daily Reads for Xteink X3 (CrossPoint)

Builds TWO daily EPUBs and publishes an OPDS catalog to docs/ for GitHub Pages:
  1. news-YYYY-MM-DD.epub   — World in 5 min / Arsenal & Sports / AI News / Vision & Multimodal
  2. study-day-NN.epub      — next lesson from syllabus.json, tracked in state.json

Claude (ANTHROPIC_API_KEY) writes the news briefings and study lessons.
Without a key: news falls back to raw article summaries; study is skipped.
"""

import os
import re
import json
import html
import datetime
import xml.sax.saxutils as sx

import feedparser
from ebooklib import epub

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
ISSUES_DIR = os.path.join(DOCS, "issues")
SITE_BASE = os.environ.get("SITE_BASE", "https://rkmac41-ui.github.io/daily-reads")
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"

KEEP_NEWS = 14    # days of news back-issues kept in catalog
KEEP_STUDY = 30   # study back-issues kept

# ─────────────────────────────────────────────────────────────
# News sections — edit feeds freely
# ─────────────────────────────────────────────────────────────
SECTIONS = [
    {
        "title": "World in 5 Minutes",
        "feeds": [
            "http://feeds.bbci.co.uk/news/world/rss.xml",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.npr.org/1004/rss.xml",
        ],
        "max_items": 15,
        "style": (
            "Condense into a tight 5-minute world briefing (~600 words). Lead with the most "
            "consequential geopolitical stories, group related items, and give just enough "
            "context to understand why each matters. Skip celebrity/crime filler."
        ),
    },
    {
        "title": "Arsenal & Sports",
        "feeds": [
            "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
            "https://arseblog.com/feed/",
            "https://feeds.bbci.co.uk/sport/rss.xml",
        ],
        "max_items": 12,
        "style": (
            "The reader is an Arsenal supporter (also follows the Knicks/NBA). Lead with Arsenal "
            "news — matches, transfers, injuries — with a fan's voice, then a quick sweep of the "
            "biggest general sports stories. ~400 words."
        ),
    },
    {
        "title": "AI News & How People Use It",
        "feeds": [
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
            "https://simonwillison.net/atom/everything/",
            "https://www.oneusefulthing.org/feed",
        ],
        "max_items": 15,
        "style": (
            "Reader is a senior PM. Two parts: (1) the day's significant AI industry news — model "
            "releases, business moves, research that matters; (2) 'AI in practice' — concrete ways "
            "people are applying AI at work and in daily life, drawn from the items. ~700 words."
        ),
    },
    {
        "title": "Vision & Multimodal",
        "feeds": [
            "https://rss.arxiv.org/rss/cs.CV",
            "https://huggingface.co/blog/feed.xml",
            "https://blog.roboflow.com/rss/",
        ],
        "max_items": 20,
        "style": (
            "Reader is a PM who evaluates, classifies, and generates images at work but is NEW to "
            "computer vision (knows CLIP only briefly). Pick the 4-6 most relevant/important items, "
            "explain each accessibly — define jargon on first use, use analogies — and say why a "
            "PM working on image products should care. Skip incremental papers. ~700 words."
        ),
    },
]

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def clean(text, limit=900):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit] + ("…" if len(text) > limit else "")

def fetch(feeds, max_items, lookback_hours=26):
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=lookback_hours)
    items, seen = [], set()
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"  ! failed {url}: {e}")
            continue
        for e in parsed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            if ts:
                when = datetime.datetime(*ts[:6], tzinfo=datetime.timezone.utc)
                if when < cutoff:
                    continue
            title = clean(e.get("title", ""), 200)
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            items.append({
                "title": title,
                "source": clean(parsed.feed.get("title", url), 60),
                "summary": clean(e.get("summary", e.get("description", ""))),
            })
    return items[:max_items]

def ask_claude(prompt, max_tokens=3000):
    if not API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=API_KEY)
        msg = client.messages.create(
            model=MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as e:
        print(f"  ! Claude call failed: {e}")
        return None

def text_to_xhtml(text):
    """Convert Claude's plain text ('## ' headings, blank-line paragraphs) to xhtml."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if block.startswith("## "):
            out.append(f"<h2>{sx.escape(block[3:].strip())}</h2>")
        else:
            out.append(f"<p>{sx.escape(block)}</p>")
    return "".join(out)

def make_book(identifier, title, chapters):
    """chapters: list of (chapter_title, xhtml_body)."""
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language("en")
    book.add_author("Daily Reads")
    eps = []
    for i, (ct, body) in enumerate(chapters):
        ch = epub.EpubHtml(title=ct, file_name=f"ch{i}.xhtml", lang="en")
        ch.content = f"<html><body><h1>{sx.escape(ct)}</h1>{body}</body></html>"
        book.add_item(ch)
        eps.append(ch)
    book.toc = eps
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + eps
    return book

PLAIN_TEXT_RULES = (
    "Format: plain text only. Section headings on their own line prefixed with '## '. "
    "Paragraphs separated by blank lines. No markdown bold/italics/bullets/links, no tables — "
    "this renders on a small e-ink screen."
)

# ─────────────────────────────────────────────────────────────
# 1. News issue
# ─────────────────────────────────────────────────────────────
def build_news(date_str):
    chapters = []
    for sec in SECTIONS:
        print(f"Fetching: {sec['title']}")
        items = fetch(sec["feeds"], sec["max_items"])
        if not items:
            continue
        material = "\n\n".join(
            f"- {i['title']} ({i['source']})\n  {i['summary'][:400]}" for i in items
        )
        briefing = ask_claude(
            f"You write a section of a daily digest read on a small e-ink device.\n"
            f"Section: {sec['title']}\nInstructions: {sec['style']}\n{PLAIN_TEXT_RULES}\n\n"
            f"Today's raw items:\n{material}"
        )
        if briefing:
            body = text_to_xhtml(briefing)
        else:  # fallback: raw summaries
            body = "".join(
                f"<h3>{sx.escape(i['title'])}</h3><p><i>{sx.escape(i['source'])}</i></p>"
                f"<p>{sx.escape(i['summary'])}</p>"
                for i in items
            )
        chapters.append((sec["title"], body))

    if not chapters:
        print("No fresh news; skipping news issue.")
        return
    book = make_book(f"news-{date_str}", f"Daily News — {date_str}", chapters)
    os.makedirs(ISSUES_DIR, exist_ok=True)
    path = os.path.join(ISSUES_DIR, f"news-{date_str}.epub")
    epub.write_epub(path, book)
    print(f"Wrote {path}")

# ─────────────────────────────────────────────────────────────
# 2. Study issue (stateful)
# ─────────────────────────────────────────────────────────────
def build_study(date_str):
    if not API_KEY:
        print("No ANTHROPIC_API_KEY — skipping study lesson (it requires Claude).")
        return
    with open(os.path.join(ROOT, "syllabus.json")) as f:
        syllabus = json.load(f)
    state_path = os.path.join(ROOT, "state.json")
    with open(state_path) as f:
        state = json.load(f)

    day = state["next_day"]
    lesson = next((l for l in syllabus["lessons"] if l["day"] == day), None)
    if lesson is None:
        print(f"Course complete (day {day} not in syllabus). Add more lessons to continue.")
        return

    covered = ", ".join(state["completed"][-15:]) or "nothing yet — this is Day 1"
    prompt = (
        f"You are writing Day {day} of a daily self-study course: '{syllabus['track']}'.\n"
        f"Learner profile: {syllabus['note']}\n"
        f"Lessons already completed: {covered}.\n\n"
        f"Today's lesson: {lesson['title']}\nFocus: {lesson['focus']}\n\n"
        f"Write a complete ~1800-word lesson with this shape: a 2-3 sentence recap connecting to "
        f"the previous lesson; the core concepts taught clearly with analogies and concrete "
        f"examples from image products; a '## Why this matters for your work' section applying it "
        f"to evaluating/classifying/generating images as a PM; and a '## Check yourself' section "
        f"with 3 questions followed by their answers. Teach, don't survey — the reader should "
        f"finish able to explain this to a colleague.\n{PLAIN_TEXT_RULES}"
    )
    print(f"Generating study lesson Day {day}: {lesson['title']}")
    content = ask_claude(prompt, max_tokens=4000)
    if not content:
        print("Lesson generation failed; state NOT advanced (will retry tomorrow).")
        return

    title = f"AI Study Day {day:02d} — {lesson['title']}"
    book = make_book(f"study-day-{day:02d}", title, [(lesson["title"], text_to_xhtml(content))])
    os.makedirs(ISSUES_DIR, exist_ok=True)
    path = os.path.join(ISSUES_DIR, f"study-day-{day:02d}.epub")
    epub.write_epub(path, book)
    print(f"Wrote {path}")

    state["next_day"] = day + 1
    state["completed"].append(f"Day {day}: {lesson['title']}")
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

# ─────────────────────────────────────────────────────────────
# 3. OPDS catalog
# ─────────────────────────────────────────────────────────────
def opds_entry(fname, title, desc):
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""
  <entry>
    <title>{sx.escape(title)}</title>
    <id>urn:daily-reads:{fname}</id>
    <updated>{date}</updated>
    <author><name>Daily Reads</name></author>
    <content type="text">{sx.escape(desc)}</content>
    <link rel="http://opds-spec.org/acquisition"
          type="application/epub+zip"
          href="{SITE_BASE}/issues/{fname}"/>
  </entry>"""

def write_opds():
    files = os.listdir(ISSUES_DIR) if os.path.isdir(ISSUES_DIR) else []
    news = sorted((f for f in files if f.startswith("news-")), reverse=True)
    study = sorted((f for f in files if f.startswith("study-")), reverse=True)
    for old in news[KEEP_NEWS:] + study[KEEP_STUDY:]:
        os.remove(os.path.join(ISSUES_DIR, old))
    news, study = news[:KEEP_NEWS], study[:KEEP_STUDY]

    entries = []
    for f in news:
        d = f.replace("news-", "").replace(".epub", "")
        entries.append(opds_entry(f, f"Daily News — {d}",
                                  "World, Arsenal & sports, AI news, vision & multimodal"))
    for f in study:
        n = int(f.replace("study-day-", "").replace(".epub", ""))
        entries.append(opds_entry(f, f"AI Study — Day {n}", "Generative AI & vision course lesson"))

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:daily-reads:catalog</id>
  <title>Daily Reads</title>
  <updated>{now}</updated>
  <author><name>Daily Reads</name></author>
  <link rel="self" type="application/atom+xml;profile=opds-catalog;kind=acquisition"
        href="{SITE_BASE}/opds.xml"/>
{''.join(entries)}
</feed>
"""
    with open(os.path.join(DOCS, "opds.xml"), "w") as fh:
        fh.write(feed)
    print(f"Wrote opds.xml with {len(news)} news + {len(study)} study issue(s)")

if __name__ == "__main__":
    today = datetime.date.today().isoformat()
    build_news(today)
    build_study(today)
    write_opds()
