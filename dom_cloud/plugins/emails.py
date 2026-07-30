import os
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import json
import urllib.request
from datetime import datetime, timezone
import time
import sys

# Dynamically find exact absolute paths based on where this file is stored
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DIR = os.path.join(os.path.dirname(PLUGIN_DIR), "..", "dom_sandbox")
PROJECT_ROOT = os.path.dirname(SANDBOX_DIR)

TXT_OUTPUT_PATH = os.path.join(SANDBOX_DIR, "important_emails.txt")

# Unified database — replaces JSON file I/O
sys.path.insert(0, os.path.join(os.path.dirname(PROJECT_ROOT), "shared"))
sys.path.insert(0, PROJECT_ROOT)
from shared import db

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
IMAP_SERVER = os.getenv("EMAIL_IMAP_SERVER")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def clean_text(text):
    return "".join(c for c in text if 32 <= ord(c) <= 126 or c in "\n\t")

def load_filter_memory():
    return db.email_filter_load_all()

def ask_ai_to_classify(sender, subject, snippet):
    if not GROQ_API_KEY:
        return "IMPORTANT"
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    prompt = (
        f"You are a ruthless, zero-tolerance spam execution unit. Your goal is to delete 90% of incoming automated garbage.\n\n"
        f"Email Details:\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Snippet: {snippet}\n\n"
        f"CRITICAL EXECUTION MANDATE:\n"
        f"Classify as 'PROMOTION' if the email is an automated platform alert, newsletter, application update, "
        f"weekly digest, social media recap, crypto market status, marketing pitch, store advertisement, or service recommendation.\n\n"
        f"Classify as 'IMPORTANT' ONLY if it is an official high-level security alert (like an untrusted login alert from Google or GitHub), "
        f"a critical manual one-on-one message from an actual individual human being, or an urgent 2FA verification code.\n\n"
        f"When in doubt, default to PROMOTION. Be completely merciless.\n"
        f"Respond with ONLY one word: PROMOTION or IMPORTANT."
    )
    
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }
    
    try:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {GROQ_API_KEY}")
        req.add_header("Content-Type", "application/json")
        data = json.dumps(payload).encode("utf-8")
        with urllib.request.urlopen(req, data=data, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            decision = res_data["choices"][0]["message"]["content"].strip().upper()
            if decision in ["PROMOTION", "IMPORTANT"]:
                return decision
    except Exception:
        pass
    return "PROMOTION"

def fetch_live_emails():
    if not EMAIL_USER or not EMAIL_PASS or not IMAP_SERVER:
        print("Error: Missing email credentials inside your root .env file.", file=sys.stderr)
        return

    filter_memory = load_filter_memory()

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, 'UNSEEN')
        mail_ids = messages[0].split()
        
        important_briefing = []
        purged_count = 0
        token_saved_count = 0
        
        target_ids = mail_ids[-1000:] if len(mail_ids) > 1000 else mail_ids
        target_ids.reverse() 

        total_to_process = len(target_ids)
        now = datetime.now(timezone.utc)
        
        print(f"\n[System]: Initiating deep cleanup for {total_to_process} items...", flush=True)

        for idx, m_id in enumerate(target_ids, 1):
            status, msg_data = mail.fetch(m_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8", errors="ignore")
                    
                    from_user, encoding = decode_header(msg["From"])[0]
                    if isinstance(from_user, bytes):
                        from_user = from_user.decode(encoding or "utf-8", errors="ignore")
                    
                    date_str = msg.get("Date")
                    email_time = now
                    formatted_date = "Unknown Date"
                    if date_str:
                        try:
                            email_time = parsedate_to_datetime(date_str)
                            if email_time.tzinfo is None:
                                email_time = email_time.replace(tzinfo=timezone.utc)
                            formatted_date = email_time.strftime("%Y-%m-%d %H:%M:%S %Z")
                        except Exception:
                            pass

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")
                    
                    body = clean_text(body.strip()[:300]) 
                    from_lower = from_user.lower()

                    # --- BYPASS INTERFACE PIPE BY WRITING DIRECTLY TO STDERR ---
                    short_subject = subject[:25] + "..." if len(subject) > 25 else subject
                    print(f"[Counter]: {idx}/{total_to_process} processing | Target: {short_subject}", flush=True)

                    # Twitch Time-out Check
                    if "twitch.tv" in from_lower or "twitch" in from_lower:
                        time_delta = now - email_time
                        if (time_delta.total_seconds() / 60.0) > 30.0:
                            purged_count += 1
                            mail.store(m_id, '+FLAGS', '\\Deleted')
                            continue
                    
                    # Extended Hard Blocklist
                    known_spam_platforms = [
                        "datacamp", "mobbin", "avast", "instagram", "tiktok", "linkedin", 
                        "gomining", "hoyoverse", "ecos", "tripo", "tebex", "trade", "codecademy", "nordpass"
                    ]
                    if any(platform in from_lower for platform in known_spam_platforms):
                        purged_count += 1
                        mail.store(m_id, '+FLAGS', '\\Deleted')
                        continue

                    # Local memory cache check
                    if any(known in from_lower for known in filter_memory["scam_senders"]) or \
                       any(known in from_lower for known in filter_memory["promo_senders"]):
                        classification = "DELETED_VIA_CACHE"
                        token_saved_count += 1
                    else:
                        classification = ask_ai_to_classify(from_user, subject, body)
                        if classification == "PROMOTION":
                            db.email_filter_add("promo", from_lower)
                        time.sleep(0.01)

                    if classification in ["PROMOTION", "DELETED_VIA_CACHE"]:
                        purged_count += 1
                        mail.store(m_id, '+FLAGS', '\\Deleted')
                        continue
                    
                    important_briefing.append(
                        f"From: {from_user}\n"
                        f"Date Received: {formatted_date}\n"
                        f"Subject: {subject}\n"
                        f"Snippet: {body}\n"
                        f"========================================\n"
                    )

        mail.expunge()
        mail.logout()

        with open(TXT_OUTPUT_PATH, "w") as txt_file:
            if important_briefing:
                txt_file.write(f"--- MASTER ARDIS' HIGH-PRIORITY INBOX ({len(important_briefing)} MESSAGES) ---\n\n")
                txt_file.write("\n".join(important_briefing))
            else:
                txt_file.write("Your live inbox contains no unread important items right now, Master.")

        db.hdd_set("spam_deleted_today", str(purged_count))
        db.hdd_set("token_free_skips", str(token_saved_count))
        db.hdd_set("unread_important_emails", f"Found {len(important_briefing)} valid messages.")

        print(f"\n--- 1000-RUN COMPLETED ---")
        print(f"[Action]: Permanently deleted {purged_count} garbage items.")
        print(f"[Optimization]: Intercepted {token_saved_count} items via filter memory.", flush=True)

    except Exception as e:
        print(f"\nNetwork Drop: {str(e)}", file=sys.stderr, flush=True)

if __name__ == "__main__":
    fetch_live_emails()