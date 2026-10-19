import resend
from config import settings
import logging

logger = logging.getLogger(__name__)

resend.api_key = settings.resend_api_key

async def send_password_reset_email(email: str, token: str):
    """
    Sends a password reset email using Resend.
    """
    if not resend.api_key:
        logger.error("RESEND_API_KEY is not set. Cannot send email.")
        # In production, you might want to raise an error
        # but for dev, we'll just log it so it doesn't crash
        return False

    # M11: reset URL is built from settings.frontend_url so prod and
    # staging both link to the right domain. Previously hardcoded to
    # staging - any prod user resetting their password got pointed at
    # the wrong environment.
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"

    html_content = f"""
    <p>Hi,</p>
    <p>You requested a password reset for your OmniFox account.</p>
    <p>Please click the link below to set a new password:</p>
    <p><a href="{reset_url}">Reset Your Password</a></p>
    <p>If you did not request this, you can safely ignore this email.</p>
    <p>This link will expire in 1 hour.</p>
    """

    try:
        params = {
            "from": "OmniFox <onboarding@resend.dev>", # Must be a verified domain in Resend
            "to": [email],
            "subject": "Reset Your OmniFox Password",
            "html": html_content,
        }
        
        email_response = resend.Emails.send(params)
        logger.info(f"Password reset email sent, ID: {email_response['id']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")
        return False