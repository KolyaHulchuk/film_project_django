from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.contrib.auth.models import User

from .emails import DUPLICATE_EMAIL_MESSAGE, email_taken, normalize_email
from .models import Profile

INVALID_LOGIN_MESSAGE = "Invalid email or password."


class EmailLoginForm(forms.Form):
    """Login by email + password (users/backends.py: EmailBackend); used as LoginView's authentication_form."""

    email = forms.EmailField(max_length=254)
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")
        if email and password:
            self.user_cache = authenticate(self.request, email=normalize_email(email), password=password)
            # Same message for unknown email, wrong password and inactive account (no account enumeration).
            if self.user_cache is None:
                raise forms.ValidationError(INVALID_LOGIN_MESSAGE, code="invalid_login")
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class SitePasswordResetForm(PasswordResetForm):
    """Unlike Django's default, also emails users without a usable password (Google-only
    accounts), so they can set one. The link only ever goes to the account's own email."""

    set_password_email_template = "users/password_set_email.txt"

    def get_users(self, email):
        return User.objects.filter(email__iexact=normalize_email(email), is_active=True)

    def send_mail(self, subject_template_name, email_template_name, context, *args, **kwargs):
        if not context["user"].has_usable_password():
            email_template_name = self.set_password_email_template
        super().send_mail(subject_template_name, email_template_name, context, *args, **kwargs)


class UniqueEmailMixin:
    def clean_email(self):
        email = normalize_email(self.cleaned_data["email"])
        if email_taken(email, exclude_user_id=self.instance.pk):
            raise forms.ValidationError(DUPLICATE_EMAIL_MESSAGE)
        return email


class UserRegisterForm(UniqueEmailMixin, UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User

        fields = ["username", "email", "password1", "password2"]


class UserUpdateForm(UniqueEmailMixin, forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User

        fields = ["username", "email"]


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile

        fields = ["image"]
