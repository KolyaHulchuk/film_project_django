import pytest
from movies.views import get_country

@pytest.mark.parametrize("data, media_type, extends", [
    ({"production_countries": [{"iso_3166_1": "US"}, {"iso_3166_1": "UA"}]}, "movie", ["US", "UA"]),
    ({"origin_country": ["US", "UA"]}, "tv", ["US", "UA"])
    ])
def test_get_country(data, media_type, extends):
    assert get_country(data, media_type) == extends

