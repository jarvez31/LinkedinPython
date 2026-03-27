# KarrierPython — Job Intelligence Dashboard

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

### macOS / Linux

```bash
git clone https://github.com/jarvez31/linkedin-job-scraper-analyser
cd linkedin-job-scraper-analyser
bash setup.sh
source venv/bin/activate
python app.py
```

### Windows

```bat
git clone https://github.com/jarvez31/linkedin-job-scraper-analyser
cd linkedin-job-scraper-analyser
setup.bat
venv\Scripts\activate
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Usage

1. Select a mode in the dashboard
2. Enter your LinkedIn credentials
3. Set keywords, location, pages per keyword, time filter
4. Enter your **profession or field** — the AI uses this to tailor scoring and the study plan
5. Upload your resume (PDF or DOCX) — required for scoring modes
6. Enter your Anthropic API key — required for scoring modes
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
- An Anthropic API key — [console.anthropic.com](https://console.anthropic.com) (~$5 covers 250–300 scored jobs)

> All credentials are entered in the UI — nothing is stored between sessions.

---

## Cost

| Mode | Cost |
|---|---|
| Scraper Only | Free |
| Scraper + AI Score (100 jobs) | ~$1.00–2.00 |
| Full Analysis (100 jobs) | ~$1.50–2.50 |

---

## Project Structure

```
├── app.py                    ← Flask server + pipeline (start here)
├── dashboard.html            ← Browser UI
├── setup.sh / setup.bat      ← One-command setup
├── requirements.txt
│
├── scraping/
│   ├── linkedin.py           ← LinkedIn scraper (Playwright)
│   └── fetch_descriptions.py ← Descriptions + salary extractor
│
├── scoring/
│   ├── score.py              ← Claude API fit scoring
│   ├── analyze.py            ← ATS keywords, CV language, cover letter angles
│   ├── study_plan.py         ← Skill boost analysis + study plan
│   └── cluster.py            ← Skill gap clustering
│
├── data/                     ← Job databases (gitignored)
├── outputs/                  ← Generated files (gitignored)
└── attachments/              ← Resume (gitignored)
```

---

## Notes

- Uses Playwright (headless Chromium) with rate limiting — works on residential IPs, not cloud servers
- Jobs deduplicated by ID on every run — re-runs only add new jobs
- Salary auto-classified: annual / hourly / missing
- For Austrian/German market: add `Künstliche Intelligenz` and `Maschinelles Lernen` to keywords
