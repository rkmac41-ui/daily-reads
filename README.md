# Daily Reads → Xteink X3 (CrossPoint)

Every morning, GitHub Actions builds **two EPUBs** and publishes them to an OPDS catalog your X3 pulls over WiFi:

- **Daily News — YYYY-MM-DD**: six chapters — World in 5 Minutes, India, Arsenal & Premier League, AI News & How People Use It, Markets & Top Tech Stocks (real last-trading-day numbers for 10 tech names), and Something Interesting (a closing digression, not necessarily related to anything else). Text only, no images.
- **AI Study — Day N**: the next lesson in a 43-day "Generative AI & Vision for Image PMs" course, covering classical CV, classifiers, generative models, and the VLM landscape (architectures, major players, and how to track progress as it moves). Progress is tracked in `state.json`; each lesson recaps and builds on what you've completed.

## One-time setup (~10 minutes)

1. Create a **public** GitHub repo named `daily-reads` and push these files.
2. Repo → Settings → Pages → Source: *Deploy from a branch* → `main`, folder `/docs` → Save.
3. Repo → Settings → Secrets and variables → Actions → New secret: `ANTHROPIC_API_KEY` (from console.anthropic.com). **Required for the study course, the written news sections, and the Something Interesting chapter.** Without it, news sections fall back to raw article summaries, study is skipped, and Something Interesting is omitted. (Markets still shows real stock numbers either way — those are fetched directly, not written by Claude.)
4. Actions tab → "Build daily issue" → Run workflow (manual test). Verify `https://rkmac41-ui.github.io/daily-reads/opds.xml` loads in a browser.
5. On the X3: enter File Transfer mode, open `http://crosspoint.local/settings` from your phone, and in the OPDS Servers card add a name and the URL: `https://rkmac41-ui.github.io/daily-reads/opds.xml` (no auth).

## Daily use

Open the OPDS browser on the X3 → auto-joins saved WiFi → today's two issues are at the top → download → read. News prunes after 14 days, study lessons after 30.

## Managing the study course

- `syllabus.json` — the full 43-day curriculum. Edit, reorder, or append lessons anytime.
- `state.json` — `next_day` is your bookmark. Fell behind and want to pause? Temporarily disable the schedule, or just let issues accumulate — lessons stay sequential either way. Want to re-do a lesson? Lower `next_day` and commit.
- If a lesson generation fails, state does NOT advance — it retries tomorrow.

## Customizing news

- `SECTIONS` in `generate.py` — World, India, Arsenal & Premier League, and AI News. Feeds are plain RSS URLs; each section's `style` string is the instruction Claude follows when writing that chapter.
- `TECH_TICKERS` and `MARKET_FEEDS` in `generate.py` — the 10 stocks tracked in Markets, and the RSS sources for market news. Stock prices/volume are fetched live (Yahoo Finance's public chart endpoint, no key needed), not written by Claude.
- Something Interesting isn't feed-driven — it's grounded in Wikipedia's "on this day" API when available, but Claude can pick any topic. Edit its prompt directly in `build_interesting_chapter()` if you want to steer it (e.g. toward specific themes).

## Schedule

`.github/workflows/daily.yml` → cron `17 10 * * *` — that's 5:17am ET in winter (EST, UTC-5) and 6:17am ET in summer (EDT, UTC-4). Cron always runs in UTC and doesn't observe daylight saving, so the local delivery time shifts by an hour twice a year. The minute is deliberately off `:00` since GitHub deprioritizes schedules at the top of the hour. The workflow also writes a `.keepalive` commit daily (GitHub auto-disables scheduled workflows after 60 days with no commits) and opens a GitHub issue — which emails you — if a build fails.
