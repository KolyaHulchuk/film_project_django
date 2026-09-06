from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AIRecommendationThrottle(UserRateThrottle):
    """Shared per-user AI recommendation budget.

    Used by both api.views.RecommendationsAiView and movies.views.ai_recomendations
    so the same rolling-hour quota applies to a user regardless of whether the
    request came through the DRF API or the browser chat panel — the scarce
    resource (Groq calls) is the same either way.
    """

    scope = "ai_recommendation_user"
    rate = "10/hour"

    def get_rate(self):
        return self.rate


class AIRecommendationAnonThrottle(AnonRateThrottle):
    scope = "ai_recommendation_anon"
    rate = "3/hour"

    def get_rate(self):
        return self.rate
