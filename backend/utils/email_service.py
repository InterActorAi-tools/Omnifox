"""Emails sent through Resend. Off unless RESEND_API_KEY and EMAIL_FROM are both set;
callers then fall back to links the admin copies by hand."""
import html
import logging

import resend
from config import settings

logger = logging.getLogger(__name__)


def email_enabled() -> bool:
    return bool(settings.resend_api_key and settings.email_from)


def send_email(to: str, subject: str, body_html: str) -> bool:
    """Send one email. Returns False (never raises) if email is off or sending fails."""
    if not email_enabled():
        return False
    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send({"from": settings.email_from, "to": [to], "subject": subject, "html": body_html})
        return True
    except Exception as e:
        logger.error(f"Email to {to} failed: {e}")
        return False


def _hi(name: str) -> str:
    return f"Hi {name}," if name else "Hi,"


def _page(greeting: str, text: str, link: str, button: str, note: str) -> str:
    return (f"<p>{html.escape(greeting)}</p><p>{text}</p>"
            f'<p><a href="{html.escape(link)}">{button}</a></p><p>{note}</p>')


def send_password_reset_email(email: str, token: str) -> bool:
    link = f"{settings.frontend_url}/reset-password?token={token}"
    return send_email(email, "Reset your OmniFox password", _page(
        "Hi,", "You asked to reset your OmniFox password.", link, "Set a new password",
        "This link expires in 1 hour. If you didn't ask for it, you can ignore this email."))


def send_invite_email(email: str, name: str, link: str) -> bool:
    return send_email(email, "Your OmniFox account", _page(
        _hi(name), "An OmniFox account has been created for you.", link,
        "Set your password", "This link expires in 24 hours."))


def send_welcome_email(email: str, name: str) -> bool:
    return send_email(email, "Welcome to OmniFox", _page(
        _hi(name), "Your request to join OmniFox has been accepted.",
        f"{settings.frontend_url}/login", "Sign in", "Use the email and password you chose when you asked to join."))
