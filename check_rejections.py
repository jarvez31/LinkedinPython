import os
import re
import sys
import json
import imaplib
import email
from email.header import decode_header
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Load environment
dotenv_path = "/mnt/d/roksolana_mac/KarrierMultiSource/_personal/env"
if not Path(dotenv_path).exists():
    dotenv_path = "/mnt/d/roksolana_mac/KarrierMultiSource/_personal/.env"
load_dotenv(dotenv_path)

# Credentials loading
accounts = []
idx = 1
while True:
    email_val = os.getenv(f"REJECTION_EMAIL_{idx}")
    pass_val = os.getenv(f"REJECTION_EMAIL_{idx}_PASS")
    if not email_val or not pass_val:
        break
    accounts.append({
        "email": email_val,
        "password": pass_val.replace(" ", ""),
        "label": f"Email Account {idx}"
    })
    idx += 1

# Fallback to scraper credentials if no custom rejection emails are set
if not accounts:
    email_1 = os.getenv("LINKEDIN_EMAIL")
    pass_1 = os.getenv("LINKEDIN_EMAIL_APP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    if email_1 and pass_1:
        accounts.append({"email": email_1, "password": pass_1.replace(" ", ""), "label": "LinkedIn Account"})
        
    email_2 = os.getenv("XING_EMAIL")
    pass_2 = os.getenv("XING_EMAIL_APP_PASSWORD") or os.getenv("XING_GMAIL_APP_PASSWORD")
    if email_2 and pass_2:
        accounts.append({"email": email_2, "password": pass_2.replace(" ", ""), "label": "Xing Account"})

# Paths
db_dir = Path("/mnt/d/roksolana_mac/KarrierMultiSource/_personal/data")
outputs_dir = Path("/mnt/d/roksolana_mac/KarrierMultiSource/_personal/outputs")

rejected_json_path = db_dir / "rejected.json"
applied_json_path = db_dir / "applied.json"
csv_path = outputs_dir / "apply_combined_2026-08-12.csv"
checked_csv_path = outputs_dir / "apply_combined_checked.csv"

def log(msg):
    print(f"[Gmail Check] {msg}", flush=True)

if not accounts:
    log("Error: No email accounts configured with App Passwords in .env!")
    sys.exit(1)

# Confirmation/Acknowledgment keywords (signals APPLIED, NOT rejected)
ack_keywords = [
    "thank you for applying", "thank you for your application", "thank you for your interest",
    "eingangsbestätigung", "received your application", "application received",
    "vielen dank für deine bewerbung", "vielen dank für ihre bewerbung", "we received your application",
    "confirmation of application", "ihre bewerbung ist eingegangen"
]

# Strict Rejection keywords (signals REJECTED)
rejection_keywords = [
    "not moving forward", "decided to pursue other candidates", "decided to go with other candidates",
    "will not be moving forward", "regret to inform", "unfortunate", "bedauern ihnen mitteilen",
    "absage", "nicht berücksichtigen", "haben uns für einen anderen bewerber entschieden",
    "leider müssen wir ihnen mitteilen", "unable to offer you", "filled the position",
    "decided not to offer", "not selected for an interview", "not selected",
    "sorry to inform you that we are not in a position to further pursue"
]

emails_found = []

import datetime
date_cutoff = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%d-%b-%Y")

for acc in accounts:
    gmail_user = acc["email"]
    gmail_pass = acc["password"]
    label = acc["label"]
    
    log(f"Connecting to Gmail IMAP for {label} ({gmail_user})...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")
    except Exception as e:
        log(f"Login failed for {gmail_user}: {e}")
        continue
        
    log("Searching last 90 days of emails...")
    status, messages = mail.search(None, f'(SINCE "{date_cutoff}")')
    if status != "OK":
        log("Failed to search inbox.")
        try: mail.logout()
        except: pass
        continue
        
    mail_ids = messages[0].split()
    log(f"Found {len(mail_ids)} emails in the last 90 days. Batch fetching headers...")
    
    if not mail_ids:
        try: mail.logout()
        except: pass
        continue
        
    id_sequence = b",".join(mail_ids)
    res, header_data = mail.fetch(id_sequence, "(BODY[HEADER.FIELDS (SUBJECT FROM DATE)])")
    
    if res != "OK":
        log("Failed to batch fetch headers.")
        try: mail.logout()
        except: pass
        continue
        
    headers_list = []
    for item in header_data:
        if isinstance(item, tuple) and len(item) == 2:
            m_id = re.search(rb'^(\d+)', item[0])
            if m_id:
                msg_id = m_id.group(1)
                headers_list.append((msg_id, item[1]))
                
    log(f"Batch fetched {len(headers_list)} headers. Processing emails...")
    
    for msg_id, raw_header in reversed(headers_list):
        try:
            msg = email.message_from_bytes(raw_header)
            
            # Decode subject
            subject_raw = msg.get("Subject", "")
            subject = ""
            for decoded, charset in decode_header(subject_raw):
                if isinstance(decoded, bytes):
                    subject += decoded.decode(charset or "utf-8", errors="ignore")
                else:
                    subject += str(decoded)
                    
            # Decode sender
            from_raw = msg.get("From", "")
            from_decoded = ""
            for decoded, charset in decode_header(from_raw):
                if isinstance(decoded, bytes):
                    from_decoded += decoded.decode(charset or "utf-8", errors="ignore")
                else:
                    from_decoded += str(decoded)
                    
            subject_lower = subject.lower()
            
            if any(kw in subject_lower or kw in from_decoded.lower() for kw in ["apply", "application", "bewerbung", "status", "thank you", "absage", "update", "interest", "interview", "invitation", "propx", "einladung"]):
                res_body, body_data = mail.fetch(msg_id, "(BODY[TEXT])")
                if res_body == "OK":
                    body_text = body_data[0][1].decode("utf-8", errors="ignore").lower()
                    full_text = f"{subject_lower}\n{body_text}"
                    
                    status_type = None
                    matched_kw = ""
                    
                    # 1. Check for strict rejection first
                    for kw in rejection_keywords:
                        if kw in full_text:
                            status_type = "rejected"
                            matched_kw = kw
                            break
                            
                    # 2. Check for acknowledgment/applied if not rejection
                    if not status_type:
                        for kw in ack_keywords:
                            if kw in full_text:
                                status_type = "applied"
                                matched_kw = kw
                                break
                                
                    if status_type:
                        company_guess = ""
                        m = re.match(r'^([^<]+)', from_decoded)
                        if m:
                            company_guess = m.group(1).strip().replace('"', '').replace("'", "")
                        
                        domain = ""
                        m_domain = re.search(r'@([a-zA-Z0-9.-]+)', from_decoded)
                        if m_domain:
                            domain = m_domain.group(1)
                            
                        emails_found.append({
                            "status_type": status_type,
                            "from": from_decoded,
                            "company_guess": company_guess,
                            "domain": domain,
                            "subject": subject,
                            "body_sample": body_text[:300],
                            "matched_keyword": matched_kw
                        })
        except Exception:
            continue
            
    try: mail.logout()
    except: pass

log(f"Scan complete. Found {len(emails_found)} total job update emails across all accounts.")

if len(emails_found) == 0:
    log("No relevant job updates detected in this scan.")
    sys.exit(0)

# Step 4: Correlate and Update Databases
if csv_path.exists():
    df = pd.read_csv(csv_path)
    df_checked = pd.read_csv(checked_csv_path) if checked_csv_path.exists() else df.copy()
else:
    log("Error: Final combined CSV file not found!")
    sys.exit(1)

rejected_db = json.loads(rejected_json_path.read_text()) if rejected_json_path.exists() else {}
applied_db = json.loads(applied_json_path.read_text()) if applied_json_path.exists() else {}

IGNORED_DOMAINS = {
    "linkedin.com", "xing.com", "gmail.com", "outlook.com", "hotmail.com", 
    "yahoo.com", "google.com", "icloud.com", "mail.com", "gmx.at", "gmx.de", 
    "web.de", "iitm.ac.in", "alumni.iitm.ac.in", "iitb.ac.in", "personio.com", "m.personio.com"
}

IGNORED_COMPANIES = {"nan", "confidential", "unknown", "careers", "jobs", "recruitment", "recruiting"}

log("Correlating email updates with specific job listings...")
newly_updated_count = 0

for item in emails_found:
    status_type = item["status_type"] # 'rejected' or 'applied'
    domain = item["domain"].lower()
    company = item["company_guess"].strip().lower()
    subject = item["subject"].lower()
    body = item["body_sample"].lower()
    
    company_matchable = bool(company and not any(c in company for c in IGNORED_COMPANIES) and len(company) > 2)
    domain_matchable = bool(domain and domain not in IGNORED_DOMAINS)
    
    matched_idx = []
    for idx, row in df.iterrows():
        row_company = str(row["Company"]).lower() if pd.notna(row["Company"]) else ""
        row_title = str(row["Title"]).lower() if pd.notna(row["Title"]) else ""
        row_url = str(row["URL"]).lower() if pd.notna(row["URL"]) else ""
        
        # 1. Company match check
        comp_matched = False
        if company_matchable and (company in row_company or row_company in company or "bcg" in company and "bcg" in row_company):
            comp_matched = True
        elif domain_matchable:
            domain_prefix = domain.split('.')[0]
            if len(domain_prefix) > 2 and domain_prefix in row_url:
                comp_matched = True
                
        if not comp_matched:
            continue
            
        # 2. Title / Specific Job match check
        title_words = [w for w in re.findall(r'\b[a-zA-Z0-9]{4,}\b', row_title) if w not in ["senior", "junior", "lead", "staff", "full", "part", "time", "remote", "gmbh", "wien", "austria", "associate", "consultant"]]
        
        title_matched = False
        if title_words:
            matched_words = [w for w in title_words if w in subject or w in body]
            if len(matched_words) >= 1:
                title_matched = True
                
        m_id = re.search(r'/jobs/view/(\d+)', row_url)
        if m_id and m_id.group(1) in body:
            title_matched = True
            
        # If company match is strong and email is an explicit rejection (like BCG Platinion's generic rejection email), match it
        if comp_matched and status_type == "rejected" and ("bcg" in row_company or "platinion" in row_company):
            title_matched = True

        if comp_matched and status_type == "applied":
            title_matched = True
            
        if title_matched:
            current_status = row.get("Status")
            if status_type == "rejected" and current_status != "rejected":
                matched_idx.append(idx)
            elif status_type == "applied" and current_status not in ["applied", "rejected"]:
                matched_idx.append(idx)
                
    if matched_idx:
        for idx in matched_idx:
            title = df.at[idx, 'Title']
            comp = df.at[idx, 'Company']
            url = df.at[idx, 'URL']
            
            df.at[idx, 'Status'] = status_type
            df_checked.at[idx, 'Status'] = status_type
            
            if status_type == "rejected":
                rejected_db[url] = {
                    "title": title,
                    "company": comp,
                    "url": url,
                    "rejection_email_from": item["from"],
                    "rejection_subject": item["subject"]
                }
                log(f"  ✓ Flagged as REJECTED: '{title}' at {comp}")
            else:
                applied_db[url] = {
                    "title": title,
                    "company": comp,
                    "url": url
                }
                log(f"  ✓ Flagged as APPLIED (Ack email): '{title}' at {comp}")
                
            newly_updated_count += 1

if newly_updated_count > 0:
    df.to_csv(csv_path, index=False)
    df_checked.to_csv(checked_csv_path, index=False)
    rejected_json_path.write_text(json.dumps(rejected_db, indent=2))
    applied_json_path.write_text(json.dumps(applied_db, indent=2))
    log(f"✓ Updated databases: Flagged {newly_updated_count} specific job updates.")
else:
    log("Scan complete. No new job postings matched the emails.")
