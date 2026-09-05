from celery import shared_task
from django.contrib.auth.models import User

from .services import get_ai


@shared_task
def get_ai_recommendation_task(user_id, message, media_type):
    user = User.objects.get(id=user_id)
    return get_ai(user, message, media_type)
