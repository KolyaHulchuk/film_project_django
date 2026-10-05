from django.contrib.auth.models import User

DUPLICATE_EMAIL_MESSAGE = "An account with this email already exists."


def normalize_email(value):
    """Single place that defines email normalization: trim + lowercase, no provider-specific rules."""
    return (value or "").strip().lower()


def email_taken(email, exclude_user_id=None):
    email = normalize_email(email)
    if not email:
        return False
    qs = User.objects.filter(email__iexact=email)
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()
