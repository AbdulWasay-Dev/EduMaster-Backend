"""
Email Integration Service
Connects to teacher's email via IMAP to fetch student assignment submissions.
Students email their assignments to the teacher; the system parses and creates submissions.
"""
import imaplib
import email
import os
import uuid
import logging
import json
from datetime import datetime, timezone
from email.header import decode_header
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join("uploads", "email_submissions")


def _decode_str(value) -> str:
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def _extract_text_from_email(msg) -> str:
    """Extract plain text body from email message."""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    text += payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        if msg.get_content_type() == "text/plain":
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return text.strip()


def _save_attachment(part, assignment_id: str) -> Optional[str]:
    """Save an email attachment and return its path."""
    try:
        filename = part.get_filename()
        if not filename:
            return None
        filename = _decode_str(filename)
        # Sanitize filename
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
        if not safe_name:
            safe_name = f"attachment_{uuid.uuid4().hex[:8]}"

        save_dir = os.path.join(UPLOAD_DIR, assignment_id)
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, safe_name)
        with open(save_path, "wb") as f:
            f.write(part.get_payload(decode=True))
        return f"/static/uploads/email_submissions/{assignment_id}/{safe_name}"
    except Exception as e:
        logger.error(f"Error saving attachment: {e}")
        return None


class EmailFetcher:
    """IMAP email fetcher for assignment submissions."""

    def __init__(self, email_address: str, app_password: str, imap_host: str = "imap.gmail.com", imap_port: int = 993):
        self.email_address = email_address
        self.app_password = app_password
        self.imap_host = imap_host
        self.imap_port = imap_port

    def _connect(self) -> imaplib.IMAP4_SSL:
        mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        mail.login(self.email_address, self.app_password)
        return mail

    def fetch_assignment_emails(self, assignment_title: str, assignment_id: str, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch emails related to an assignment.
        Searches for emails with subject containing the assignment title.
        Returns list of parsed email data.
        """
        results = []
        try:
            mail = self._connect()
            mail.select("INBOX")

            # Build search criteria
            search_parts = [f'SUBJECT "{assignment_title}"']
            if since_date:
                # since_date format: DD-Mon-YYYY e.g. 01-Jan-2025
                search_parts.append(f'SINCE {since_date}')

            search_query = "(" + " ".join(search_parts) + ")"
            _, data = mail.search(None, search_query)

            email_ids = data[0].split() if data[0] else []
            logger.info(f"Found {len(email_ids)} emails for assignment: {assignment_title}")

            for eid in email_ids:
                try:
                    _, msg_data = mail.fetch(eid, "(RFC822)")
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    from_addr = _decode_str(msg.get("From", ""))
                    subject = _decode_str(msg.get("Subject", ""))
                    date_str = msg.get("Date", "")

                    # Parse date
                    try:
                        sent_at = email.utils.parsedate_to_datetime(date_str)
                    except Exception:
                        sent_at = datetime.now(timezone.utc)

                    body = _extract_text_from_email(msg)
                    attachments = []

                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_disposition() == "attachment":
                                path = _save_attachment(part, assignment_id)
                                if path:
                                    attachments.append(path)

                    # Extract sender email
                    sender_email = ""
                    if "<" in from_addr and ">" in from_addr:
                        sender_email = from_addr.split("<")[-1].rstrip(">").strip()
                    else:
                        sender_email = from_addr.strip()

                    results.append({
                        "from_name": from_addr,
                        "from_email": sender_email,
                        "subject": subject,
                        "body": body,
                        "attachments": attachments,
                        "sent_at": sent_at.isoformat(),
                    })
                except Exception as e:
                    logger.error(f"Error parsing email {eid}: {e}")
                    continue

            mail.logout()
        except Exception as e:
            logger.error(f"Email fetch failed: {e}")
            raise

        return results

    def test_connection(self) -> Dict[str, Any]:
        """Test IMAP connection and return status."""
        try:
            mail = self._connect()
            mail.select("INBOX")
            mail.logout()
            return {"success": True, "message": "Connection successful"}
        except imaplib.IMAP4.error as e:
            return {"success": False, "message": f"Authentication failed: {e}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
