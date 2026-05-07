import html
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_error_email_sync(
    error: Exception,
    recipient_email: str | None = None,
    *,
    request_url: str | None = None,
    user_message: str | None = None,
    context: str = "Request processing",
) -> bool:
    receiver_email = recipient_email or settings.ERROR_ALERT_EMAIL

    if not receiver_email:
        logger.warning("SMTP recipient email is not configured.")
        return False

    smtp_ready = all(
        [
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            settings.SMTP_USER,
            settings.SMTP_PASSWORD,
        ]
    )
    if not smtp_ready:
        logger.warning("SMTP settings are incomplete; skipping error email.")
        return False

    subject = "[A-ka] 요청 처리 중 오류가 발생했습니다"
    error_summary = f"{type(error).__name__}: {error}"
    text_body = _build_text_body(
        error_summary=error_summary,
        request_url=request_url,
        user_message=user_message,
        context=context,
    )
    html_body = _build_html_body(
        error_summary=error_summary,
        request_url=request_url,
        user_message=user_message,
        context=context,
    )

    message = EmailMessage()
    message["From"] = settings.SMTP_USER
    message["To"] = receiver_email
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(
            settings.SMTP_HOST,
            int(settings.SMTP_PORT),
            timeout=10,
        ) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
    except Exception:
        logger.exception("Failed to send SMTP error email to %s", receiver_email)
        return False

    logger.info("SMTP error email sent to %s", receiver_email)
    return True


def _build_text_body(
    *,
    error_summary: str,
    request_url: str | None,
    user_message: str | None,
    context: str,
) -> str:
    lines = [
        "A-ka 요청 처리 중 문제가 발생했습니다.",
        "",
        "잠시 후 다시 시도해 주세요. 문제가 반복되면 이 메일을 전달해 주세요.",
        "",
        f"처리 단계: {context}",
        f"오류: {error_summary}",
    ]

    if user_message:
        lines.append(f"요청 메시지: {user_message}")
    if request_url:
        lines.append(f"요청 URL: {request_url}")

    return "\n".join(lines)


def _build_html_body(
    *,
    error_summary: str,
    request_url: str | None,
    user_message: str | None,
    context: str,
) -> str:
    rows = [
        ("처리 단계", context),
        ("오류", error_summary),
    ]
    if user_message:
        rows.append(("요청 메시지", user_message))
    if request_url:
        rows.append(("요청 URL", request_url))

    detail_rows = "\n".join(
        "<tr>"
        "<th style='text-align:left;padding:6px 12px 6px 0;'>"
        f"{html.escape(label)}</th>"
        f"<td style='padding:6px 0;'>{html.escape(value)}</td>"
        "</tr>"
        for label, value in rows
    )

    return f"""
    <html>
      <body>
        <p>A-ka 요청 처리 중 문제가 발생했습니다.</p>
        <p>잠시 후 다시 시도해 주세요. 문제가 반복되면 이 메일을 전달해 주세요.</p>
        <table>
          {detail_rows}
        </table>
      </body>
    </html>
    """
