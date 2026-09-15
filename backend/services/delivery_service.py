import logging
import re
import socket
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional, Tuple
import urllib.request
import urllib.parse
import urllib.error
import json
import base64

from config import settings

logger = logging.getLogger("delivery_service")


def validate_phone_number(phone: Optional[str]) -> Tuple[bool, str]:
    """
    Validates phone number format for SMS dispatch.
    Accepts international standard (E.164), 10-15 digit numbers, or formatted phone numbers.
    """
    if not phone or not phone.strip():
        return False, "Phone number cannot be empty."
    
    clean = re.sub(r"[\s\-\(\)\.]", "", phone.strip())
    # Match optionally leading + followed by 7 to 15 digits
    if re.match(r"^\+?[1-9]\d{6,14}$", clean):
        return True, clean
    return False, "Invalid phone number format. Please provide a valid 10-15 digit number (e.g. +1234567890 or 9876543210)."


def is_email_configured() -> bool:
    """Returns True only when valid SMTP credentials exist in settings."""
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def is_sms_configured() -> bool:
    """Returns True only when valid Twilio credentials exist in settings."""
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER)


def get_provider_status() -> Dict[str, Any]:
    """
    Returns public provider availability status without exposing credentials.
    """
    return {
        "email": {
            "configured": is_email_configured(),
            "provider": "SMTP",
            "host": settings.SMTP_HOST if settings.SMTP_HOST else None,
            "sender": settings.EMAILS_FROM_EMAIL or "notifications@wakewise.ai",
        },
        "sms": {
            "configured": is_sms_configured(),
            "provider": "Twilio",
            "sender_number": settings.TWILIO_PHONE_NUMBER if settings.TWILIO_PHONE_NUMBER else None,
        }
    }


def send_email_notification(
    to_email: str,
    subject: str,
    body_text: str,
    html_content: Optional[str] = None
) -> Dict[str, Any]:
    """
    Dispatches a real email via SMTP if configured, or returns explicit unconfigured/failed status.
    Isolated with strict timeout to prevent blocking application workers when network is unreachable.
    """
    if not to_email or "@" not in to_email:
        return {"status": "failed", "detail": f"Invalid recipient email address: '{to_email}'"}

    if not is_email_configured():
        logger.info(f"Email delivery skipped (SMTP unconfigured) for recipient '{to_email}': '{subject}'")
        return {
            "status": "unconfigured",
            "detail": "SMTP email provider is not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env"
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        msg["To"] = to_email

        # Attach text part
        msg.attach(MIMEText(body_text, "plain"))

        # Attach HTML part if available
        if html_content:
            msg.attach(MIMEText(html_content, "html"))
        else:
            default_html = f"""
            <div style="font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; border-radius: 8px;">
                <h2 style="color: #818cf8; margin-top: 0;">WakeWise AI Notification</h2>
                <h3 style="color: #ffffff;">{subject}</h3>
                <p style="color: #cbd5e1; font-size: 15px; line-height: 1.6;">{body_text}</p>
                <hr style="border: 0; border-top: 1px solid #334155; margin: 20px 0;">
                <small style="color: #64748b;">Intelligent Cognitive Alarm Platform &copy; WakeWise AI</small>
            </div>
            """
            msg.attach(MIMEText(default_html, "html"))

        # 2.5 second timeout to prevent thread starvation on unreachable networks (e.g. Railway egress policies)
        smtp_timeout = 2.5
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=smtp_timeout)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=smtp_timeout)
            if settings.SMTP_TLS:
                server.starttls()

        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.EMAILS_FROM_EMAIL, [to_email], msg.as_string())
        server.quit()

        logger.info(f"Email successfully dispatched to {to_email}: '{subject}'")
        return {"status": "delivered", "detail": f"Dispatched via SMTP to {to_email}"}

    except (socket.error, OSError) as net_err:
        logger.warning(f"SMTP network unreachable / socket error for {to_email}: {net_err}")
        return {"status": "failed", "detail": f"SMTP Network Error: {str(net_err)}"}
    except smtplib.SMTPException as smtp_err:
        logger.warning(f"SMTP protocol error for {to_email}: {smtp_err}")
        return {"status": "failed", "detail": f"SMTP Protocol Error: {str(smtp_err)}"}
    except Exception as e:
        logger.warning(f"SMTP delivery failed to {to_email}: {e}")
        return {"status": "failed", "detail": f"SMTP Error: {str(e)}"}


def send_sms_notification(
    to_phone: Optional[str],
    message: str
) -> Dict[str, Any]:
    """
    Dispatches a real SMS via Twilio API if configured, or returns explicit unconfigured/no_phone status.
    Isolated with strict timeout to prevent blocking application workers.
    """
    if not to_phone or not to_phone.strip():
        logger.info("SMS delivery skipped: User does not have a configured phone number.")
        return {"status": "no_phone", "detail": "User has no phone number configured on profile."}

    is_valid, clean_phone = validate_phone_number(to_phone)
    if not is_valid:
        return {"status": "failed", "detail": clean_phone}

    if not is_sms_configured():
        logger.info(f"SMS delivery skipped (Twilio unconfigured) for recipient '{clean_phone}': '{message[:40]}...'")
        return {
            "status": "unconfigured",
            "detail": "Twilio SMS provider is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in .env"
        }

    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        
        # Prepare payload
        payload = urllib.parse.urlencode({
            "From": settings.TWILIO_PHONE_NUMBER,
            "To": clean_phone,
            "Body": message
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        auth_string = f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}"
        base64_auth = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
        req.add_header("Authorization", f"Basic {base64_auth}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=3.0) as response:
            resp_body = response.read().decode("utf-8")
            data = json.loads(resp_body)
            sid = data.get("sid", "unknown")
            logger.info(f"SMS successfully dispatched via Twilio to {clean_phone} (SID: {sid})")
            return {"status": "delivered", "detail": f"Dispatched via Twilio (SID: {sid})"}

    except (socket.error, OSError, urllib.error.URLError) as net_err:
        logger.warning(f"Twilio SMS network error for {clean_phone}: {net_err}")
        return {"status": "failed", "detail": f"Twilio Network Error: {str(net_err)}"}
    except Exception as e:
        logger.warning(f"Twilio SMS delivery failed to {clean_phone}: {e}")
        return {"status": "failed", "detail": f"Twilio SMS Error: {str(e)}"}

