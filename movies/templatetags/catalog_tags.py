import re

from django import template

register = template.Library()

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


@register.filter
def year_of(value):
    """Pull the 4-digit year out of '2024-05-01' or '01.05.2024' (or a date); '' when there is none."""
    match = _YEAR_RE.search(str(value or ""))
    return match.group(0) if match else ""


@register.simple_tag(takes_context=True)
def qs_without(context, *keys):
    """Current querystring ('?a=1&b=2', or '?') without the given keys and without `page`."""
    params = context["request"].GET.copy()
    for key in (*keys, "page"):
        params.pop(key, None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


# TMDB's genre ids are stable public constants; list responses only carry ids, so this lets
# cards that don't have the per-item genre names (home page rows) still show them.
TMDB_GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
    18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Science Fiction", 10770: "TV Movie", 53: "Thriller",
    10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics",
}  # fmt: skip


@register.filter
def genre_names(ids, limit=2):
    """[28, 12, 878] -> ['Action', 'Adventure']; unknown ids are skipped."""
    names = [TMDB_GENRES[i] for i in (ids or []) if i in TMDB_GENRES]
    return names[: int(limit)]


@register.filter
def days_until(value):
    """'2026-11-20' -> 'In 26 days' / 'Tomorrow' / 'Today'; '' when the date is missing or already past."""
    from datetime import date, datetime

    try:
        target = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    days = (target - date.today()).days
    if days < 0:
        return ""
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"In {days} days"


@register.filter
def pretty_date(value):
    """'2026-11-20' -> '20 Nov 2026'."""
    from datetime import datetime

    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%-d %b %Y")
    except ValueError:
        return ""


@register.filter
def compact_votes(value):
    """25134 -> '25.1k votes'."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return f"{n / 1000:.1f}k votes" if n >= 1000 else f"{n} votes"
