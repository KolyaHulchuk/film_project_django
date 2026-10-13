from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.account.utils import user_email
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import redirect

from .emails import DUPLICATE_EMAIL_MESSAGE, is_email_verified, normalize_email, send_verification

SOCIAL_NO_EMAIL_MESSAGE = "Google did not share an email address, so we can't sign you in. Please allow email access or register with a password."
SOCIAL_UNVERIFIED_MESSAGE = (
    "Your Google email address is not verified. Verify it with Google, or log in with your email and password."
)
SOCIAL_EXISTING_UNVERIFIED_MESSAGE = (
    "An account with this email already exists, but its email hasn't been verified yet, so we can't link "
    "Google to it automatically. Log in with your email and password and connect Google on your profile page, "
    "or confirm your email using the link we've sent you and then sign in with Google again."
)


class AccountAdapter(DefaultAccountAdapter):
    def clean_email(self, email):
        # Normalize only. allauth also calls this to *validate* emails coming from
        # social providers and silently drops the email on ValidationError, so a
        # uniqueness check here made Google logins with an existing email create
        # an email-less "user" account. Uniqueness is enforced by allauth's forms
        # (ACCOUNT_UNIQUE_EMAIL), our own forms and the DB index.
        return normalize_email(super().clean_email(email))


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """Attach a social login to the existing local account with the same email instead of creating a second one."""
        if sociallogin.is_existing or sociallogin.state.get("process") == "connect":
            return

        email, verified = self._provider_email(sociallogin)
        if not email:
            self._reject(request, SOCIAL_NO_EMAIL_MESSAGE)
        if not verified:
            self._reject(request, SOCIAL_UNVERIFIED_MESSAGE)

        # Use the normalized email for both linking and a possible new account.
        user_email(sociallogin.user, email)
        sociallogin.email_addresses = [EmailAddress(email=email, verified=True, primary=True)]

        matches = list(User.objects.filter(email__iexact=email)[:2])
        if not matches:
            return  # new user: allauth signs them up (no password, SocialAccount.uid = Google "sub")
        if len(matches) > 1:
            self._reject(request, DUPLICATE_EMAIL_MESSAGE + " Please log in with your email and password.")

        user = matches[0]
        if not is_email_verified(user):
            # Pre-hijacking guard: whoever registered this local account may not own
            # the address, so a matching email alone is not enough to link. The real
            # owner can confirm the email (link sent now) or log in and connect Google
            # from the profile page.
            send_verification(request, user)
            self._reject(request, SOCIAL_EXISTING_UNVERIFIED_MESSAGE)

        # Only adds a SocialAccount: the password, staff/superuser flags and sessions are untouched.
        sociallogin.connect(request, user)

    @staticmethod
    def _provider_email(sociallogin):
        # Read the raw provider data: allauth's own extraction drops emails that
        # fail validation (e.g. surrounding whitespace) instead of normalizing them.
        data = sociallogin.account.extra_data or {}
        email = normalize_email(data.get("email"))
        verified = bool(data.get("email_verified") or data.get("verified_email"))
        if not email and sociallogin.email_addresses:
            address = sociallogin.email_addresses[0]
            email, verified = normalize_email(address.email), address.verified
        try:
            validate_email(email)
        except ValidationError:
            return "", False
        return email, verified

    @staticmethod
    def _reject(request, message):
        messages.error(request, message)
        raise ImmediateHttpResponse(redirect("login"))
