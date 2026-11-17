from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from users.throttling import ClientIPMixin

# ClientIPMixin: anonymous clients are counted per real IP (users/client_ip.py), not per
# X-Forwarded-For string, which the client controls.


class AIRecommendationThrottle(ClientIPMixin, UserRateThrottle):
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


class AIRecommendationAnonThrottle(ClientIPMixin, AnonRateThrottle):
    scope = "ai_recommendation_anon"
    rate = "3/hour"

    def get_rate(self):
        return self.rate


class CommentCreateThrottle(ClientIPMixin, UserRateThrottle):
    """Shared by movies.views.comment_create and api.views.CommentListCreateView."""

    scope = "comment_create"
    rate = "10/hour"

    def get_rate(self):
        return self.rate


class CommentVoteThrottle(ClientIPMixin, UserRateThrottle):
    """Shared by movies.views.comment_vote and api.views.CommentVoteView."""

    scope = "comment_vote"
    rate = "60/min"

    def get_rate(self):
        return self.rate
