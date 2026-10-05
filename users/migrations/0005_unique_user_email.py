"""Case-insensitive UNIQUE index on auth_user.email.

auth.User can't be given a functional UniqueConstraint from our app, so this is raw SQL.
Partial (email <> '') so accounts without an email (e.g. createsuperuser) don't collide.

Run `manage.py find_duplicate_emails --apply` BEFORE migrating: creating the index fails
(by design) while duplicates still exist.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_site_domain_per_environment"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunSQL(
            sql="UPDATE auth_user SET email = LOWER(TRIM(email)) WHERE email <> LOWER(TRIM(email));",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX auth_user_email_lower_uniq ON auth_user (LOWER(email)) WHERE email <> '';",
            reverse_sql="DROP INDEX IF EXISTS auth_user_email_lower_uniq;",
        ),
    ]
