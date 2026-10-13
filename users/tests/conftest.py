import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    # Sessions and allauth's email rate limits live in the default cache (Redis in
    # dev/prod); keep tests independent of a running Redis and of each other.
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
