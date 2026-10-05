from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .emails import normalize_email
from .models import Profile


@receiver(post_save, sender=User)
def create_profile(sender, created, instance, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_profile(sender, instance, **kwargs):
    instance.profile.save()


@receiver(pre_save, sender=User)
def normalize_user_email(sender, instance, **kwargs):
    # Covers every save path (admin, shell, allauth, forms)
    instance.email = normalize_email(instance.email)
