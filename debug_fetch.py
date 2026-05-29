from playwright.sync_api import sync_playwright
import json, os, re
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent
PERSONAL_DIR = BASE / "_personal"
IS_PERSONAL = PERSONAL_DIR.exists()

if IS_PERSONAL:
    load_dotenv(PERSONAL_DIR / ".env")
    DATA_DIR = PERSONAL_DIR / "data"
else:
    load_dotenv(BASE / ".env")
    DATA_DIR = BASE / "data"

EMAIL = os.environ.get("LINKEDIN_EMAIL", "")
PASSWORD = os.environ.get("LINKEDIN_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env")
    exit(1)

with sync_playwright() as p:
    print("Launching browser (non-headless for debugging)...")
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    page = context.new_page()

    # Login with aggressive waits
    print("Opening LinkedIn login page...")
    page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)
    
    print(f"Page URL: {page.url}")
    print("Waiting for username field...")
    
    try:
        page.wait_for_selector("#username", timeout=30000)
        print("✓ Username field found")
        page.fill("#username", EMAIL)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_timeout(8000)
        print(f"After login URL: {page.url}")
    except Exception as e:
        print(f"✗ Login failed: {e}")
        print(f"Current page HTML available for inspection")
        print(f"Current URL: {page.url}")
        browser.close()
        exit(1)
    
    # Check for checkpoint challenge
    if "checkpoint" in page.url:
        print("⚠ LinkedIn checkpoint detected — manual verification needed")
        print("Complete the challenge manually, then press Enter to continue...")
        input()
        page.wait_for_timeout(2000)
        print(f"Continuing from: {page.url}")

    # Save cookies
    cookies = context.cookies()
    print(f"Cookies saved: {len(cookies)}")

    # Get a job — prefer one with description to inspect it
    jobs = json.load(open(DATA_DIR / "linkedin_jobs.json"))
    job = jobs[0]  # Just take the first one
    
    # Or find one without description if any exist
    no_desc = [j for j in jobs if not j.get("description") or not j.get("description").strip()]
    if no_desc:
        job = no_desc[0]
        print(f"\n✓ Found job with empty description")
    else:
        print(f"\n✓ All jobs have descriptions — using first job to inspect selectors")
    print(f"\nTesting: {job['title']}")
    print(f"Raw URL: {job['url']}")

    # Normalise URL — strip everything after the job ID number
    job_url = job["url"].replace("at.linkedin.com", "www.linkedin.com")
    match = re.search(r'(https://www\.linkedin\.com/jobs/view/[\w-]+-(\d+))', job_url)
    if match:
        job_id = match.group(2)
        job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
    print(f"Clean URL: {job_url}")

    page.goto(job_url, timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    print(f"Page URL after goto: {page.url}")

    # Try accepting cookie consent
    for btn_text in ["Accept", "Accept cookies"]:
        btn = page.query_selector(f"button:has-text('{btn_text}')")
        if btn:
            print(f"Found cookie button: {btn_text}")
            btn.click(force=True)
            page.wait_for_timeout(2000)
            break

    text = page.inner_text("body")
    print(f"\nPage title: {page.title()}")
    print(f"About the job found: {'About the job' in text}")
    
    # Try to find description containers
    print("\n--- Selector Inspection ---")
    
    selectors = [
        ".show-more-less-html__markup",
        ".description__text",
        "article",
        ".job-details",
        "[data-test-id='job-details']",
        ".jobs-details__main-content",
    ]
    
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                text_sample = el.inner_text().strip()[:200]
                print(f"✓ {sel}: Found ({len(text_sample)} chars)")
                print(f"  Sample: {text_sample}...")
            else:
                print(f"✗ {sel}: Not found")
        except Exception as e:
            print(f"✗ {sel}: Error — {e}")
    
    # Check for "About the job" header
    print("\n--- Text Landmarks ---")
    if "About the job" in text:
        idx = text.find("About the job")
        print(f"✓ 'About the job' found at position {idx}")
        print(f"  Content after:\n{text[idx:idx+500]}...")
    else:
        print(f"✗ 'About the job' not found in body text")
    
    # Save full body text for manual inspection
    with open("/tmp/linkedin_page_debug.txt", "w") as f:
        f.write(text)
    print(f"\n✓ Full page text saved to /tmp/linkedin_page_debug.txt")
    print(f"First 1500 chars:\n{text[:1500]}")

    browser.close()