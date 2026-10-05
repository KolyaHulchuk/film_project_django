from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .emails import DUPLICATE_EMAIL_MESSAGE, email_taken, normalize_email
from .models import Profile


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
