#!/usr/bin/env python3
"""
Daily Reads for Xteink X3 (CrossPoint)

Builds TWO daily EPUBs and publishes an OPDS catalog to docs/ for GitHub Pages:
  1. news-YYYY-MM-DD.epub   — World in 5 min / India / Arsenal & Premier League /
                               AI News / Markets & Top Tech Stocks / Something Interesting
  2. study-day-NN.epub      — next lesson from syllabus.json, tracked in state.json

Claude (ANTHROPIC_API_KEY) writes the news briefings and study lessons.
Without a key: news falls back to raw article summaries; study is skipped.

Stock quotes and "on this day" material come from public, keyless endpoints (Yahoo Finance's
chart API and Wikipedia's REST API) — fetched directly in code, not asked of Claude, so numbers
and dates in the issue are real rather than model-generated.
"""

import os
import re
import json
import html
import time
import random
import datetime
import urllib.request
import xml.sax.saxutils as sx

import feedparser
from ebooklib import epub

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
ISSUES_DIR = os.path.join(DOCS, "issues")
SITE_BASE = os.environ.get("SITE_BASE", "https://rkmac41-ui.github.io/daily-reads")
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"
UA = "Mozilla/5.0 (compatible; daily-reads-bot/1.0)"

KEEP_NEWS = 14    # days of news back-issues kept in catalog
KEEP_STUDY = 30   # study back-issues kept

# Top tech stocks tracked in the Markets section — edit this list freely.
TECH_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "TSLA", "ORCL", "AMD"]

MARKET_FEEDS = [
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",  # CNBC Markets
]

# ─────────────────────────────────────────────────────────────
# News sections — edit feeds freely. (Markets and Something Interesting are built
# separately below since they pull real data, not just feed material — see
# build_markets_chapter() and build_interesting_chapter().)
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
        "title": "India",
        "feeds": [
            "https://www.thehindu.com/news/national/feeder/default.rss",
            "https://feeds.feedburner.com/ndtvnews-india-news",
            "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
        ],
        "max_items": 15,
        "style": (
            "Condense into a standalone briefing on news from India (~450 words). Lead with the "
            "most consequential national stories — politics, economy, major events — grouped "
            "sensibly. Skip filler and pure entertainment gossip."
        ),
    },
    {
        "title": "Arsenal & Premier League",
        "feeds": [
            "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
            "https://arseblog.com/feed/",
            "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml",
            "https://feeds.bbci.co.uk/sport/rss.xml",
        ],
        "max_items": 15,
        "style": (
            "The reader is an Arsenal supporter (also follows the Knicks/NBA). Lead with Arsenal "
            "news — matches, transfers, injuries — with a fan's voice. Then cover the wider "
            "Premier League: other big clubs, table movement, the week's biggest storylines. "
            "Close with a short note on other sports if anything notable happened (NBA etc). "
            "~450 words."
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

def strip_redundant_leading_heading(text, title):
    """Defensively drop a leading '## ...' block if it just restates the chapter title —
    the chapter template already renders the title as an <h1>, so a matching '## ' first
    line produces a visible duplicate heading. Belt-and-braces alongside the prompt
    instruction in PLAIN_TEXT_RULES telling Claude not to do this in the first place."""
    if not text:
        return text
    blocks = re.split(r"\n\s*\n", text.strip(), maxsplit=1)
    first = blocks[0].strip()
    if not first.startswith("## "):
        return text
    heading = first[3:].strip()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    h, t = norm(heading), norm(title)
    if h and t and (h == t or h in t or t in h):
        return blocks[1] if len(blocks) > 1 else ""
    return text

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

PLAIN_TEXT_RULES = (
    "Format: plain text only. Section headings on their own line prefixed with '## '. "
    "Paragraphs separated by blank lines. No markdown bold/italics/bullets/links, no tables — "
    "this renders on a small e-ink screen. Do not begin with a heading that just repeats the "
    "section or lesson title given to you above — that title is already shown as the chapter "
    "heading, so a repeat of it would display as a duplicate. Start directly with your first "
    "real subheading or the first paragraph."
)

# ─────────────────────────────────────────────────────────────
# EPUB assembly — build the book incrementally so chapters (news sections, markets,
# the interesting digest) can each contribute their own embedded images if they have one.
# ─────────────────────────────────────────────────────────────
def new_book(identifier, title):
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language("en")
    book.add_author("Daily Reads")
    return book

def add_chapter(book, index, title, body_xhtml):
    ch = epub.EpubHtml(title=title, file_name=f"ch{index}.xhtml", lang="en")
    ch.content = f"<html><body><h1>{sx.escape(title)}</h1>{body_xhtml}</body></html>"
    book.add_item(ch)
    return ch

def finalize_book(book, chapters):
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters

# ─────────────────────────────────────────────────────────────
# Markets & Top Tech Stocks — real quotes (Yahoo Finance chart API, no key needed) plus
# Claude commentary grounded in those numbers. The numbers themselves are code-rendered,
# not asked of the model, so they can't drift from what was actually fetched.
# ─────────────────────────────────────────────────────────────
def fetch_stock_quotes(tickers):
    rows = []
    for t in tickers:
        try:
            req = urllib.request.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{t}",
                headers={"User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                meta = json.loads(r.read())["chart"]["result"][0]["meta"]
            price, prev = meta["regularMarketPrice"], meta["previousClose"]
            rows.append({
                "ticker": t,
                "name": meta.get("longName") or meta.get("shortName") or t,
                "price": price,
                "change_pct": (price - prev) / prev * 100 if prev else 0.0,
                "day_high": meta.get("regularMarketDayHigh"),
                "day_low": meta.get("regularMarketDayLow"),
                "volume": meta.get("regularMarketVolume"),
            })
        except Exception as e:
            print(f"  ! quote fetch failed for {t}: {e}")
        time.sleep(0.3)  # be polite to the endpoint
    return rows

def build_markets_chapter():
    print("Fetching: Markets & Top Tech Stocks")
    quotes = fetch_stock_quotes(TECH_TICKERS)
    news_items = fetch(MARKET_FEEDS, 12)

    quote_material = "\n".join(
        f"- {q['ticker']} ({q['name']}): ${q['price']:.2f}, {q['change_pct']:+.2f}% vs prior "
        f"close, day range ${q['day_low']:.2f}-${q['day_high']:.2f}"
        for q in quotes
    ) or "No stock data available today."
    news_material = "\n\n".join(
        f"- {i['title']} ({i['source']})\n  {i['summary'][:400]}" for i in news_items
    ) or "No fresh market news today."

    briefing = ask_claude(
        "You write the Markets section of a daily digest read on a small e-ink device.\n"
        "Write a short market recap (~200 words) covering the day's biggest financial-market "
        "stories. Then a '## Tech stock insights' section (~200 words) commenting on what's "
        "moving the top tech names in the data below — standouts, patterns, anything worth "
        "noticing. Only reference numbers given to you below; do not invent figures.\n"
        f"{PLAIN_TEXT_RULES}\n\n"
        f"Today's tech stock data (most recent trading day):\n{quote_material}\n\n"
        f"Today's market news items:\n{news_material}"
    )
    body = ""
    if briefing:
        briefing = strip_redundant_leading_heading(briefing, "Markets & Top Tech Stocks")
        body += text_to_xhtml(briefing)
    else:
        body += "<p><i>Market commentary unavailable today (no API key or the Claude call failed).</i></p>"

    body += "<h2>Top 10 Tech Stocks — Last Trading Day</h2>"
    if quotes:
        for q in quotes:
            direction = "up" if q["change_pct"] >= 0 else "down"
            vol = f"{q['volume'] / 1e6:.1f}M shares" if q.get("volume") else "volume n/a"
            body += (
                f"<p><b>{sx.escape(q['ticker'])}</b> — {sx.escape(q['name'])} — "
                f"${q['price']:.2f} ({direction} {abs(q['change_pct']):.2f}%), "
                f"day range ${q['day_low']:.2f}–${q['day_high']:.2f}, {vol}</p>"
            )
    else:
        body += "<p><i>Live stock data unavailable today.</i></p>"
    return body

# ─────────────────────────────────────────────────────────────
# Something Interesting — a closing digression, unrelated to anything else in the issue.
# Grounded (optionally) in Wikipedia's "on this day" feed so it's a real fact rather than
# a model invention, but the prompt explicitly allows Claude to pick something else. Embeds
# an image only when a decent one is available — never forced.
# ─────────────────────────────────────────────────────────────
def fetch_on_this_day():
    today = datetime.date.today()
    url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{today.month:02d}/{today.day:02d}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("selected", [])
    except Exception as e:
        print(f"  ! on-this-day fetch failed: {e}")
        return []

def build_interesting_chapter(book):
    print("Fetching: Something Interesting")
    events = fetch_on_this_day()
    material, image_url = "", None
    if events:
        picks = random.sample(events, min(4, len(events)))
        material = "\n\n".join(f"- {e.get('text', '')}" for e in picks)
        for e in picks:
            pages = e.get("pages") or []
            if pages and pages[0].get("thumbnail"):
                image_url = pages[0]["thumbnail"]["source"]
                break

    prompt = (
        "You write the closing 'Something Interesting' section of a daily digest read on a "
        "small e-ink device — a short, engaging digression that does not need to connect to "
        "anything else in the issue. History, science, a strange fact, nature, culture — "
        "anything genuinely interesting. Pick ONE angle and go deep rather than listing many. "
        "Write with warmth and curiosity, not like a news brief. ~300 words.\n"
        f"{PLAIN_TEXT_RULES}"
    )
    if material:
        prompt += (
            "\n\nSome things that happened on this date in history, for inspiration only — use "
            "one, riff on one, or ignore all of them and pick something else entirely if you "
            "have a better idea:\n" + material
        )
    content = ask_claude(prompt, max_tokens=1200)
    if not content:
        return None  # skip the chapter rather than publish nothing interesting
    content = strip_redundant_leading_heading(content, "Something Interesting")
    body = text_to_xhtml(content)

    if image_url:
        try:
            req = urllib.request.Request(image_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                img_bytes = r.read()
            ext = image_url.rsplit(".", 1)[-1].split("?")[0].lower()
            ext = ext if ext in ("jpg", "jpeg", "png") else "jpg"
            media_type = "image/png" if ext == "png" else "image/jpeg"
            img_item = epub.EpubItem(
                uid="interesting_img", file_name=f"images/interesting.{ext}",
                media_type=media_type, content=img_bytes,
            )
            book.add_item(img_item)
            body = f'<img src="images/interesting.{ext}" alt="Illustration"/>' + body
        except Exception as e:
            print(f"  ! image embed failed (continuing without it): {e}")

    return ("Something Interesting", body)

# ─────────────────────────────────────────────────────────────
# 1. News issue
# ─────────────────────────────────────────────────────────────
def build_news(date_str):
    book = new_book(f"news-{date_str}", f"Daily News — {date_str}")
    chapters, idx = [], 0

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
            briefing = strip_redundant_leading_heading(briefing, sec["title"])
            body = text_to_xhtml(briefing)
        else:  # fallback: raw summaries
            body = "".join(
                f"<h3>{sx.escape(i['title'])}</h3><p><i>{sx.escape(i['source'])}</i></p>"
                f"<p>{sx.escape(i['summary'])}</p>"
                for i in items
            )
        chapters.append(add_chapter(book, idx, sec["title"], body))
        idx += 1

    market_body = build_markets_chapter()
    if market_body:
        chapters.append(add_chapter(book, idx, "Markets & Top Tech Stocks", market_body))
        idx += 1

    interesting = build_interesting_chapter(book)
    if interesting:
        title, body = interesting
        chapters.append(add_chapter(book, idx, title, body))
        idx += 1

    if not chapters:
        print("No fresh news; skipping news issue.")
        return
    finalize_book(book, chapters)
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
    content = strip_redundant_leading_heading(content, lesson["title"])

    title = f"AI Study Day {day:02d} — {lesson['title']}"
    book = new_book(f"study-day-{day:02d}", title)
    chapter = add_chapter(book, 0, lesson["title"], text_to_xhtml(content))
    finalize_book(book, [chapter])
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
                                  "World, India, Arsenal & Premier League, AI news, "
                                  "markets & top tech stocks, something interesting"))
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
