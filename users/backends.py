from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

from .emails import normalize_email


class EmailBackend(ModelBackend):
    """Site login by email + password. Admin and username logins still go through ModelBackend."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        email = normalize_email(email)
        if not email or password is None:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Run the hasher anyway so response time doesn't reveal whether the email exists.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
