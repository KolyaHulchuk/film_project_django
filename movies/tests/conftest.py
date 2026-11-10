import pytest
from django.core.cache import cache

from movies import redis_services


class FakeRedis:
    """In-memory stand-in for the raw redis-py client `redis_services.r`.

    Supports only the calls redis_services makes (get/set/mget/pipeline).
    TTLs are recorded in `ttls` (not enforced); every test gets a fresh, empty
    instance.
    """

    def __init__(self):
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex
        return True

    def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.queued = []

    def set(self, key, value, ex=None):
        self.queued.append((key, value, ex))
        return self

    def execute(self):
        results = [self.client.set(key, value, ex=ex) for key, value, ex in self.queued]
        self.queued = []
        return results


@pytest.fixture(autouse=True)
def isolated_cache(settings, monkeypatch):
    # The movies code caches through two paths to the same Redis: the raw client
    # `redis_services.r` (lists, genres, search) and Django's cache (details,
    # seasons, collections, keywords, throttles). Replace both so tests never
    # read or overwrite the dev site's cache, and never see each other's data.
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    fake = FakeRedis()
    monkeypatch.setattr(redis_services, "r", fake)
    return fake
