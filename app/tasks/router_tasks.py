from app.core.celery_app import celery_app
from app.services.chat_command import ChatCommandService


@celery_app.task(bind=True, name="router.analyze_intent")
def process_ai_routing_task(self, user_id: str, user_message: str):
    service = ChatCommandService()
    return service.process(user_id=user_id, user_message=user_message)
