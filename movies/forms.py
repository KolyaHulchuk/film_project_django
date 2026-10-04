from django import forms

from .models import COMMENT_MAX_LENGTH, Comment


class CommentForm(forms.ModelForm):
    # forms.CharField strips leading/trailing whitespace by default, so a
    # whitespace-only comment fails `required` instead of being saved.
    text = forms.CharField(
        max_length=COMMENT_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": COMMENT_MAX_LENGTH}),
        error_messages={
            "required": "Comment can't be empty.",
            "max_length": f"Comment is too long: {COMMENT_MAX_LENGTH} characters maximum.",
        },
    )

    class Meta:
        model = Comment
        fields = ["text"]
