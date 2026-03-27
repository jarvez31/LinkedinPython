# KarrierPython — Job Intelligence Dashboard

A local web dashboard that scrapes LinkedIn jobs, scores them against your resume using Claude AI, and generates a personalised skill gap study plan. Works for **any profession, any location**.

---

## What It Does

| Mode | What you get |
|---|---|
| **Scraper Only** | LinkedIn jobs → CSV with title, company, location, salary, URL |
| **Scraper + AI Score** | Above + fit score (0–100), response probability, matched skills, missing skills, verdict per job |
| **Full Analysis** | Above + clustered skill gaps ranked by score boost + 4-week day-by-day study plan |

Output CSV is split into 3 sections: **Annual Salary**, **Hourly Rate**, and **Salary Not Listed**, each sorted by fit score. The dashboard renders all three groups as interactive tabs with full job details after the pipeline finishes.

---

## Quick Start

### 1. Clone the repo
```bash
git clone https://github.com/jarvez31/KarrierPython
cd KarrierPython
```

### 2. Run setup script
**macOS/Linux:**
````bash setup.sh ```

**Windows:**
```bat setup.bat ```

This does everything automatically:
- Creates a Python virtual environment
- Installs all dependencies
- Installs Playwright + Chromium browser
- Creates `data/`, `outputs/`, `attachments/` folders
- Copies `.env.example` → `.env`

### 3. Start the dashboard
```bash
source venv/bin/activate
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Dashboard Usage

1. Select a mode (Scraper Only / Scraper + AI Score / Full Analysis)
2. Enter your LinkedIn credentials
3. Set keywords, location, pages per keyword, time filter
4. Enter your **profession or field** — used by the AI to tailor scoring and study plan to your specific role
5. Upload your resume (PDF or DOCX) — required for scoring modes
6. Enter your Anthropic API key — required for scoring modes
7. Click **Run Pipeline** and watch the live log
8. Use **⚠ Stop** to halt mid-run and save partial results
9. Use **↺ Reset** to clear state and start fresh
10. Download output files or browse the salary tabs when done

---

## Output Files

All files saved to `outputs/` folder.

| File | Contents |
|---|---|
| `job_results_YYYY-MM-DD.csv` | Jobs split into 3 sections by salary type, sorted by fit score |
| `skill_clusters.txt` | Skill gaps clustered and ranked by score boost impact |
| `study_plan.txt` | 4-week day-by-day learning roadmap personalised to your gaps |

---

## Project Structure

```
KarrierPython/
├── app.py                    ← Flask server + full pipeline (start here)
├── dashboard.html            ← Browser UI
├── setup.sh                  ← One-command setup for new machines
├── .env                      ← API keys (gitignored)
├── .env.example              ← Template for .env
├── requirements.txt          ← All dependencies
│
├── scraping/
│   ├── linkedin.py           ← LinkedIn scraper (Playwright)
│   ├── fetch_descriptions.py ← Job descriptions + salary extractor
│   └── karriere.py           ← karriere.at scraper (secondary source)
│
├── scoring/
│   ├── score.py              ← Claude API fit scoring
│   ├── analyze.py            ← 6 market analyses (ATS, CV language, cover letter angles)
│   ├── study_plan.py         ← Skill boost analysis + 4-week plan generator
│   └── cluster.py            ← Skill gap clustering
│
├── data/                     ← JSON job databases (gitignored)
│   ├── linkedin_jobs.json
│   └── linkedin_jobs_scored.json
│
├── outputs/                  ← Generated output files (gitignored)
│
├── attachments/              ← Resume storage (gitignored)
│   └── resume.pdf
│
└── models/
    └── job_model.py
```

---

## Running Individual Scripts

```bash
python scraping/linkedin.py            # Scrape LinkedIn jobs
python scraping/fetch_descriptions.py  # Fetch descriptions + salary
python scoring/score.py                # Score all jobs with Claude API
python scoring/analyze.py              # Run 6 market analyses
python scoring/study_plan.py           # Generate skill boost + study plan
```

---

## Cost Estimate

| Mode | Approximate cost |
|---|---|
| Scraper Only | Free |
| Scraper + AI Score (100 jobs) | ~$1.00–2.00 |
| Full Analysis (100 jobs) | ~$1.50–2.50 |

Using Claude Sonnet via Anthropic API. Add credits at [console.anthropic.com](https://console.anthropic.com).

A $5 credit covers ~250–300 fully scored jobs with study plan generation.

---

## Sharing With Friends

Each person runs the tool locally on their own machine and LinkedIn account. This is intentional — LinkedIn blocks cloud-hosted scrapers. Local runs work reliably.

### Requirements
- Python 3.9+
- macOS, Linux, or Windows (WSL recommended on Windows)
- A LinkedIn account
- An Anthropic API key — get one at [console.anthropic.com](https://console.anthropic.com)

All credentials are entered in the dashboard UI — nothing is stored between sessions.

---

## Notes

- Scraper uses Playwright (headless Chromium) with rate limiting to avoid detection.
- Jobs are deduplicated by ID — re-running only adds new jobs to the database.
- Salary extraction covers ~90% of listings. Some jobs don't display salary publicly.
- Salary types are auto-classified: annual / hourly / missing based on the raw salary string.
- For Austrian/German market: add `Künstliche Intelligenz` and `Maschinelles Lernen` to keywords to surface German-language postings.
- `.env`, `data/`, `outputs/`, and `attachments/` are all gitignored — no credentials or job data ever gets committed.
