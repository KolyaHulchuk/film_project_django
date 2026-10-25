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
