"""
Job Scraper Dashboard — Flask Backend
Run: python app.py
Open: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_file
import os, json, csv, re, time, threading, random
from pathlib import Path
from collections import Counter
import tempfile

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = BASE_DIR / "outputs"
DATA_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

JOBS_FILE           = DATA_DIR / "linkedin_jobs.json"
SCORED_FILE         = DATA_DIR / "linkedin_jobs_scored.json"
APPLIED_FILE        = DATA_DIR / "applied.json"
NOT_INTERESTED_FILE = DATA_DIR / "not_interested.json"
REJECTED_FILE       = DATA_DIR / "rejected.json"
INTERESTED_FILE     = DATA_DIR / "interested.json"
ACTION_NEEDED_FILE  = DATA_DIR / "action_needed.json"
EXPIRED_FILE        = DATA_DIR / "expired.json"

# ─── State ────────────────────────────────────────────────────────────────────
state = {
    "running": False,
    "stop_requested": False,
    "stage": "",
    "log": [],
    "jobs": [],
    "scored_jobs": [],
    "clusters": [],
    "study_plan": [],
    "error": None
}

def log(msg):
    print(msg)
    state["log"].append(msg)

# ─── File Helpers ─────────────────────────────────────────────────────────────
def load_file(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_file(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_timestamp():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def remove_from_all(job_id):
    for path in [APPLIED_FILE, NOT_INTERESTED_FILE, REJECTED_FILE,
                 INTERESTED_FILE, ACTION_NEEDED_FILE, EXPIRED_FILE]:
        data = load_file(path)
        if job_id in data:
            data.pop(job_id)
            save_file(path, data)

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    with open(BASE_DIR / "dashboard.html", encoding="utf-8") as f:
        return f.read()

@app.route("/config")
def get_config():
    config_path = BASE_DIR / "config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route("/status")
def status():
    return jsonify({
        "running": state["running"],
        "stop_requested": state["stop_requested"],
        "stage": state["stage"],
        "log": state["log"][-50:],
        "job_count": len(state["jobs"]),
        "scored_count": len(state["scored_jobs"]),
        "error": state["error"]
    })

@app.route("/stop", methods=["POST"])
def stop():
    if state["running"]:
        state["stop_requested"] = True
        state["stage"] = "Stopping..."
        log("⚠ Stop requested — finishing current task then stopping...")
        return jsonify({"ok": True})
    return jsonify({"error": "Not running"}), 400

@app.route("/reset", methods=["POST"])
def reset():
    if state["running"]:
        return jsonify({"error": "Still running, stop first"}), 400
    state["stop_requested"] = False
    state["stage"] = ""
    state["log"] = []
    state["jobs"] = []
    state["scored_jobs"] = []
    state["clusters"] = []
    state["study_plan"] = []
    state["error"] = None
    log("Pipeline reset. Ready to run.")
    return jsonify({"ok": True})

@app.route("/run", methods=["POST"])
def run():
    if state["running"]:
        return jsonify({"error": "Already running"}), 400

    data = request.form
    files = request.files
    mode = data.get("mode")

    config = {
        "mode": mode,
        "email": data.get("email", ""),
        "password": data.get("password", ""),
        "keywords": [k.strip() for k in data.get("keywords", "").split(",") if k.strip()],
        "location": data.get("location", "Vienna"),
        "anthropic_key": data.get("anthropic_key", ""),
        "time_filter": data.get("time_filter", "r604800"),
        "pages": int(data.get("pages", 5)),
        "profession": data.get("profession", "").strip(),
        "resume_text": ""
    }

    if "resume" in files:
        resume_file = files["resume"]
        suffix = Path(resume_file.filename).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            resume_file.save(tmp.name)
            try:
                if suffix == ".pdf":
                    import pdfplumber
                    with pdfplumber.open(tmp.name) as pdf:
                        config["resume_text"] = "\n".join(p.extract_text() or "" for p in pdf.pages)
                elif suffix in [".docx", ".doc"]:
                    import docx
                    doc = docx.Document(tmp.name)
                    config["resume_text"] = "\n".join(p.text for p in doc.paragraphs)
            except Exception as e:
                log(f"Warning: could not extract resume text: {e}")

    state["running"] = True
    state["stop_requested"] = False
    state["log"] = []
    state["jobs"] = []
    state["scored_jobs"] = []
    state["clusters"] = []
    state["study_plan"] = []
    state["error"] = None
    state["stage"] = "Starting..."

    thread = threading.Thread(target=run_pipeline, args=(config,))
    thread.daemon = True
    thread.start()

    return jsonify({"ok": True})

@app.route("/download/<filetype>")
def download(filetype):
    if filetype == "csv":
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        path = generate_csv()
        return send_file(path, as_attachment=True, download_name=f"job_results_{date_str}.csv")
    elif filetype == "skills":
        return send_file(generate_skills_txt(), as_attachment=True, download_name="skill_clusters.txt")
    elif filetype == "plan":
        return send_file(generate_plan_txt(), as_attachment=True, download_name="study_plan.txt")
    return "Not found", 404

# ─── Job Status Routes ────────────────────────────────────────────────────────
@app.route("/applied", methods=["GET"])
def get_applied():
    return jsonify(load_file(APPLIED_FILE))

@app.route("/applied/mark", methods=["POST"])
def mark_applied():
    data = request.get_json()
    job = data.get("job")
    if not job:
        return jsonify({"error": "No job provided"}), 400
    job_id = job.get("url") or job.get("title")
    remove_from_all(job_id)
    job["applied_at"] = get_timestamp()
    applied = load_file(APPLIED_FILE)
    applied[job_id] = job
    save_file(APPLIED_FILE, applied)
    return jsonify({"ok": True})

@app.route("/applied/unmark", methods=["POST"])
def unmark_applied():
    data = request.get_json()
    job_id = data.get("job_id")
    applied = load_file(APPLIED_FILE)
    applied.pop(job_id, None)
    save_file(APPLIED_FILE, applied)
    return jsonify({"ok": True})

@app.route("/applied/reject", methods=["POST"])
def reject_applied():
    data = request.get_json()
    job_id = data.get("job_id")
    applied = load_file(APPLIED_FILE)
    job = applied.pop(job_id, None)
    save_file(APPLIED_FILE, applied)
    if job:
        job["rejected_at"] = get_timestamp()
        rejected = load_file(REJECTED_FILE)
        rejected[job_id] = job
        save_file(REJECTED_FILE, rejected)
    return jsonify({"ok": True})

@app.route("/applied/switch_type", methods=["POST"])
def switch_application_type():
    data = request.get_json()
    job_id = data.get("job_id")
    new_type = data.get("application_type")
    applied = load_file(APPLIED_FILE)
    if job_id in applied:
        applied[job_id]["application_type"] = new_type
        save_file(APPLIED_FILE, applied)
    return jsonify({"ok": True})

@app.route("/not_interested", methods=["GET"])
def get_not_interested():
    return jsonify(load_file(NOT_INTERESTED_FILE))

@app.route("/not_interested/mark", methods=["POST"])
def mark_not_interested():
    data = request.get_json()
    job = data.get("job")
    if not job:
        return jsonify({"error": "No job provided"}), 400
    job_id = job.get("url") or job.get("title")
    remove_from_all(job_id)
    job["hidden_at"] = get_timestamp()
    ni = load_file(NOT_INTERESTED_FILE)
    ni[job_id] = job
    save_file(NOT_INTERESTED_FILE, ni)
    return jsonify({"ok": True})

@app.route("/not_interested/restore", methods=["POST"])
def restore_not_interested():
    data = request.get_json()
    job_id = data.get("job_id")
    ni = load_file(NOT_INTERESTED_FILE)
    ni.pop(job_id, None)
    save_file(NOT_INTERESTED_FILE, ni)
    return jsonify({"ok": True})

@app.route("/rejected", methods=["GET"])
def get_rejected():
    return jsonify(load_file(REJECTED_FILE))

@app.route("/rejected/restore", methods=["POST"])
def restore_rejected():
    data = request.get_json()
    job_id = data.get("job_id")
    rejected = load_file(REJECTED_FILE)
    job = rejected.pop(job_id, None)
    save_file(REJECTED_FILE, rejected)
    if job:
        job.pop("rejected_at", None)
        job["applied_at"] = job.get("applied_at", get_timestamp())
        applied = load_file(APPLIED_FILE)
        applied[job_id] = job
        save_file(APPLIED_FILE, applied)
    return jsonify({"ok": True})

@app.route("/interested", methods=["GET"])
def get_interested():
    return jsonify(load_file(INTERESTED_FILE))

@app.route("/interested/mark", methods=["POST"])
def mark_interested():
    data = request.get_json()
    job = data.get("job")
    if not job:
        return jsonify({"error": "No job provided"}), 400
    job_id = job.get("url") or job.get("title")
    remove_from_all(job_id)
    job["interested_at"] = get_timestamp()
    interested = load_file(INTERESTED_FILE)
    interested[job_id] = job
    save_file(INTERESTED_FILE, interested)
    return jsonify({"ok": True})

@app.route("/action_needed", methods=["GET"])
def get_action_needed():
    applied = load_file(APPLIED_FILE)
    action_needed = {k: v for k, v in applied.items() if v.get("action_needed_at")}
    return jsonify(action_needed)

@app.route("/action_needed/mark", methods=["POST"])
def mark_action_needed():
    data = request.get_json()
    job_id = data.get("job_id")
    applied = load_file(APPLIED_FILE)
    if job_id in applied:
        applied[job_id]["action_needed_at"] = get_timestamp()
        save_file(APPLIED_FILE, applied)
    return jsonify({"ok": True})

@app.route("/expired", methods=["GET"])
def get_expired():
    return jsonify(load_file(EXPIRED_FILE))

@app.route("/expired/mark", methods=["POST"])
def mark_expired():
    data = request.get_json()
    job = data.get("job")
    if not job:
        return jsonify({"error": "No job provided"}), 400
    job_id = job.get("url") or job.get("title")
    remove_from_all(job_id)
    job["expired_at"] = get_timestamp()
    expired = load_file(EXPIRED_FILE)
    expired[job_id] = job
    save_file(EXPIRED_FILE, expired)
    return jsonify({"ok": True})

@app.route("/salary_stats")
def salary_stats():
    jobs = state["scored_jobs"] or state["jobs"]
    annual  = [j for j in jobs if classify_salary(j.get("salary","")) == "annual"]
    hourly  = [j for j in jobs if classify_salary(j.get("salary","")) == "hourly"]
    missing = [j for j in jobs if classify_salary(j.get("salary","")) == "missing"]

    def summarize(group):
        return [{
            "title": j.get("title",""),
            "company": j.get("company",""),
            "location": j.get("location",""),
            "salary": j.get("salary",""),
            "fit_score": j.get("fit_score",""),
            "response_probability": j.get("response_probability",""),
            "matched_skills": j.get("matched_skills", []),
            "missing_skills": j.get("missing_skills", []),
            "verdict": j.get("verdict",""),
            "url": j.get("url","")
        } for j in sorted(group, key=lambda x: x.get("fit_score",0)
                          if x.get("fit_score","") != "" else 0, reverse=True)]

    return jsonify({"annual": summarize(annual), "hourly": summarize(hourly), "missing": summarize(missing)})

@app.route("/load_csv", methods=["POST"])
def load_csv():
    if "csv_file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["csv_file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400
    try:
        import io
        content_str = file.read().decode("utf-8")
        reader = csv.reader(io.StringIO(content_str))
        headers = next(reader, None)
        if not headers:
            return jsonify({"error": "Empty CSV"}), 400

        def col(name):
            for i, h in enumerate(headers):
                if h.lower().strip() == name.lower():
                    return i
            return None

        idx = {
            "title": col("title"), "company": col("company"), "location": col("location"),
            "salary": col("salary"), "salary_type": col("salary type"),
            "fit_score": col("fit score"), "response_probability": col("response probability"),
            "missing_skills": col("missing skills"), "verdict": col("verdict"), "url": col("url"),
        }

        annual, hourly, missing_salary = [], [], []

        for row in reader:
            if not row or not any(row) or row[0].startswith("---"):
                continue

            def get(key):
                i = idx.get(key)
                return row[i].strip() if i is not None and i < len(row) else ""

            salary_type = get("salary_type") or classify_salary(get("salary"))
            missing = [s.strip() for s in get("missing_skills").split("|") if s.strip()]

            job = {
                "title": get("title"), "company": get("company"), "location": get("location"),
                "salary": get("salary"), "fit_score": get("fit_score"),
                "response_probability": get("response_probability"),
                "missing_skills": missing, "matched_skills": [],
                "verdict": get("verdict"), "url": get("url"),
            }

            if salary_type == "annual": annual.append(job)
            elif salary_type == "hourly": hourly.append(job)
            else: missing_salary.append(job)

        def sort_by_fit(group):
            def fit_key(j):
                try: return int(j.get("fit_score", 0))
                except: return 0
            return sorted(group, key=fit_key, reverse=True)

        return jsonify({
            "annual": sort_by_fit(annual), "hourly": sort_by_fit(hourly),
            "missing": sort_by_fit(missing_salary),
            "total": len(annual) + len(hourly) + len(missing_salary)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Pipeline ─────────────────────────────────────────────────────────────────
def run_pipeline(config):
    try:
        mode = config["mode"]

        state["stage"] = "Scraping LinkedIn + fetching descriptions..."
        scrape_jobs(config)

        if state["stop_requested"]:
            raise StopIteration("Stopped by user after scraping")

        if mode in ["with_scoring", "full"]:
            state["stage"] = "Scoring jobs with AI..."
            score_jobs(config)

        if mode == "full" and not state["stop_requested"]:
            state["stage"] = "Generating skill clusters and study plan..."
            generate_clusters_and_plan(config)

        save_jobs()
        state["stage"] = "Done ✓"
        state["running"] = False
        log("✓ Pipeline complete. Download your files below.")

    except StopIteration as e:
        save_jobs()
        state["stage"] = "Stopped ⚠"
        state["running"] = False
        state["stop_requested"] = False
        log(f"⚠ Pipeline stopped: {e}")
        log("Partial results saved. Download CSV or reset to start fresh.")
    except Exception as e:
        import traceback
        state["error"] = str(e)
        state["stage"] = "Error"
        state["running"] = False
        log(f"✗ Error: {e}")
        log(traceback.format_exc())

def save_jobs():
    existing = {}
    if JOBS_FILE.exists():
        with open(JOBS_FILE) as f:
            for j in json.load(f):
                existing[j["id"]] = j
    for job in state["jobs"]:
        existing[job["id"]] = job
    with open(JOBS_FILE, "w") as f:
        json.dump(list(existing.values()), f, indent=2)

    if state["scored_jobs"]:
        scored_existing = {}
        if SCORED_FILE.exists():
            with open(SCORED_FILE) as f:
                for j in json.load(f):
                    scored_existing[j["id"]] = j
        for job in state["scored_jobs"]:
            scored_existing[job["id"]] = job
        with open(SCORED_FILE, "w") as f:
            json.dump(list(scored_existing.values()), f, indent=2)

    log(f"Saved {len(existing)} jobs to data/")

# ─── Helper: extract description from page body ───────────────────────────────
def extract_description(page):
    """Try CSS selector first, fall back to body text split."""
    # Try structured selectors
    for selector in [".jobs-description__content", ".description__text",
                     ".job-view-layout", "[class*='description']"]:
        try:
            el = page.query_selector(selector)
            if el:
                text = el.inner_text().strip()
                if len(text) > 200:
                    return text[:12000]
        except:
            pass

    # Fallback: body text split on "About the job"
    try:
        body = page.inner_text("body")
        if "About the job" in body:
            desc = body.split("About the job")[-1].strip()
            return desc[:12000]
    except:
        pass

    return ""

# ─── Helper: extract salary from page body ────────────────────────────────────
def extract_salary(page):
    salary_patterns = [
        r'[\$€£]\s*[\d,\.]+\s*[kK]?\s*[-–]\s*[\$€£]?\s*[\d,\.]+\s*[kK]?',
        r'[\d,\.]+\s*[kK]?\s*[-–]\s*[\d,\.]+\s*[kK]?\s*(EUR|USD|GBP|€|\$)',
        r'[\$€£]\s*[\d,\.]+\s*(per hour|per year|\/hr|\/yr|annually)',
    ]
    try:
        body = page.inner_text("body")
        for line in body.split("\n"):
            line = line.strip()
            for pattern in salary_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    return re.sub(r'\s*·.*$', '', line).strip()
    except:
        pass
    return ""

# ─── Step 1: Scrape + Fetch Descriptions (merged, single session) ─────────────
def scrape_jobs(config):
    from playwright.sync_api import sync_playwright
    import re as _re

    all_jobs = []
    seen = set()           # dedup during scrape — prevents duplicate navigations
    job_counter = 0        # for periodic long pauses

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

# ── Login ──────────────────────────────────────────────────────────────
        log("Logging into LinkedIn...")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        try:
            page.locator('input[type="email"]').first.fill(config["email"], force=True)
            page.wait_for_timeout(500)
            page.locator('input[type="password"]').first.fill(config["password"], force=True)
            page.wait_for_timeout(500)
            page.locator('button[type="submit"]').first.click(force=True)
            page.wait_for_timeout(random.randint(6000, 9000))
            current_url = page.url
            if "feed" in current_url or "jobs" in current_url:
                log(f"✓ Logged in — now on: {current_url}")
            else:
                page.screenshot(path="debug_login.png")
                log(f"✗ Login failed — ended up on: {current_url} — screenshot saved")
                browser.close()
                return
        except Exception as e:
            page.screenshot(path="debug_login.png")
            log(f"✗ Login failed: {e} — screenshot saved to debug_login.png")
            browser.close()
            return
        
        # ── Scrape each keyword ────────────────────────────────────────────────
        for keyword in config["keywords"]:
            if state["stop_requested"]:
                break
            log(f"Scraping: {keyword}")

            for page_num in range(0, config["pages"]):
                if state["stop_requested"]:
                    break

                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={keyword.replace(' ', '+')}"
                    f"&location={config['location']}"
                    f"&f_TPR={config['time_filter']}"
                    f"&sortBy=R&start={page_num * 25}"
                )

                try:
                    page.goto(search_url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(random.randint(3000, 5000))
                except Exception as e:
                    log(f"  Timeout on page {page_num+1} for '{keyword}' — skipping")
                    break

                # Scroll to load lazy elements
                for _ in range(3):
                    page.keyboard.press("End")
                    page.wait_for_timeout(random.randint(1200, 2000))

                job_cards = (
                    page.query_selector_all(".scaffold-layout__list-item") or
                    page.query_selector_all(".jobs-search__results-list li")
                )
                log(f"  Page {page_num+1}: {len(job_cards)} cards found")

                if len(job_cards) == 0:
                    break

                # ── Extract card metadata ──────────────────────────────────────
                cards_data = []
                for card in job_cards:
                    title_el = (
                        card.query_selector(".job-card-list__title--link span[aria-hidden='true']") or
                        card.query_selector(".base-search-card__title")
                    )
                    company_el = (
                        card.query_selector(".artdeco-entity-lockup__subtitle span") or
                        card.query_selector(".base-search-card__subtitle")
                    )
                    location_el = (
                        card.query_selector(".artdeco-entity-lockup__caption li span") or
                        card.query_selector(".job-search-card__location")
                    )
                    link_el = (
                        card.query_selector("a.job-card-list__title--link") or
                        card.query_selector("a.base-card__full-link")
                    )
                    id_el = (
                        card.query_selector("[data-job-id]") or
                        card.query_selector("[data-entity-urn]")
                    )

                    if not (title_el and link_el):
                        continue

                    job_id = ""
                    if id_el:
                        job_id = id_el.get_attribute("data-job-id") or ""
                        if not job_id:
                            urn = id_el.get_attribute("data-entity-urn") or ""
                            job_id = urn.split(":")[-1] if urn else ""

                    href = link_el.get_attribute("href") or ""
                    url = href if href.startswith("http") else "https://www.linkedin.com" + href

                    # Extract numeric job ID from URL as fallback
                    if not job_id:
                        match = _re.search(r'(\d{9,})', url)
                        job_id = match.group(1) if match else url

                    cards_data.append({
                        "id": job_id,
                        "title": title_el.inner_text().strip(),
                        "company": company_el.inner_text().strip() if company_el else "",
                        "location": location_el.inner_text().strip() if location_el else "",
                        "url": url,
                        "keyword": keyword,
                    })

                # ── Fetch description for each new card ────────────────────────
                for card_data in cards_data:
                    if state["stop_requested"]:
                        break

                    job_id = card_data["id"]

                    # Skip duplicates before navigating
                    if job_id in seen:
                        continue
                    seen.add(job_id)

                    job = {
                        **card_data,
                        "description": "",
                        "salary": "",
                        "scored": False,
                    }

                    # Navigate to job page
                    match = _re.search(r'(\d{9,})', card_data["url"])
                    job_url = (
                        f"https://www.linkedin.com/jobs/view/{match.group(1)}"
                        if match else card_data["url"]
                    )

                    try:
                        page.goto(job_url, timeout=45000, wait_until="domcontentloaded")
                        page.wait_for_timeout(random.randint(3000, 5000))

                        # Accept cookie consent if shown
                        for cookie_text in ["Accept", "Accept cookies"]:
                            try:
                                btn = page.query_selector(f"button:has-text('{cookie_text}')")
                                if btn:
                                    btn.click(force=True)
                                    page.wait_for_timeout(1000)
                                    break
                            except:
                                pass

                        # Expand full description
                        for btn_text in ["Show more", "See more"]:
                            try:
                                btn = page.query_selector(f"button:has-text('{btn_text}')")
                                if btn:
                                    btn.click(force=True)
                                    page.wait_for_timeout(800)
                                    break
                            except:
                                pass

                        job["description"] = extract_description(page)
                        job["salary"] = extract_salary(page)

                        job_counter += 1
                        if job_counter % 10 == 0:
                            status = "✓" if job["description"] else "⚠ no desc"
                            log(f"  [{job_counter}] {job['title'][:45]} — {status}")

                    except Exception as e:
                        log(f"  Error fetching {card_data['title'][:40]}: {e}")

                    all_jobs.append(job)
                    state["jobs"] = all_jobs  # live update for status endpoint

                    # ── Random wait between jobs ───────────────────────────────
                    # Every 25 jobs take a longer break to avoid rate limiting
                    if job_counter > 0 and job_counter % 25 == 0:
                        pause = random.randint(45, 90)
                        log(f"  ⏸ Pause {pause}s every 25 jobs...")
                        time.sleep(pause)
                    else:
                        time.sleep(random.uniform(8, 15))

                # Wait between search result pages
                time.sleep(random.uniform(5, 8))

        browser.close()

    log(f"Total unique jobs scraped: {len(all_jobs)}")
    log(f"  With descriptions: {len([j for j in all_jobs if j.get('description')])}")
    state["jobs"] = all_jobs

# ─── Step 2: Score Jobs ───────────────────────────────────────────────────────
def score_jobs(config):
    import anthropic
    resume = config.get("resume_text", "No resume provided")
    profession = config.get("profession", "the relevant field")
    client = anthropic.Anthropic(api_key=config.get("anthropic_key", ""))
    jobs = state["jobs"]
    scored = []

    for i, job in enumerate(jobs):
        if not job.get("description"):
            continue

        prompt = f"""You are a senior recruiter and career coach specialising in {profession or "the relevant field"} roles.

Evaluate this candidate for the specific job below. Be precise and honest, not generic.
Base your evaluation strictly on what is in the resume vs what the job actually requires.
Consider: location match, visa/work authorization if mentioned, seniority level, competition.

CANDIDATE RESUME:
{resume}

JOB TITLE: {job['title']}
COMPANY: {job['company']}
LOCATION: {job['location']}
JOB DESCRIPTION:
{job.get('description', '')[:12000]}

Respond ONLY in this exact JSON format, no other text:
{{
  "fit_score": <0-100>,
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1", "skill2"],
  "response_probability": <0-100>,
  "general_gaps": "2 honest sentences on the biggest gaps",
  "resume_suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
  "verdict": "One direct sentence: should they apply and why"
}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text.strip())
            job.update(result)
            job["scored"] = True
            if i % 5 == 0:
                log(f"  Scored {i+1}/{len(jobs)} — {job['title']} | fit: {result.get('fit_score')}")
        except Exception as e:
            log(f"  Error scoring {job['title']}: {e}")

        scored.append(job)

        if state["stop_requested"]:
            log(f"  Stopping scoring at job {i+1}/{len(jobs)}")
            break

        time.sleep(0.5)

    state["scored_jobs"] = scored
    log(f"Scoring complete: {len([j for j in scored if j.get('scored')])} jobs scored")

# ─── Step 3: Clusters + Plan ──────────────────────────────────────────────────
def generate_clusters_and_plan(config):
    import anthropic
    profession = config.get("profession", "the relevant field")
    client = anthropic.Anthropic(api_key=config.get("anthropic_key", ""))
    jobs = state["scored_jobs"] or state["jobs"]
    resume = config.get("resume_text", "")

    all_missing = []
    for job in jobs:
        all_missing.extend(job.get("missing_skills", []))
    freq = Counter(all_missing).most_common(40)
    skill_list = "\n".join([f"- {s} ({c}x)" for s, c in freq])
    job_summaries = "\n".join([
        f"- {j['title']} @ {j['company']} | fit: {j.get('fit_score', '?')} | missing: {', '.join(j.get('missing_skills', [])[:3])}"
        for j in sorted(jobs, key=lambda x: x.get('fit_score', 0), reverse=True)[:30]
    ])

    prompt = f"""You are a senior career coach specialising in {profession or "this field"}.

A candidate is applying to {len(jobs)} job listings. Based on their resume and skill gaps, do two things:

1. SKILL CLUSTERS: Group missing skills into 6-8 clusters. For each:
   name, skills, score_boost (0-15), jobs_impacted, days, resource, priority (high/medium/low)

2. STUDY PLAN: 4-week day-by-day plan. Highest ROI first. Week 4 = apply + polish.
   Each day: focus, tasks (3), deliverable, hours (2-4)

RESUME: {resume[:2000]}
TOP JOBS: {job_summaries}
MISSING SKILLS: {skill_list}

Respond ONLY in JSON:
{{"clusters": [{{"name":"","skills":[],"score_boost":0,"jobs_impacted":0,"days":0,"resource":"","priority":"high"}}],
"study_plan": [{{"week":1,"theme":"","days":[{{"day":1,"focus":"","tasks":["","",""],"deliverable":"","hours":3}}]}}]}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        state["clusters"] = result.get("clusters", [])
        state["study_plan"] = result.get("study_plan", [])
        log("Skill clusters and study plan generated")
    except Exception as e:
        log(f"Error generating clusters/plan: {e}")
        state["clusters"] = []
        state["study_plan"] = []

# ─── Salary Classification ────────────────────────────────────────────────────
def classify_salary(salary_str):
    if not salary_str or not salary_str.strip():
        return "missing"
    s = salary_str.lower()
    if any(x in s for x in ["/hr", "per hour", "hourly", "/h"]):
        return "hourly"
    if any(x in s for x in ["/yr", "per year", "annually", "year", "annual", "k/y"]):
        return "annual"
    numbers = re.findall(r"[\d]+", salary_str.replace(",", ""))
    if numbers:
        try:
            val = int(numbers[0])
            if val > 1000: return "annual"
            elif val < 500: return "hourly"
        except: pass
    return "annual"

# ─── File Generators ──────────────────────────────────────────────────────────
def generate_csv():
    jobs = state["scored_jobs"] or state["jobs"]
    for job in jobs:
        job["salary_type"] = classify_salary(job.get("salary", ""))

    annual  = [j for j in jobs if j["salary_type"] == "annual"]
    hourly  = [j for j in jobs if j["salary_type"] == "hourly"]
    missing = [j for j in jobs if j["salary_type"] == "missing"]

    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = OUTPUTS_DIR / f"job_results_{date_str}.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Title","Company","Location","Salary","Salary Type",
                         "Fit Score","Response Probability","Missing Skills","Verdict","URL"])

        def write_section(section_jobs, label):
            if section_jobs:
                writer.writerow([f"--- {label} ({len(section_jobs)} jobs) ---"])
                for job in sorted(section_jobs, key=lambda x: x.get("fit_score", 0), reverse=True):
                    writer.writerow([
                        job.get("title",""), job.get("company",""), job.get("location",""),
                        job.get("salary",""), job.get("salary_type",""),
                        job.get("fit_score",""), job.get("response_probability",""),
                        " | ".join(job.get("missing_skills",[])), job.get("verdict",""), job.get("url","")
                    ])
                writer.writerow([])

        write_section(annual, "ANNUAL SALARY")
        write_section(hourly, "HOURLY RATE")
        write_section(missing, "SALARY NOT LISTED")

    return str(path)

def generate_skills_txt():
    clusters = state.get("clusters", [])
    path = OUTPUTS_DIR / "skill_clusters.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("SKILL GAP ANALYSIS\n" + "=" * 60 + "\n\n")
        if not clusters:
            jobs = state["scored_jobs"] or state["jobs"]
            all_missing = []
            for job in jobs:
                all_missing.extend(job.get("missing_skills", []))
            for skill, count in Counter(all_missing).most_common():
                f.write(f"  {count:3d}x  {skill}\n")
        else:
            for c in sorted(clusters, key=lambda x: x.get("score_boost", 0), reverse=True):
                f.write(f"[{c.get('priority','').upper()}] {c['name']}\n")
                f.write(f"  Score boost:   +{c.get('score_boost', 0)} pts\n")
                f.write(f"  Jobs impacted: {c.get('jobs_impacted', '?')}\n")
                f.write(f"  Days to learn: {c.get('days', '?')}\n")
                f.write(f"  Resource:      {c.get('resource', '')}\n")
                f.write(f"  Skills:        {', '.join(c.get('skills', []))}\n\n")
    return str(path)

def generate_plan_txt():
    plan = state.get("study_plan", [])
    path = OUTPUTS_DIR / "study_plan.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("4-WEEK STUDY PLAN\n" + "=" * 60 + "\n\n")
        if not plan:
            f.write("Run in 'Full Analysis' mode to generate a personalized study plan.\n")
        else:
            for week in plan:
                f.write(f"WEEK {week['week']} — {week.get('theme', '')}\n" + "-" * 40 + "\n")
                for day in week.get("days", []):
                    f.write(f"\nDay {day['day']}: {day['focus']} ({day.get('hours', 3)} hrs)\n")
                    for task in day.get("tasks", []):
                        f.write(f"  □ {task}\n")
                    f.write(f"  → Deliverable: {day.get('deliverable', '')}\n")
                f.write("\n")
    return str(path)

if __name__ == "__main__":
    print("Starting Job Scraper Dashboard...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=False, port=5000)