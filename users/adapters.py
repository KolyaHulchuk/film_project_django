from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.shortcuts import redirect

from .emails import DUPLICATE_EMAIL_MESSAGE, email_taken, normalize_email


class AccountAdapter(DefaultAccountAdapter):
    def clean_email(self, email):
        email = normalize_email(super().clean_email(email))
        if email_taken(email):
            raise ValidationError(DUPLICATE_EMAIL_MESSAGE)
        return email


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """Attach a social login to the existing local account with the same email instead of creating a second one."""
        if sociallogin.is_existing:
            return
        for address in sociallogin.email_addresses:
            email = normalize_email(address.email)
            if not email:
                continue
            matches = list(User.objects.filter(email__iexact=email)[:2])
            if not matches:
                continue
            if address.verified and len(matches) == 1:
                sociallogin.connect(request, matches[0])
                return
            # Unverified email (or ambiguous duplicates): never create a second account with it.
            messages.error(request, DUPLICATE_EMAIL_MESSAGE + " Please log in with your username and password.")
            raise ImmediateHttpResponse(redirect("login"))
