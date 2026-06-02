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

from dotenv import load_dotenv

# If _personal/ exists, load .env and data from there (personal mode).
# If not, use root paths (clean product mode for new users).
BASE_DIR = Path(__file__).parent
PERSONAL_DIR = BASE_DIR / "_personal"
IS_PERSONAL = PERSONAL_DIR.exists()

if IS_PERSONAL:
    load_dotenv(PERSONAL_DIR / ".env")
    DATA_DIR = PERSONAL_DIR / "data"
    OUTPUTS_DIR = PERSONAL_DIR / "outputs"
else:
    load_dotenv(BASE_DIR / ".env")
    DATA_DIR = BASE_DIR / "data"
    OUTPUTS_DIR = BASE_DIR / "outputs"

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

DATA_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

CONFIG_FILE = (PERSONAL_DIR if IS_PERSONAL else BASE_DIR) / "config.json"

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

# Handle to the live pipeline thread so a new Run can force the previous
# session to wind down before starting completely fresh.
pipeline_thread = None

def log(msg):
    # flush=True ensures lines appear in the terminal immediately even when
    # stdout is piped (e.g. under `conda run`, IDE consoles, log files).
    print(msg, flush=True)
    state["log"].append(msg)

# ─── Pacing (anti-rate-limit jitter) ──────────────────────────────────────────
# All delays keep randomness — constant intervals are the easiest bot signal —
# but the tier controls how aggressive the pace is. "safe" is the old overnight
# pace; "balanced" is the interactive default; "fast" is for small/test runs.
SPEED_PROFILES = {
    "fast":     {"between": (2, 4),   "page_ms": (1500, 2500),
                 "batch_every": 0,    "batch_pause": (0, 0),   "login_ms": (3000, 5000)},
    "balanced": {"between": (4, 8),   "page_ms": (2000, 3500),
                 "batch_every": 40,   "batch_pause": (20, 35), "login_ms": (4000, 6000)},
    "safe":     {"between": (8, 15),  "page_ms": (3000, 5000),
                 "batch_every": 25,   "batch_pause": (45, 90), "login_ms": (6000, 9000)},
}

def _profile(config):
    return SPEED_PROFILES.get(config.get("speed", "balanced"), SPEED_PROFILES["balanced"])

def interruptible_sleep(seconds):
    """Sleep in ~0.3s slices, bailing the instant a stop is requested.
    Returns False if interrupted, True if it slept the full duration. This is
    what makes Stop feel instant instead of waiting out a 90s pause."""
    end = time.time() + seconds
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            return True
        if state["stop_requested"]:
            return False
        time.sleep(min(0.3, remaining))

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
    """Merge .env secrets (take priority) with config.json preferences."""
    cfg = {}
    # Load preferences from config.json (keywords, location, profession)
    config_path = CONFIG_FILE
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    # Secrets from .env always take priority
    for env_key, cfg_key in [("LINKEDIN_EMAIL", "email"),
                              ("LINKEDIN_PASSWORD", "password")]:
        val = os.environ.get(env_key, "")
        if val:
            cfg[cfg_key] = val
    # LLM config — new unified keys with legacy fallback
    cfg.setdefault("llm_provider", os.environ.get("LLM_PROVIDER", "anthropic"))
    cfg.setdefault("llm_model", os.environ.get("LLM_MODEL", "claude-sonnet-4-6"))
    cfg.setdefault("speed", os.environ.get("SPEED", "balanced"))
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        cfg["llm_api_key"] = api_key
    return jsonify(cfg)

def _persist_config(cfg):
    """Save non-sensitive preferences to config.json. Secrets stay in .env."""
    pref_keys = ["keywords", "location", "profession", "llm_provider", "llm_model",
                 "llm_base_url", "speed"]
    out = {}
    # Preserve existing preferences if not in this request
    config_path = CONFIG_FILE
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                for k in pref_keys:
                    if k in (existing := json.load(f)):
                        out[k] = existing[k]
        except Exception:
            pass
    for k in pref_keys:
        v = cfg.get(k, "")
        if k == "keywords" and isinstance(v, list):
            v = ", ".join(v)
        if v:
            out[k] = v
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"Warning: could not save config.json: {e}")

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
    # Always allow reset, even when "running" is True — this rescues the user
    # from a stuck pipeline (e.g. Playwright hang). The background thread (if
    # actually alive) will see stop_requested on its next checkpoint and exit;
    # if it was a stale flag from a crashed run, this just clears it.
    was_running = state["running"]
    state["running"] = False
    state["stop_requested"] = True if was_running else False
    state["stage"] = ""
    state["log"] = []
    state["jobs"] = []
    state["scored_jobs"] = []
    state["clusters"] = []
    state["study_plan"] = []
    state["error"] = None
    if was_running:
        log("⚠ Force-reset while running — any background work will be discarded.")
    else:
        log("Pipeline reset. Ready to run.")
    return jsonify({"ok": True})

@app.route("/run", methods=["POST"])
def run():
    global pipeline_thread

    # Run = a brand-new session. If a previous pipeline is still alive (or left
    # a stale running flag), signal it to stop and let it wind down its browser
    # before we wipe state and start fresh — "like a new app.py was started".
    if state["running"] or (pipeline_thread and pipeline_thread.is_alive()):
        state["stop_requested"] = True
        if pipeline_thread and pipeline_thread.is_alive():
            pipeline_thread.join(timeout=12)
        state["running"] = False

    data = request.form
    files = request.files
    mode = data.get("mode")

    single_run = data.get("single_run", "") in ("1", "true", "True", "on")

    config = {
        "mode": mode,
        "single_run": single_run,
        "speed": "fast" if single_run else (data.get("speed", "") or "balanced"),
        "email": data.get("email", ""),
        "password": data.get("password", ""),
        "keywords": [k.strip() for k in data.get("keywords", "").split(",") if k.strip()],
        "location": data.get("location", ""),
        "llm_provider": data.get("llm_provider", "") or os.environ.get("LLM_PROVIDER", "anthropic"),
        "llm_model": data.get("llm_model", "") or os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
        "llm_api_key": data.get("llm_api_key", "") or os.environ.get("LLM_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", ""),
        "llm_base_url": data.get("llm_base_url", "") or os.environ.get("LLM_BASE_URL", ""),
        "time_filter": data.get("time_filter", "r604800"),
        "pages": 1 if single_run else int(data.get("pages", 5)),
        "profession": data.get("profession", "").strip(),
        "resume_text": ""
    }

    # A single test run is login → 1 JD → score. Always score, never cluster
    # (clustering one job is meaningless), regardless of the selected mode.
    if single_run:
        config["mode"] = mode = "with_scoring"

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

    # Persist form values so they prefill on next page load
    _persist_config(config)

    # Validate API key before launching pipeline (fail fast)
    if mode in ("with_scoring", "full"):
        try:
            _llm_ping(config)
        except Exception as e:
            return jsonify({"error": f"LLM API key / connection invalid: {e}"}), 400

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
    pipeline_thread = thread

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

# ─── Provider / Model Registry ────────────────────────────────────────────────
# Verified June 2026. For each provider:
#   sdk       — which client path ("anthropic" native, or "openai"-compatible)
#   base_url  — OpenAI-compatible endpoint (None = SDK default / native host)
#   models    — {model_id: max_output_tokens}. NOTE: context window (how much
#               INPUT a model accepts, often 200K–1M) is NOT the same as the
#               max OUTPUT tokens a single call may return. The number below is
#               the OUTPUT ceiling — that's what max_tokens must be clamped to.
PROVIDERS = {
    "anthropic": {
        "sdk": "anthropic",
        "base_url": None,
        "models": {
            "claude-opus-4-8":   64000,
            "claude-sonnet-4-6": 64000,
            "claude-haiku-4-5":  32000,
        },
    },
    "deepseek": {
        "sdk": "openai",
        "base_url": "https://api.deepseek.com",
        "models": {
            # deepseek-chat / deepseek-reasoner are DEPRECATED — do not use.
            "deepseek-v4-pro":   65536,
            "deepseek-v4-flash": 65536,
        },
    },
    "gemini": {
        "sdk": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": {
            "gemini-2.5-pro":          65536,
            "gemini-2.5-flash":        65536,
            "gemini-3-flash-preview":  65536,
        },
    },
    "openai": {
        "sdk": "openai",
        "base_url": None,
        "models": {
            "gpt-4o":      16000,
            "gpt-4o-mini": 16000,
        },
    },
    "llama": {
        "sdk": "openai",
        "base_url": "https://api.llama.com/compat/v1/",
        "models": {
            "Llama-4-Maverick-17B-128E-Instruct-FP8": 16000,
            "Llama-4-Scout-17B-16E-Instruct":         16000,
        },
    },
    "custom": {
        "sdk": "openai",
        "base_url": None,   # user supplies llm_base_url
        "models": {},        # user types any model id
    },
}

# Fallback output ceiling for unknown / user-typed models.
DEFAULT_MAX_OUTPUT = 8000

# Automatic parallel-scoring concurrency per provider. Tuned to stay comfortably
# under each provider's default rate limits — the user never sets this. DeepSeek
# is generous; the rest are kept conservative so low API tiers don't hit 429s.
PROVIDER_WORKERS = {
    "anthropic": 4,
    "deepseek":  8,
    "gemini":    4,
    "openai":    4,
    "llama":     3,
    "custom":    3,
}

def _auto_workers(config, job_count):
    """Pick a safe number of parallel scoring workers automatically.
    Never exceeds the number of jobs, and an optional SCORE_WORKERS env var
    lets a power user override without any UI."""
    if config.get("single_run") or job_count <= 1:
        return 1
    env = os.environ.get("SCORE_WORKERS")
    if env:
        try:
            return max(1, min(int(env), 12))
        except ValueError:
            pass
    base = PROVIDER_WORKERS.get(config.get("llm_provider", "anthropic"), 3)
    return max(1, min(base, job_count))

# Substrings that mean the browser/context is gone for good. Once we see one,
# retrying just burns 45s per attempt for hours (the original 4-hour hang) —
# so we abort the scrape and keep whatever we already have.
_FATAL_PW_SUBSTRINGS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "context has been closed",
    "context was destroyed",
    "browser closed",
    "connection closed",
    "has crashed",
    "crashed",
)

def _is_fatal_pw_error(e):
    msg = str(e).lower()
    return any(s in msg for s in _FATAL_PW_SUBSTRINGS)

def _provider_spec(provider):
    # Unknown provider name → treat as a custom OpenAI-compatible endpoint.
    return PROVIDERS.get(provider, PROVIDERS["custom"])

def _model_max_output(provider, model):
    return _provider_spec(provider).get("models", {}).get(model, DEFAULT_MAX_OUTPUT)

def _resolve_max_tokens(config, want):
    """Clamp a desired output-token budget to the chosen model's real ceiling.
    Fixes the old hardcoded 2000 cap that truncated output on large models."""
    cap = _model_max_output(config.get("llm_provider", "anthropic"),
                            config.get("llm_model", ""))
    return max(256, min(want, cap))

# ─── LLM Helpers (multi-provider) ─────────────────────────────────────────────
def _llm_client(config):
    """Return (sdk_name, client) for the configured provider."""
    provider = config.get("llm_provider", "anthropic")
    api_key = config.get("llm_api_key", "")
    spec = _provider_spec(provider)
    # Explicit user override (custom) wins over the registry default.
    url = config.get("llm_base_url", "") or spec.get("base_url")

    if spec["sdk"] == "anthropic":
        import anthropic
        kwargs = {"api_key": api_key}
        if url:
            kwargs["base_url"] = url
        return ("anthropic", anthropic.Anthropic(**kwargs))
    else:
        import openai
        kwargs = {"api_key": api_key}
        if url:
            kwargs["base_url"] = url
        return ("openai", openai.OpenAI(**kwargs))

def _llm_ping(config):
    """Quick validation call to check API key / connectivity."""
    sdk, client = _llm_client(config)
    model = config.get("llm_model", "claude-sonnet-4-6")
    if sdk == "anthropic":
        client.messages.create(model=model, max_tokens=1,
                               messages=[{"role": "user", "content": "ping"}])
    else:
        client.chat.completions.create(model=model, max_tokens=1,
                                       messages=[{"role": "user", "content": "ping"}])

def _llm_chat(config, prompt, max_tokens=2000):
    """Send a prompt and return the text response. Routes to correct SDK.
    Output budget is clamped to the model's ceiling and usage is logged so the
    real input/output token counts are visible in the live log."""
    sdk, client = _llm_client(config)
    model = config.get("llm_model", "claude-sonnet-4-6")
    capped = _resolve_max_tokens(config, max_tokens)
    if sdk == "anthropic":
        resp = client.messages.create(
            model=model, max_tokens=capped,
            messages=[{"role": "user", "content": prompt}])
        try:
            u = resp.usage
            log(f"  · tokens in={u.input_tokens} out={u.output_tokens} (cap {capped})")
        except Exception:
            pass
        return resp.content[0].text.strip()
    else:
        resp = client.chat.completions.create(
            model=model, max_tokens=capped,
            messages=[{"role": "user", "content": prompt}])
        try:
            u = resp.usage
            log(f"  · tokens in={u.prompt_tokens} out={u.completion_tokens} (cap {capped})")
        except Exception:
            pass
        return resp.choices[0].message.content.strip()

# ─── Pipeline ─────────────────────────────────────────────────────────────────
def run_pipeline(config):
    single = config.get("single_run", False)
    try:
        mode = config["mode"]

        if single:
            log("▶ Single test run: login → find one job description → score it.")
        state["stage"] = ("Test run: scraping one job..." if single
                          else "Scraping LinkedIn + fetching descriptions...")
        scrape_jobs(config)

        if state["stop_requested"]:
            raise StopIteration("Stopped by user after scraping")

        # Single run must end with a usable JD; surface a clear error otherwise.
        if single and not any(j.get("description") for j in state["jobs"]):
            raise RuntimeError("No job description could be extracted after "
                               "checking several cards. Try again or widen keywords.")

        if mode in ["with_scoring", "full"]:
            state["stage"] = "Scoring jobs with AI..."
            score_jobs(config)

        if mode == "full" and not state["stop_requested"]:
            state["stage"] = "Generating skill clusters and study plan..."
            generate_clusters_and_plan(config)

        # A test run is throwaway — don't pollute the persistent job database.
        if not single:
            save_jobs()
        state["stage"] = "Done ✓"
        state["running"] = False
        log("✓ Test run complete — one job scored." if single
            else "✓ Pipeline complete. Download your files below.")

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
    """Extract job description. LinkedIn uses hashed class names so we rely
    on text landmarks rather than CSS selectors."""
    # Landmarks LinkedIn uses for the JD section (English + German)
    landmarks = ["About the job", "Job description",
                 "Über den Job", "Stellenbeschreibung"]

    # Find which landmark is on the page
    try:
        body = page.inner_text("body")
    except:
        return ""
    marker = None
    for lm in landmarks:
        if lm in body:
            marker = lm
            break
    if not marker:
        return ""

    # Try section/article containing the landmark for cleaner extraction
    for tag in ["section", "article"]:
        try:
            container = page.locator(tag).filter(has_text=marker).first
            if container.count():
                text = container.inner_text()
                idx = text.find(marker)
                if idx >= 0:
                    desc = text[idx + len(marker):].strip()
                    if len(desc) > 200:
                        return desc[:12000]
        except:
            pass

    # Fallback: body text split on the landmark
    desc = body.split(marker)[-1].strip()
    return desc[:12000] if desc else ""

# ─── Helper: extract salary from page body ────────────────────────────────────
def extract_salary(page):
    """Returns (confidence, salary_text). confidence: 'verified' | 'unverified' | 'none'."""
    salary_keywords = [
        "salary", "gehalt", "compensation", "vergütung", "€", "$", "£",
        "/yr", "/hr", "per year", "per hour", "annually", "jährlich",
        "monatlich", "hourly", "k/y", "pro jahr", "pro monat",
    ]

    def _has_salary_keyword(line):
        lower = line.lower()
        return any(kw.lower() in lower for kw in salary_keywords)

    def _clean(text):
        return re.sub(r'\s*·.*$', '', text).strip()

    salary_patterns = [
        r'[\$€£]\s*[\d,\.]+\s*[kK]?\s*[-–]\s*[\$€£]?\s*[\d,\.]+\s*[kK]?',
        r'[\d,\.]+\s*[kK]?\s*[-–]\s*[\d,\.]+\s*[kK]?\s*(EUR|USD|GBP|€|\$)',
        r'[\$€£]\s*[\d,\.]+\s*(per hour|per year|\/hr|\/yr|annually)',
    ]

    try:
        # High confidence: LinkedIn's own salary elements
        for sel in [".salary-compensation", "[class*='salary']",
                     ".jobs-unified-top-card__job-insight"]:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if text and 3 < len(text) < 200 and _has_salary_keyword(text):
                        return ("verified", _clean(text))
            except:
                pass

        # Medium confidence: regex match on a line with a salary keyword nearby
        body = page.inner_text("body")
        for line in body.split("\n"):
            line = line.strip()
            if not _has_salary_keyword(line):
                continue
            for pattern in salary_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    return ("unverified", _clean(line))
    except:
        pass
    return ("none", "")

# ─── Step 1: Scrape + Fetch Descriptions (merged, single session) ─────────────
def scrape_jobs(config):
    from playwright.sync_api import sync_playwright
    import re as _re

    all_jobs = []
    seen = set()           # dedup during scrape — prevents duplicate navigations
    job_counter = 0        # for periodic long pauses

    prof = _profile(config)
    single = config.get("single_run", False)
    single_tries = 0       # how many cards we've opened looking for a JD
    SINGLE_MAX_TRIES = 4    # checkpoint 2: try a few cards before flagging error
    single_done = False

    # Death-spiral guards. If the browser/context dies, every later navigation
    # throws after a full timeout — hundreds of those is the original 4-hour
    # hang. We bail the moment the session is fatally gone, or after too many
    # consecutive failures (a soft-ban / dead session), and save what we have.
    consecutive_fail = 0
    MAX_CONSECUTIVE_FAIL = 6
    session_dead = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

# ── Login ──────────────────────────────────────────────────────────────
        log("Logging into LinkedIn...")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        try:
            # LinkedIn renders hidden autofill input stubs that come BEFORE the
            # real visible inputs in DOM order. `.first` without `:visible`
            # focuses a hidden input and keystrokes are silently lost.
            email_input = page.locator('input[type="email"]:visible').first
            email_input.wait_for(state="visible", timeout=15000)
            email_input.click()
            page.wait_for_timeout(300)
            page.keyboard.type(config["email"], delay=50)
            page.wait_for_timeout(500)
            pwd_input = page.locator('input[type="password"]:visible').first
            pwd_input.click()
            page.wait_for_timeout(300)
            page.keyboard.type(config["password"], delay=50)
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            page.wait_for_timeout(random.randint(*prof["login_ms"]))
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
                    page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(random.randint(*prof["page_ms"]))
                except Exception as e:
                    if _is_fatal_pw_error(e):
                        log(f"  ✗ Browser session lost on search page — aborting scrape. ({str(e)[:80]})")
                        session_dead = True
                        break
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
                        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
                        page.wait_for_timeout(random.randint(*prof["page_ms"]))
                        consecutive_fail = 0  # a clean navigation = session healthy
                        if single:
                            single_tries += 1

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
                        salary_conf, salary_text = extract_salary(page)
                        job["salary"] = salary_text
                        job["salary_confidence"] = salary_conf

                        job_counter += 1
                        if job_counter % 10 == 0:
                            status = "✓" if job["description"] else "⚠ no desc"
                            log(f"  [{job_counter}] {job['title'][:45]} — {status}")

                    except Exception as e:
                        if _is_fatal_pw_error(e):
                            log(f"  ✗ Browser session lost — aborting scrape, saving partial. ({str(e)[:80]})")
                            session_dead = True
                            all_jobs.append(job)
                            state["jobs"] = all_jobs
                            break
                        consecutive_fail += 1
                        log(f"  Error fetching {card_data['title'][:40]}: {str(e)[:80]} "
                            f"({consecutive_fail}/{MAX_CONSECUTIVE_FAIL})")
                        if consecutive_fail >= MAX_CONSECUTIVE_FAIL:
                            log(f"  ✗ {consecutive_fail} failures in a row — session likely "
                                f"dead or blocked. Aborting, saving partial.")
                            session_dead = True
                            all_jobs.append(job)
                            state["jobs"] = all_jobs
                            break

                    all_jobs.append(job)
                    state["jobs"] = all_jobs  # live update for status endpoint

                    # ── Single test run: stop at the first usable JD ───────────
                    if single:
                        if job.get("description"):
                            log(f"  ✓ Found a job description on try {single_tries} — scoring it.")
                            all_jobs[:] = [job]
                            state["jobs"] = all_jobs
                            single_done = True
                            break
                        if single_tries >= SINGLE_MAX_TRIES:
                            log(f"  ✗ No description found after {single_tries} cards.")
                            break
                        # try the next card quickly, no long pause
                        interruptible_sleep(random.uniform(1, 2))
                        continue

                    # ── Random wait between jobs ───────────────────────────────
                    every = prof["batch_every"]
                    if every and job_counter > 0 and job_counter % every == 0:
                        pause = random.randint(*prof["batch_pause"])
                        log(f"  ⏸ Pause {pause}s every {every} jobs...")
                        if not interruptible_sleep(pause):
                            break
                    else:
                        if not interruptible_sleep(random.uniform(*prof["between"])):
                            break

                if single_done or state["stop_requested"] or session_dead:
                    break
                # Wait between search result pages
                interruptible_sleep(random.uniform(*prof["between"]))

            if single_done or state["stop_requested"] or session_dead:
                break

        browser.close()

    log(f"Total unique jobs scraped: {len(all_jobs)}")
    log(f"  With descriptions: {len([j for j in all_jobs if j.get('description')])}")
    state["jobs"] = all_jobs

# ─── Step 2: Score Jobs ───────────────────────────────────────────────────────
def _score_one_job(config, job):
    """Score a single job in place. Safe to call from worker threads."""
    resume = config.get("resume_text", "No resume provided")

    # Only pass salary if we got it from a reliable source
    salary_line = ""
    if job.get("salary_confidence") == "verified" and job.get("salary"):
        salary_line = f"SALARY: {job['salary']}\n"

    prompt = f"""You are a hiring advisor evaluating a candidate for a specific job. Be direct — no flattery, no filler.

Compare the resume against the job requirements. Consider: seniority match, skill overlap, location/visa fit, realistic callback odds. Only mention compensation if it is listed and relevant.

RESUME:
{resume}

JOB:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
{salary_line}
DESCRIPTION:
{job.get('description', '')[:12000]}

Return a JSON object with exactly these keys. Do NOT wrap the response in markdown or add any other text:
{{
  "fit_score": <0-100>,
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1", "skill2"],
  "response_probability": <0-100>,
  "general_gaps": "2 honest sentences on the biggest gaps",
  "resume_suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
  "verdict": "One sentence: apply or skip, and why"
}}"""

    try:
        # 64K requested budget — clamped per-model by _resolve_max_tokens, so a
        # 64K/65K model gets full headroom and a smaller model gets its own max.
        # Scoring JSON is ~3K tokens, so this is safety headroom, not extra cost.
        text = _llm_chat(config, prompt, max_tokens=64000)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        job.update(result)
        job["scored"] = True
    except Exception as e:
        log(f"  Error scoring {job['title'][:40]}: {e}")
    return job

def score_jobs(config):
    from concurrent.futures import ThreadPoolExecutor

    jobs = state["jobs"]
    to_score = [j for j in jobs if j.get("description")]
    if not to_score:
        state["scored_jobs"] = []
        log("Scoring complete: 0 jobs had descriptions to score")
        return

    # Score in parallel — the LLM call is the bottleneck, so concurrency cuts
    # wall-clock time hugely. Worker count is chosen automatically per provider
    # to stay under rate limits; the user never has to think about it. These
    # workers only make HTTP/LLM calls — they never touch Playwright.
    workers = _auto_workers(config, len(to_score))

    scored = []
    lock = threading.Lock()
    done = 0
    total = len(to_score)
    log(f"Scoring {total} jobs with {workers} parallel workers...")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_score_one_job, config, j) for j in to_score]
        for fut in futures:
            if state["stop_requested"]:
                fut.cancel()  # cancels only not-yet-started tasks
        for fut in futures:
            if fut.cancelled():
                continue
            try:
                job = fut.result()
            except Exception as e:
                log(f"  Worker error: {e}")
                continue
            with lock:
                scored.append(job)
                state["scored_jobs"] = list(scored)  # live update for status
                done += 1
                if done % 5 == 0 or done == total:
                    log(f"  Scored {done}/{total}")
            if state["stop_requested"]:
                log(f"  Stop requested — halting scoring at {done}/{total}")
                for f in futures:
                    f.cancel()

    state["scored_jobs"] = scored
    log(f"Scoring complete: {len([j for j in scored if j.get('scored')])} jobs scored")

# ─── Step 3: Clusters + Plan ──────────────────────────────────────────────────
def generate_clusters_and_plan(config):
    profession = config.get("profession", "the relevant field")
    jobs = state["scored_jobs"] or state["jobs"]
    resume = config.get("resume_text", "")

    all_missing = []
    for job in jobs:
        all_missing.extend(job.get("missing_skills", []))
    freq = Counter(all_missing).most_common(30)
    skill_list = "\n".join([f"- {s} ({c}x)" for s, c in freq])
    job_summaries = "\n".join([
        f"- {j['title']} @ {j['company']} | fit: {j.get('fit_score', '?')} | missing: {', '.join(j.get('missing_skills', [])[:3])}"
        for j in sorted(jobs, key=lambda x: x.get('fit_score', 0), reverse=True)[:30]
    ])

    location = config.get("location", "")
    location_line = f" targeting jobs in/around {location}." if location else ""

    prompt = f"""You are a career strategist building a personalised skill-up plan.

A candidate is applying to {len(jobs)} job listings{location_line} Their resume and aggregated skill gaps are below.

1. SKILL CLUSTERS: Group missing skills into 5-7 thematic clusters. For each: name, skills (list), score_boost (0-15 — how many fit-score points this adds), jobs_impacted (count), days_to_learn, one free resource (URL or book title), priority (high/medium/low).

2. STUDY PLAN: 4-week day-by-day learning roadmap. Highest-ROI skills first. Week 4 reserved for applications + interview prep. Each day: focus area, 2-3 concrete tasks, one deliverable, 2-4 hours.

RESUME:
{resume}

TOP JOBS (by fit score):
{job_summaries}

MISSING SKILLS (by frequency across all jobs):
{skill_list}

Return a JSON object. Do NOT wrap the response in markdown or add any other text:
{{"clusters": [{{"name":"","skills":[],"score_boost":0,"jobs_impacted":0,"days_to_learn":0,"resource":"","priority":"high"}}],
"study_plan": [{{"week":1,"theme":"","days":[{{"day":1,"focus":"","tasks":["","",""],"deliverable":"","hours":3}}]}}]}}"""

    try:
        text = _llm_chat(config, prompt, max_tokens=64000)
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
                f.write(f"  Days to learn: {c.get('days_to_learn', c.get('days', '?'))}\n")
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
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    print("Starting Job Scraper Dashboard...")
    print(f"Open http://localhost:{port} in your browser")
    app.run(debug=False, host=host, port=port)