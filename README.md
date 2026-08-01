# Daily Reads → Xteink X3 (CrossPoint)

Every morning, GitHub Actions builds **two EPUBs** and publishes them to an OPDS catalog your X3 pulls over WiFi:

- **Daily News — YYYY-MM-DD**: four chapters — World in 5 Minutes, Arsenal & Sports, AI News & How People Use It, Vision & Multimodal (explained for someone new to CV)
- **AI Study — Day N**: the next lesson in a 41-day "Generative AI & Vision for Image PMs" course. Progress is tracked in `state.json`; each lesson recaps and builds on what you've completed.

## One-time setup (~10 minutes)

1. Create a **public** GitHub repo named `daily-reads` and push these files.
2. Repo → Settings → Pages → Source: *Deploy from a branch* → `main`, folder `/docs` → Save.
3. Repo → Settings → Secrets and variables → Actions → New secret: `ANTHROPIC_API_KEY` (from console.anthropic.com). **Required for the study course and news briefings.** Without it, news falls back to raw article summaries and study is skipped.
4. Actions tab → "Build daily issue" → Run workflow (manual test). Verify `https://rkmac41-ui.github.io/daily-reads/opds.xml` loads in a browser.
5. On the X3: enter File Transfer mode, open `http://crosspoint.local/settings` from your phone, and in the OPDS Servers card add: `https://rkmac41-ui.github.io/daily-reads/opds.xml` (no auth). Optionally set the OPDS download folder to `Daily/` in device settings.

## Daily use

Open the OPDS browser on the X3 → auto-joins saved WiFi → today's two issues are at the top → download → read. News prunes after 14 days, study lessons after 30.

## Managing the study course

- `syllabus.json` — the full 41-day curriculum. Edit, reorder, or append lessons anytime.
- `state.json` — `next_day` is your bookmark. Fell behind and want to pause? Temporarily disable the schedule, or just let issues accumulate — lessons stay sequential either way. Want to re-do a lesson? Lower `next_day` and commit.
- If a lesson generation fails, state does NOT advance — it retries tomorrow.

## Customizing news

Edit `SECTIONS` in `generate.py`: feeds are plain RSS URLs, and each section's `style` string is the instruction Claude follows when writing that chapter.

## Schedule

`.github/workflows/daily.yml` → cron `0 10 * * *` (6am ET winter / 5am EDT summer; use `0 9` for 5am EDT).
