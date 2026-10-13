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


# Email verification reuses allauth's EmailAddress table and confirmation links
# (/accounts/confirm-email/<key>/). User.email stays the source of truth; the
# EmailAddress row for it only tracks whether it has been verified.


def email_address_for(user):
    """Get or create the EmailAddress row matching user.email; older users may have none."""
    from allauth.account.models import EmailAddress

    email = normalize_email(user.email)
    if not email:
        return None
    address = EmailAddress.objects.filter(user=user, email__iexact=email).first()
    if address is None:
        has_primary = EmailAddress.objects.filter(user=user, primary=True).exists()
        address = EmailAddress.objects.create(user=user, email=email, verified=False, primary=not has_primary)
    return address


def is_email_verified(user):
    from allauth.account.models import EmailAddress

    email = normalize_email(user.email)
    return bool(email) and EmailAddress.objects.filter(user=user, email__iexact=email, verified=True).exists()


def send_verification(request, user):
    """Send (rate-limited by allauth) a confirmation link for user.email. Returns False if nothing was sent."""
    from allauth.account.internal.flows.email_verification import send_verification_email_to_address

    address = email_address_for(user)
    if address is None or address.verified:
        return False
    return send_verification_email_to_address(request, address)


def mark_email_verified(user):
    address = email_address_for(user)
    if address is not None and not address.verified:
        address.verified = True
        address.save(update_fields=["verified"])


def replace_email_address(request, user):
    """After user.email changed: drop the old rows (and their verified state) and verify the new address."""
    from allauth.account.models import EmailAddress

    EmailAddress.objects.filter(user=user).exclude(email__iexact=normalize_email(user.email)).delete()
    return send_verification(request, user)
