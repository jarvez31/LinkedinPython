# KarrierMultiSource — Job Intelligence Dashboard

> Scrape jobs from LinkedIn, Indeed, karriere.at, and Xing, score them against your resume with the AI provider of your choice (Anthropic, DeepSeek, Gemini, OpenAI, Llama, or any OpenAI-compatible endpoint), and get a personalised skill gap study plan. Works for any profession, any location.

---

## Features

| Mode | What you get |
|---|---|
| 🔍 **Scraper Only** | Jobs → CSV with title, company, location, salary, URL, source |
| 🎯 **Scraper + AI Score** | Above + fit score, response probability, matched/missing skills, verdict |
| 🧠 **Full Analysis** | Above + skill gap clusters ranked by score boost + 4-week study plan |

- **Multiple job sources** — tick any of **LinkedIn, Indeed, karriere.at, Xing**; results are merged and deduplicated, each row tagged with its source. Indeed needs no login; LinkedIn and Xing use their own credentials
- **Choose your AI provider & model** from dropdowns — Anthropic, DeepSeek, Gemini, OpenAI, Llama, or a custom OpenAI-compatible endpoint
- **🔬 Test Run** — a ~30s preflight: scrapes one real job per ticked source, scores it, then cleans up. Run it before committing to a full scrape
- **Speed control** — Fast / Balanced / Safe pacing (all keep human-like jitter to avoid rate limits)
- **Parallel AI scoring** — jobs are scored concurrently (worker count auto-tuned per provider), so scoring is near-instant
- Jobs sorted by fit score inside 3 salary tabs: **Annual / Hourly / Not Listed**
- Stop mid-run and save partial results; Run starts a clean new session
- Works on macOS, Linux, and Windows (no WSL needed)
- **Windows:** `setup.bat` creates a one-click Desktop shortcut that launches the dashboard (and self-installs any missing packages)

---

## Quick Start

### Option A: Docker (recommended — zero dependency install)

```bash
git clone https://github.com/jarvez31/LinkedinPython
cd LinkedinPython
# Create a .env file with your credentials:
cp .env.example .env
# Edit .env — add your LinkedIn + LLM credentials
docker compose up --build
```
Open **http://localhost:5000**. Works identically on Windows, macOS, and Linux.

### Option B: Manual (Python + Playwright)

**macOS / Linux**
```bash
git clone https://github.com/jarvez31/LinkedinPython
cd LinkedinPython
bash setup.sh
```

**Windows**
```bat
git clone https://github.com/jarvez31/LinkedinPython
cd LinkedinPython
setup.bat
```

### 2. Add your credentials

Edit the `.env` file and fill in your details:

```
LINKEDIN_EMAIL=your-email@example.com
LINKEDIN_PASSWORD=your-password
# Xing is optional — only needed if you tick the Xing source:
XING_EMAIL=your-xing-email@example.com
XING_PASSWORD=your-xing-password
# Indeed and karriere.at need no login.
# Provider: anthropic | deepseek | gemini | openai | llama | custom
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=sk-ant-api03-...
# Custom endpoints only (deepseek/gemini/llama are routed automatically):
# LLM_BASE_URL=https://api.openrouter.ai/v1
```

> You can also pick the provider, model, and API key directly in the dashboard — no `.env` edit required. Non-Anthropic providers use the `openai` package (already in `requirements.txt`).

### 3. Run

```bash
source venv/bin/activate   # macOS / Linux
venv\Scripts\activate      # Windows
python app.py
```

Open **http://localhost:5000** in your browser.

### Access from your phone (Windows, Tailscale or LAN)

`launch_dashboard_remote.bat` starts the dashboard bound to all network interfaces so another device (your phone) can reach it:

```bat
launch_dashboard_remote.bat
```

The window prints the address to open on your phone. Over [Tailscale](https://tailscale.com) it looks like `http://100.x.y.z:5000` and works from anywhere on mobile data; on the same Wi-Fi use the PC's LAN IP. Run `tailscale ip -4` to find the address.

> **Security:** the dashboard has no password and shows your saved credentials. Only expose it over Tailscale (private) or a trusted LAN, never a public tunnel without a password gate first.

### 4. Smoke test (optional)

Before a full run, verify everything works:
```bash
python smoke_test.py
```

---

## Usage

1. Select a mode in the dashboard
2. Tick the **job sources** you want (LinkedIn, Indeed, karriere.at, Xing) and enter credentials for the ones that need them (pre-filled from `.env`; Indeed and karriere.at need none)
3. Set keywords, location, pages per keyword, time filter, and **Speed** (Fast / Balanced / Safe)
4. Enter your **profession or field** — the AI uses this to tailor scoring and the study plan
5. Upload your resume (PDF or DOCX) — required for scoring modes
6. Pick your **AI provider & model** and enter the API key (pre-filled from `.env`) — required for scoring modes
7. (Recommended) Hit **🔬 Test Run** first — logs in, scores one job, confirms everything works in ~30s
8. Click **Run Pipeline** — watch the live log (including live token counts per scored job)
9. Hit **⚠ Stop** to halt and save partial results, **↺ Reset** to start fresh
10. Download output files or browse the salary tabs

---

## Output Files

Saved to `outputs/` folder.

| File | Contents |
|---|---|
| `job_results_YYYY-MM-DD.csv` | Jobs in 3 sections by salary type, sorted by fit score |
| `skill_clusters.txt` | Skill gaps ranked by how much learning each one boosts your score |
| `study_plan.txt` | 4-week day-by-day learning roadmap tailored to your gaps |

---

## Requirements

- Python 3.9+
- A LinkedIn and/or Xing account for those sources (Indeed and karriere.at need no login)
- An API key for **one** AI provider (scoring modes only): Anthropic, DeepSeek, Gemini, OpenAI, Llama, or any OpenAI-compatible endpoint. DeepSeek is the cheapest; Anthropic ~$5 covers 250–300 scored jobs.

> Secrets are stored in `.env` (gitignored). Preferences (keywords, location, profession) are saved to `config.json` for convenience.

---

## Cost

| Mode | Cost |
|---|---|
| Scraper Only | Free |
| Scraper + AI Score (100 jobs) | ~$1.00-2.00 |
| Full Analysis (100 jobs) | ~$1.50-2.50 |

---

## Project Structure

```
├── app.py                    ← Flask server + full pipeline (scrape, score, clusters, plan)
├── dashboard.html            ← Browser UI
├── launch_dashboard.bat      ← Windows one-click launcher (Desktop shortcut target; self-heals deps)
├── launch_dashboard_remote.bat ← Same, but binds all interfaces for phone access (Tailscale / LAN)
├── smoke_test.py             ← Pre-flight dependency check
├── clean_jobs.py             ← Remove null-description jobs from data files
├── setup.sh / setup.bat      ← One-command setup (Windows setup.bat also creates the Desktop shortcut)
├── requirements.txt
├── .env.example              ← Template for your credentials
│
├── data/                     ← Job databases (gitignored)
├── outputs/                  ← Generated files (gitignored)
└── attachments/              ← Resume uploads (gitignored)
```

> **Want the full picture?** See [ARCHITECTURE.md](ARCHITECTURE.md) for how a run flows end-to-end, the modes, the supported AI providers, and the HTTP endpoints.

---

## Notes

- Uses Playwright (headless Chromium) with rate limiting — works on residential IPs, not cloud servers
- **Speed tiers** keep human-like randomness; if the browser session dies, the scrape auto-aborts and saves partial results (no more multi-hour hangs)
- **Scoring runs in parallel** with a per-provider auto-tuned worker count; the live log shows token counts per job
- Jobs from all ticked sources are merged, deduplicated by ID on every run, and tagged with their source — re-runs only add new jobs
- Salary auto-classified: annual / hourly / missing
- Run `python smoke_test.py` (or the in-app **Test Run**) before your first full pipeline to catch setup issues early
