from collections import defaultdict

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from movies.models import Comment, CommentVote, Rating
from users.emails import normalize_email
from users.models import Watchlist


def related_counts(user):
    return {
        "watchlist": user.watchlist_set.count(),
        "ratings": user.rating_set.count(),
        "comments": user.comment_set.count(),
        "votes": user.comment_votes.count(),
        "social": user.socialaccount_set.count(),
    }


def pick_primary(members, keep_ids):
    for user in members:
        if user.id in keep_ids:
            return user

    return max(
        members,
        key=lambda u: (u.last_login is not None, u.last_login or u.date_joined, sum(related_counts(u).values()), -u.id),
    )


def merge_into(primary, dup):
    """Move dup's data to primary (primary's rows win on unique conflicts), then deactivate dup and free its email."""
    owned = set(Watchlist.objects.filter(user=primary).values_list("movie_id", flat=True))
    for item in Watchlist.objects.filter(user=dup):
        if item.movie_id in owned:
            item.delete()
        else:
            item.user = primary
            item.save(update_fields=["user"])

    owned = set(Rating.objects.filter(user=primary).values_list("movie_id", flat=True))
    for rating in Rating.objects.filter(user=dup):
        if rating.movie_id in owned:
            rating.delete()
        else:
            rating.user = primary
            rating.save(update_fields=["user"])

    Comment.objects.filter(user=dup).update(user=primary)

    owned = set(CommentVote.objects.filter(user=primary).values_list("comment_id", flat=True))
    for vote in CommentVote.objects.filter(user=dup):
        # also drop votes that would become a self-vote on primary's own comment
        if vote.comment_id in owned or vote.comment.user_id == primary.id:
            vote.delete()
        else:
            vote.user = primary
            vote.save(update_fields=["user"])

    dup.socialaccount_set.update(user=primary)
    dup.emailaddress_set.all().delete()

    # Email is cleared (the original is printed in the log) so the UNIQUE index can be created.
    # The account is deactivated, not deleted.
    dup.is_active = False
    dup.email = ""
    dup.save(update_fields=["is_active", "email"])


class Command(BaseCommand):
    help = "Report accounts sharing the same normalized (trimmed, lowercased) email. Read-only unless --apply is given."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Merge duplicates (BACK UP THE DATABASE FIRST).")
        parser.add_argument(
            "--keep",
            type=int,
            action="append",
            default=[],
            metavar="USER_ID",
            help="Force this user id to be the primary account of its group (repeatable).",
        )

    def handle(self, *args, **options):
        groups = defaultdict(list)
        for user in User.objects.exclude(email="").order_by("id"):
            groups[normalize_email(user.email)].append(user)
        groups = {email: members for email, members in groups.items() if len(members) > 1}

        mode = "APPLY" if options["apply"] else "DRY-RUN, nothing is modified"
        self.stdout.write(f"Users: {User.objects.count()}, duplicate groups: {len(groups)} ({mode})\n")

        plan = []
        for email, members in groups.items():
            keep_ids = [uid for uid in options["keep"] if uid in {m.id for m in members}]
            if len(keep_ids) > 1:
                raise CommandError(f"--keep names several users of the same group {email}: {keep_ids}")
            primary = pick_primary(members, set(keep_ids))
            plan.append((email, primary, [m for m in members if m.id != primary.id]))
            self.stdout.write(f"== {email}")
            for u in members:
                role = "KEEP " if u.id == primary.id else "MERGE"
                self.stdout.write(
                    f"  [{role}] id={u.id} username={u.username!r} raw_email={u.email!r} "
                    f"joined={u.date_joined:%Y-%m-%d %H:%M} last_login={u.last_login or 'never'} "
                    f"staff={u.is_staff} super={u.is_superuser} active={u.is_active} {related_counts(u)}"
                )

        if not options["apply"] or not plan:
            return

        with transaction.atomic():
            for email, primary, dups in plan:
                for dup in dups:
                    merge_into(primary, dup)
                    self.stdout.write(f"merged id={dup.id} into id={primary.id} (original email: {email!r})")
        self.stdout.write("Done. Now run `manage.py migrate`.")
