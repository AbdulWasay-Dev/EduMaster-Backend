"""
Email Integration Service
Connects to teacher's email via IMAP to fetch student assignment submissions.
Students email their assignments to the teacher; the system parses and creates submissions.
"""
import imaplib
import email
import os
import smtplib
import ssl
import uuid
import logging
import json
from datetime import datetime, timezone
from email.message import EmailMessage
from email.header import decode_header
from email.utils import formataddr
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

    def fetch_assignment_emails(
        self,
        assignment_title: str,
        assignment_id: str,
        since_date: Optional[str] = None,
        assignment_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch emails related to an assignment.
        Searches for emails with subject containing the assignment title or the
        generated assignment code, for example [ASG-ABC12345].
        Returns list of parsed email data.
        """
        results = []
        try:
            mail = self._connect()
            mail.select("INBOX")

            search_terms = [term for term in [assignment_code, assignment_title] if term]
            email_ids = []
            seen_ids = set()
            for term in search_terms:
                search_parts = [f'SUBJECT "{term}"']
                if since_date:
                    # since_date format: DD-Mon-YYYY e.g. 01-Jan-2025
                    search_parts.append(f'SINCE {since_date}')
                search_query = "(" + " ".join(search_parts) + ")"
                _, data = mail.search(None, search_query)
                for eid in data[0].split() if data and data[0] else []:
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        email_ids.append(eid)

            logger.info(f"Found {len(email_ids)} emails for assignment: {assignment_title} ({assignment_code or 'no code'})")

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


class EmailSender:
    """SMTP email sender for teacher report delivery."""

    def __init__(
        self,
        email_address: str,
        app_password: str,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        smtp_use_tls: bool = True,
        smtp_use_ssl: bool = False,
        from_name: Optional[str] = None,
    ):
        self.email_address = email_address
        self.app_password = app_password
        self.smtp_host = smtp_host or "smtp.gmail.com"
        self.smtp_port = int(smtp_port or 587)
        self.smtp_use_tls = smtp_use_tls
        self.smtp_use_ssl = smtp_use_ssl or self.smtp_port == 465
        self.from_name = from_name or "EduMaster"

    def _connect(self):
        context = ssl.create_default_context()
        if self.smtp_use_ssl:
            server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=30)
        else:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
            if self.smtp_use_tls:
                server.starttls(context=context)
        server.login(self.email_address, self.app_password)
        return server

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send an email with optional byte attachments."""
        try:
            msg = EmailMessage()
            msg["From"] = formataddr((self.from_name, self.email_address))
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(body)

            for attachment in attachments or []:
                content = attachment.get("content") or b""
                if isinstance(content, str):
                    content = content.encode("utf-8")
                filename = attachment.get("filename") or "report.pdf"
                media_type = attachment.get("media_type") or "application/octet-stream"
                maintype, _, subtype = media_type.partition("/")
                msg.add_attachment(
                    content,
                    maintype=maintype or "application",
                    subtype=subtype or "octet-stream",
                    filename=filename,
                )

            server = self._connect()
            try:
                server.send_message(msg)
            finally:
                server.quit()
            return {"success": True, "message": "Email sent successfully"}
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return {"success": False, "message": "SMTP authentication failed. Check the email address and app password."}
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return {"success": False, "message": str(e)}

    def test_connection(self) -> Dict[str, Any]:
        """Test SMTP login without sending an email."""
        try:
            server = self._connect()
            server.quit()
            return {"success": True, "message": "SMTP connection successful"}
        except smtplib.SMTPAuthenticationError as e:
            return {"success": False, "message": f"SMTP authentication failed: {e}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
