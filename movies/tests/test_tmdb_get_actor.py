import pytest
from unittest.mock import MagicMock
from movies.tmdb_service import TMDBClient


@pytest.fixture
def value():
    return {
  "page": 1,
  "results": [
    {
      "adult": False,
      "gender": 1,
      "id": 224513,
      "known_for": [
        {
          "adult": False,
          "backdrop_path": "/ilRyazdMJwN05exqhwK4tMKBYZs.jpg",
          "genre_ids": [
            878,
            18
          ],
          "id": 335984,
          "media_type": "movie",
          "original_language": "en",
          "original_title": "Blade Runner 2049",
          "overview": "Thirty years after the events of the first film, a new blade runner, LAPD Officer K, unearths a long-buried secret that has the potential to plunge what's left of society into chaos. K's discovery leads him on a quest to find Rick Deckard, a former LAPD blade runner who has been missing for 30 years.",
          "poster_path": "/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",
          "release_date": "2017-10-04",
          "title": "Blade Runner 2049",
          "video": False,
          "vote_average": 7.5,
          "vote_count": 11771
        },
        {
          "adult": False,
          "backdrop_path": "/4HWAQu28e2yaWrtupFPGFkdNU7V.jpg",
          "genre_ids": [
            35,
            80,
            9648
          ],
          "id": 546554,
          "media_type": "movie",
          "original_language": "en",
          "original_title": "Knives Out",
          "overview": "When renowned crime novelist Harlan Thrombey is found dead at his estate just after his 85th birthday, the inquisitive and debonair Detective Benoit Blanc is mysteriously enlisted to investigate. From Harlan's dysfunctional family to his devoted staff, Blanc sifts through a web of red herrings and self-serving lies to uncover the truth behind Harlan's untimely death.",
          "poster_path": "/pThyQovXQrw2m0s9x82twj48Jq4.jpg",
          "release_date": "2019-11-27",
          "title": "Knives Out",
          "video": False,
          "vote_average": 7.9,
          "vote_count": 10631
        },
        {
          "adult": False,
          "backdrop_path": "/3Mnbw4gOYz5BNZB9PhZ2cyBSQum.jpg",
          "genre_ids": [
            35,
            80,
            18
          ],
          "id": 308266,
          "media_type": "movie",
          "original_language": "en",
          "original_title": "War Dogs",
          "overview": "Based on the true story of two young men, David Packouz and Efraim Diveroli, who won a $300 million contract from the Pentagon to arm America's allies in Afghanistan.",
          "poster_path": "/uH9qGH5XS1iZXCSb3tgu40dxQoh.jpg",
          "release_date": "2016-08-17",
          "title": "War Dogs",
          "video": False,
          "vote_average": 6.9,
          "vote_count": 4324
        }
      ],
      "known_for_department": "Acting",
      "name": "Ana de Armas",
      "popularity": 343.33,
      "profile_path": "/3vxvsmYLTf4jnr163SUlBIw51ee.jpg"
    } 
  ]
}


@pytest.fixture
def tmdb_client():
    return TMDBClient(api_key="test_key", languages=["en"])


def test_get_person(mocker, tmdb_client, value):

    mock_request = mocker.patch.object(tmdb_client, "_request", return_value=value["results"][0])

    result = tmdb_client.get_person(224513)

    assert result["id"] == 224513
    assert result["name"] == "Ana de Armas"
    assert result["known_for_department"] == "Acting"

    mock_request.assert_called_once_with("person/popular", {"page": 224513})
