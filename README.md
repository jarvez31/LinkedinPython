# LinkedinPython — Job Intelligence Dashboard

> Scrape LinkedIn jobs, score them against your resume with Claude AI, and get a personalised skill gap study plan. Works for any profession, any location.

---

## Features

| Mode | What you get |
|---|---|
| 🔍 **Scraper Only** | Jobs → CSV with title, company, location, salary, URL |
| 🎯 **Scraper + AI Score** | Above + fit score, response probability, matched/missing skills, verdict |
| 🧠 **Full Analysis** | Above + skill gap clusters ranked by score boost + 4-week study plan |

- Jobs sorted by fit score inside 3 salary tabs: **Annual / Hourly / Not Listed**
- Stop mid-run and save partial results
- Reset and re-run with different settings
- Works on macOS, Linux, and Windows (no WSL needed)

---

## Quick Start

### 1. Clone & setup

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

Edit the `.env` file created by setup and fill in your details:

```
LINKEDIN_EMAIL=your-email@example.com
LINKEDIN_PASSWORD=your-password
ANTHROPIC_API_KEY=sk-ant-api03-...
```

### 3. Run

```bash
source venv/bin/activate   # macOS / Linux
venv\Scripts\activate      # Windows
python app.py
```

Open **http://localhost:5000** in your browser.

### 4. Smoke test (optional)

Before a full run, verify everything works:
```bash
python smoke_test.py
```

---

## Usage

1. Select a mode in the dashboard
2. Enter your LinkedIn credentials (pre-filled from `.env`)
3. Set keywords, location, pages per keyword, time filter
4. Enter your **profession or field** — the AI uses this to tailor scoring and the study plan
5. Upload your resume (PDF or DOCX) — required for scoring modes
6. Enter your Anthropic API key (pre-filled from `.env`) — required for scoring modes
7. Click **Run Pipeline** — watch the live log
8. Hit **⚠ Stop** to halt mid-run, **↺ Reset** to start fresh
9. Download output files or browse the salary tabs

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
- A LinkedIn account
- An Anthropic API key — [console.anthropic.com](https://console.anthropic.com) (~$5 covers 250-300 scored jobs)

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
├── smoke_test.py             ← Pre-flight dependency check
├── clean_jobs.py             ← Remove null-description jobs from data files
├── setup.sh / setup.bat      ← One-command setup
├── requirements.txt
├── .env.example              ← Template for your credentials
│
├── data/                     ← Job databases (gitignored)
├── outputs/                  ← Generated files (gitignored)
└── attachments/              ← Resume uploads (gitignored)
```

---

## Notes

- Uses Playwright (headless Chromium) with rate limiting — works on residential IPs, not cloud servers
- Jobs deduplicated by ID on every run — re-runs only add new jobs
- Salary auto-classified: annual / hourly / missing
- Run `python smoke_test.py` before your first full pipeline to catch setup issues early
