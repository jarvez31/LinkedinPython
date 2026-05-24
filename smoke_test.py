"""
Smoke test for the pipeline — verifies each external dependency works
before committing to a full scrape. Run from project root:

    conda activate scraper
    python smoke_test.py
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
CFG_FILE = BASE / "config.json"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def ok(msg):   print(f"{GREEN}  ✓ {msg}{RESET}")
def bad(msg):  print(f"{RED}  ✗ {msg}{RESET}")
def warn(msg): print(f"{YELLOW}  ! {msg}{RESET}")
def step(n, msg): print(f"\n[{n}] {msg}")

failures = 0
def fail(msg):
    global failures
    failures += 1
    bad(msg)

# ─── 1. config.json ───────────────────────────────────────────────────────────
step(1, "Load config.json")
if not CFG_FILE.exists():
    fail(f"{CFG_FILE} not found")
    sys.exit(1)
with open(CFG_FILE, encoding="utf-8") as f:
    cfg = json.load(f)
for key in ["email", "password", "anthropic_key", "keywords", "location"]:
    val = cfg.get(key, "")
    if val:
        shown = val if key not in ("password", "anthropic_key") else (val[:6] + "..." + val[-4:])
        ok(f"{key} = {shown}")
    else:
        fail(f"{key} is empty")

# ─── 2. Python imports ────────────────────────────────────────────────────────
step(2, "Import required packages")
for mod in ["flask", "playwright.sync_api", "anthropic", "pdfplumber", "docx", "tinydb"]:
    try:
        __import__(mod)
        ok(f"import {mod}")
    except Exception as e:
        fail(f"import {mod} failed: {e}")

# ─── 3. Anthropic API key works ──────────────────────────────────────────────
step(3, "Verify Anthropic API key (1-token call)")
try:
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["anthropic_key"])
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=5,
        messages=[{"role": "user", "content": "Say 'ok'"}],
    )
    ok(f"API responded: {resp.content[0].text.strip()!r}  (model={resp.model})")
except Exception as e:
    fail(f"Anthropic API call failed: {e}")

# ─── 4. Playwright browser launch ─────────────────────────────────────────────
step(4, "Launch Playwright Chromium")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://example.com", timeout=15000)
        title = page.title()
        ok(f"navigated to example.com, title = {title!r}")
        browser.close()
except Exception as e:
    fail(f"Playwright failed: {e}")
    if "Executable doesn't exist" in str(e):
        warn("Run: playwright install chromium")

# ─── 5. LinkedIn login (the actual risky step) ────────────────────────────────
step(5, "LinkedIn login (the most failure-prone step)")
try:
    from playwright.sync_api import sync_playwright
    import random
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = ctx.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # LinkedIn renders 6 inputs: the first 3 are hidden autofill stubs,
        # the next 3 are the real visible ones. Without `:visible`, .first
        # grabs the hidden input and keystrokes go into the void.
        email_input = page.locator('input[type="email"]:visible').first
        email_input.wait_for(state="visible", timeout=15000)
        email_input.click()
        page.wait_for_timeout(300)
        page.keyboard.type(cfg["email"], delay=50)
        page.wait_for_timeout(500)
        typed_email = email_input.input_value()
        if typed_email != cfg["email"]:
            warn(f"email field shows {typed_email!r}, expected {cfg['email']!r}")

        pwd_input = page.locator('input[type="password"]:visible').first
        pwd_input.click()
        page.wait_for_timeout(300)
        page.keyboard.type(cfg["password"], delay=50)
        page.wait_for_timeout(500)
        typed_pwd = pwd_input.input_value()
        if len(typed_pwd) != len(cfg["password"]):
            warn(f"password length mismatch: typed {len(typed_pwd)}, expected {len(cfg['password'])}")

        page.keyboard.press("Enter")
        page.wait_for_timeout(8000)

        url = page.url
        page.screenshot(path=str(BASE / "smoke_login.png"))

        if "feed" in url or "jobs" in url or "mynetwork" in url:
            ok(f"login succeeded — landed on {url}")
        elif "checkpoint" in url or "challenge" in url:
            fail(f"login hit a CAPTCHA / challenge: {url}")
            warn("LinkedIn is asking for verification — log in manually once in a real browser, then retry.")
        elif "login" in url:
            fail(f"still on login page: {url}  (wrong creds, or fields didn't fill)")
        else:
            warn(f"ended on unexpected page: {url}")
        warn(f"screenshot saved → {BASE / 'smoke_login.png'}")
        browser.close()
except Exception as e:
    fail(f"login flow crashed: {e}")

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
if failures == 0:
    print(f"{GREEN}All checks passed — safe to run the full pipeline.{RESET}")
    sys.exit(0)
else:
    print(f"{RED}{failures} check(s) failed — fix above before running full pipeline.{RESET}")
    sys.exit(1)
