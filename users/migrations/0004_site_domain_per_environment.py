"""Give local dev its own Site domain now that it has its own database.

0003_set_default_site unconditionally wrote the production domain, because at
the time local dev and production shared the same Neon database (there was
only one Site row to set, and it had to be right for the live site). Local
dev now runs against its own Postgres (docker-compose's `db` service), so
this migration - applied fresh there - can safely split back to a per-DEBUG
domain without touching what's already live on Neon: this migration has
already run there via 0003 and Django never re-runs an applied migration.
"""

from django.conf import settings
from django.db import migrations

LOCAL = ("localhost:8001", "Film Project (local)")
PRODUCTION = ("film-project-django.onrender.com", "Film Project")


def set_site_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    domain, name = LOCAL if settings.DEBUG else PRODUCTION
    Site.objects.filter(pk=getattr(settings, "SITE_ID", 1)).update(domain=domain, name=name)


def revert(apps, schema_editor):
    """Restore whatever 0003 set (the production domain), on either DB."""
    Site = apps.get_model("sites", "Site")
    domain, name = PRODUCTION
    Site.objects.filter(pk=getattr(settings, "SITE_ID", 1)).update(domain=domain, name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_set_default_site"),
    ]

    operations = [migrations.RunPython(set_site_domain, revert)]
