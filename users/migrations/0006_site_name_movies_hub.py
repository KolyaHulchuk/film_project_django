"""Brand the Site row as "Movies.hub" on every environment.

django.contrib.sites' name ends up in the subject and body of the emails we send
(password reset, email confirmation). 0003/0004 left "Film Project" (prod) and
"Film Project (local)" (dev); both are replaced. The domain is not touched.
"""

from django.conf import settings
from django.db import migrations

NAME = "Movies.hub"


def set_name(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(pk=getattr(settings, "SITE_ID", 1)).update(name=NAME)


def revert(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    name = "Film Project (local)" if settings.DEBUG else "Film Project"
    Site.objects.filter(pk=getattr(settings, "SITE_ID", 1)).update(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_unique_user_email"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [migrations.RunPython(set_name, revert)]
