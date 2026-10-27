"""Email delivery for the notification outbox. Runs only in the worker, never in a request."""

import smtplib
from email.message import EmailMessage
from html import escape

from app.settings import get_settings


def render(name: str, payload: dict) -> tuple[str, str, str]:
    """Return (subject, text, html) for a notification payload."""
    title = payload.get("title", "Relay notification")
    body = payload.get("body", "")
    link = payload.get("link")
    base = get_settings().base_url
    if link and link.startswith("/"):
        link = base + link
    text = f"Hi {name},\n\n{body}\n" + (f"\n{link}\n" if link else "") + "\n— Relay, lab resource booking\n"
    button = (
        f'<p><a href="{escape(link)}" style="background:#0f766e;color:#fff;padding:10px 16px;border-radius:8px;'
        f'text-decoration:none;display:inline-block">Open in Relay</a></p>'
        if link
        else ""
    )
    html = (
        '<div style="font-family:system-ui,Segoe UI,sans-serif;max-width:560px;margin:auto;color:#1f2937">'
        f'<h2 style="font-size:18px;margin:0 0 12px">{escape(title)}</h2>'
        f"<p>Hi {escape(name)},</p><p>{escape(body)}</p>{button}"
        '<p style="color:#6b7280;font-size:12px;margin-top:24px">Relay · lab resource booking</p></div>'
    )
    return title, text, html


def send(to: str, name: str, payload: dict) -> None:
    s = get_settings()
    subject, text, html = render(name, payload)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s.smtp_from, to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if payload.get("ics"):
        msg.add_attachment(
            payload["ics"].encode(), maintype="text", subtype="calendar", filename="invite.ics", params={"method": "REQUEST"}
        )
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_starttls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
