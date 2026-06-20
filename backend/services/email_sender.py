import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Template
from config import get_settings

settings = get_settings()


def render_template(template_str: str, context: dict) -> str:
    return Template(template_str).render(**context)


async def send_email(to_email: str, subject: str, body: str, is_html: bool = False) -> dict:
    """Send a single email via SMTP. Returns {"success": bool, "error": str|None}."""
    if not settings.smtp_user or not settings.smtp_password:
        return {"success": False, "error": "SMTP credentials not configured"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    msg["To"] = to_email

    if is_html:
        msg.attach(MIMEText(body, "html"))
    else:
        msg.attach(MIMEText(body, "plain"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        return {"success": True, "error": None}
    except Exception as e:
        return {"success": False, "error": str(e)}
