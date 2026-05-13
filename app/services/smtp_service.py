import html
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("aka.smtp")


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

def send_search_result_email(recipient_email: str, query: str, answer: str, chunks: list) -> bool:
    """검색된 RAG 답변과 참고 링크를 사용자에게 이메일로 발송"""
    if not recipient_email:
        return False
    
    #참고한 영상이 5개 미만일 때 중복 표시 방지 위함
    seen_urls = set()
    unique_sources = []

    for chunk in chunks:
        url = chunk.get("original_url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_sources.append(chunk)

    subject = f"[A-ka] 요청하신 '{query[:15]}...' 검색 결과입니다"
    
    #참고한 영상 리스트
    source_links = ""
    for i, chunk in enumerate(unique_sources, 1):
        title = chunk.get("title", "영상 제목 없음")
        url = chunk.get("original_url", "#")
        source_links += f"<li>{i}. <a href='{url}'>{title}</a></li>"

    html_body = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #4A90E2;">안녕하세요, A-ka입니다.</h2>
        <p>질문하신 내용에 대해 저장된 영상들을 분석한 결과입니다:</p>
        
        <div style="background-color: #f9f9f9; padding: 20px; border-radius: 8px; border-left: 5px solid #4A90E2;">
            <strong>질문:</strong> {query}<br><br>
            <strong>답변:</strong> {answer.replace('\n', '<br>')}
        </div>

        <h3 style="margin-top: 30px;">참고한 영상 리스트</h3>
        <ul>{source_links if source_links else "<li>참고한 특정 영상이 없습니다.</li>"}</ul>
        
        <p style="margin-top: 40px; font-size: 0.8em; color: #888;">
            본 메일은 사용자의 요청에 의해 발송되었습니다.
        </p>
      </body>
    </html>
    """

    message = EmailMessage()
    message["From"] = settings.SMTP_USER
    message["To"] = recipient_email
    message["Subject"] = subject
    message.set_content(f"질문: {query}\n\n답변: {answer}\n\n참고 영상들은 HTML 메일을 지원하는 환경에서 확인하실 수 있습니다.")
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.SMTP_HOST, int(settings.SMTP_PORT), timeout=10) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
        logger.info(f"검색 결과 메일 발송 완료: {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"메일 발송 실패: {e}")
        return False
