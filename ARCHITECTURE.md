# Architecture

A short tour of how **LinkedinPython** is put together — the folder layout, how a run flows through the system, and where your data ends up. For setup and usage, see the [README](README.md).

## The big picture

It's a small, single-process web app:

- **Flask backend** (`app.py`) serves the dashboard and runs the whole pipeline.
- **Playwright** (headless Chromium) drives LinkedIn — logs in, scrapes job cards, opens each posting to pull the description and salary.
- **Your chosen LLM** (Anthropic, DeepSeek, Gemini, OpenAI, Llama, or any OpenAI-compatible endpoint) scores each job against your resume and, in Full Analysis mode, builds a skill-gap study plan.
- **The dashboard** (`dashboard.html`) is one HTML page with embedded JavaScript. It posts your form to the backend and polls for live progress every ~1.5 seconds.

There's no database and no microservices — job data is kept in JSON files under `data/`, and results are written as CSV/TXT under `outputs/`.

## How a run flows

```
You fill the form  ─►  POST /run  ─►  background pipeline thread
                                          │
       1. Log in to LinkedIn (headless Chromium)
       2. For each keyword/page: collect job cards
       3. Open each posting → extract description + salary
       4. (scoring modes) Score every job vs your resume — in parallel
       5. (full mode)      Cluster missing skills + build a 4-week study plan
       6. Save JSON (data/) and let you download CSV/TXT (outputs/)
                                          │
   Meanwhile the dashboard polls GET /status ~every 1.5s for the live log
```

- **Scraping** is sequential and paced (one posting at a time, with human-like random delays) to avoid LinkedIn rate-limiting.
- **Scoring** runs **after** scraping finishes, but the LLM calls go out **in parallel** (the number of concurrent calls is chosen automatically per provider), so scoring is fast even for hundreds of jobs.

## Modes

| Mode | What runs | Output |
|---|---|---|
| **Scraper Only** | Steps 1–3 | `job_results_*.csv` (no scores) |
| **Scraper + AI Score** | Steps 1–4 | CSV with fit score, skills, verdict |
| **Full Analysis** | Steps 1–5 | CSV + `skill_clusters.txt` + `study_plan.txt` |

**🔬 Test Run** is a tiny preflight: it logs in, scores a single real job, then stops — a ~30-second way to confirm credentials, your API key, and the scraper all work before a full run.

## Speed & safety

- The **Speed** dropdown (Fast / Balanced / Safe) controls how long the scraper pauses between actions. Every tier keeps randomness, because constant-interval requests are the easiest way for LinkedIn to flag a bot. Safe is slowest and most cautious; Balanced is the default.
- **Stop** halts the pipeline as soon as possible and keeps whatever was already done (partial CSV).
- **Run** always starts a clean session — any previous run is wound down first.
- If the browser session dies mid-scrape, the run **aborts automatically and saves partial results** instead of hanging.

## File & folder layout

```
app.py                 Flask server + the whole pipeline (scrape → score → cluster → plan)
dashboard.html         The single-page dashboard UI (HTML + embedded JS)
launch_dashboard.bat   Windows one-click launcher (Desktop-shortcut target; installs missing deps)
setup.sh / setup.bat   First-time setup (Windows setup.bat also creates the Desktop shortcut)
smoke_test.py          Standalone preflight check (config, packages, API key, login)
clean_jobs.py          Utility: remove jobs that have no description
requirements.txt       Python dependencies
.env.example           Template for your credentials and provider settings

data/                  Scraped + scored jobs, and your job-status lists (JSON) — gitignored
outputs/               Generated CSV and TXT result files — gitignored
attachments/           Uploaded resumes — gitignored
config.json            Your saved form preferences (created at runtime) — gitignored
.env                   Your credentials (you create this from .env.example) — gitignored
```

## Supported AI providers

You pick the provider and model in the dashboard (or set them in `.env`). Known providers are routed to the correct endpoint automatically; "Custom" lets you point at any OpenAI-compatible URL.

| Provider | Example models |
|---|---|
| Anthropic | claude-sonnet-4-6, claude-opus-4-8, claude-haiku-4-5 |
| DeepSeek | deepseek-v4-pro, deepseek-v4-flash |
| Gemini | gemini-2.5-pro, gemini-2.5-flash, gemini-3-flash-preview |
| OpenAI | gpt-4o, gpt-4o-mini |
| Meta Llama | Llama-4-Maverick…, Llama-4-Scout… |
| Custom | any model on your OpenAI-compatible endpoint |

The model field is editable — if a provider ships a newer model, just type its id; no code change needed.

## HTTP endpoints (for contributors)

| Endpoint | Purpose |
|---|---|
| `GET /` | Serves the dashboard |
| `GET /config` | Returns saved preferences + secrets (merged from `.env` + `config.json`) |
| `POST /run` | Starts a pipeline run (or a Test Run) |
| `GET /status` | Live progress: stage, log tail, job counts |
| `POST /stop` | Requests a graceful stop (saves partial) |
| `POST /reset` | Clears state and returns to a fresh session |
| `GET /download/<csv\|skills\|plan>` | Downloads result files |
| `GET /salary_stats` | Jobs grouped by salary type, sorted by fit |
| `POST /load_csv` | Loads a previous results CSV to browse without re-scraping |
| `/applied`, `/interested`, `/not_interested`, `/rejected`, … | Per-job status tracking |

All of it lives in `app.py` — there's no separate module to hunt through.
