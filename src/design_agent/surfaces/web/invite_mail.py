"""Send a project invitation through the operator's SMTP relay."""

import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from design_agent.config import Settings


def send_invitation(
    settings: Settings, email: str, organization: str, owner: str, link: str
) -> bool:
    if not settings.smtp_host or not settings.smtp_from:
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = "Invitation to join a Studio project"
    message.set_content(
        f"{owner} invited you to join {organization} as a member.\n\n"
        f"Review invitation: {link}\n\nSign in with {email} to accept."
    )
    message.add_alternative(
        f"<p>{escape(owner)} invited you to join <strong>{escape(organization)}</strong> "
        f'as a member.</p><p><a href="{escape(link, quote=True)}">Review invitation</a></p>'
        f"<p>Sign in with {escape(email)} to accept.</p>",
        subtype="html",
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as relay:
            if settings.smtp_starttls:
                relay.starttls(context=ssl.create_default_context())
            if settings.smtp_username or settings.smtp_password:
                if not (
                    settings.smtp_starttls and settings.smtp_username and settings.smtp_password
                ):
                    return False
                relay.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            relay.send_message(message)
    except (OSError, smtplib.SMTPException):
        return False
    return True
