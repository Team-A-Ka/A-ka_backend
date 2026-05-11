from app.core.celery_app import celery_app
from app.services.chat_command import ChatCommandService
from app.services.user_notification_service import send_user_processing_error_email


@celery_app.task(bind=True, name="router.analyze_intent")
def process_ai_routing_task(self, user_id: int, user_message: str):
    service = ChatCommandService()
    try:
        return service.process(user_id=user_id, user_message=user_message)
    except Exception as exc:
        send_user_processing_error_email(
            user_id=user_id,
            error=exc,
            user_message=user_message,
            context="Kakao message AI routing",
        )
        raise
