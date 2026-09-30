"""Point the SITE_ID=1 Site row at the deployed domain.

django.contrib.sites' own migration seeds id=1 with "example.com"; allauth
falls back to that row whenever it has to build an absolute URL without a
request (e.g. links inside emails). Local development shares this same Neon
database with production, so there is only one row to set - and it has to hold
the real public domain. Google's OAuth redirect_uri is unaffected either way:
allauth derives it from the incoming request, not from Site.
"""

from django.conf import settings
from django.db import migrations

DOMAIN = "film-project-django.onrender.com"
NAME = "Film Project"


def set_default_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        pk=getattr(settings, "SITE_ID", 1),
        defaults={"domain": DOMAIN, "name": NAME},
    )


def revert(apps, schema_editor):
    """Restore the placeholder django.contrib.sites ships with."""
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(pk=getattr(settings, "SITE_ID", 1)).update(
        domain="example.com", name="example.com"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_watchlist"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [migrations.RunPython(set_default_site, revert)]
