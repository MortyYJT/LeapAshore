from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock

from .models import AgentRecommendationResponse, ApplicantProfile, DemoUser, RecommendationRunSummary


class DemoStore:
    """Small repository abstraction for the demo; replace with PostgreSQL in production."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._users: dict[str, DemoUser] = {}
        self._tokens: dict[str, str] = {}
        self._profiles: dict[str, ApplicantProfile] = {}
        self._runs: dict[str, list[tuple[RecommendationRunSummary, AgentRecommendationResponse]]] = {}

    def login(self, email: str) -> tuple[str, DemoUser]:
        normalized = email.strip().lower()
        user_id = f"usr_{sha256(normalized.encode()).hexdigest()[:10]}"
        token = f"demo_{sha256((normalized + ':offerpilot').encode()).hexdigest()}"
        user = DemoUser(id=user_id, email=normalized, display_name=normalized.split("@", 1)[0])
        with self._lock:
            self._users[user_id] = user
            self._tokens[token] = user_id
        return token, user

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            user_id = self._tokens.get(token)
            return self._users.get(user_id) if user_id else None

    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile:
        with self._lock:
            self._profiles[user_id] = profile
        return profile

    def get_profile(self, user_id: str) -> ApplicantProfile | None:
        with self._lock:
            return self._profiles.get(user_id)

    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary:
        summary = RecommendationRunSummary(
            run_id=result.run_id,
            created_at=datetime.now(UTC),
            workflow_version=result.workflow_version,
            target_field=profile.target_field,
            intake=profile.intake,
            recommendation_count=len(result.recommendations),
            summary=result.summary,
        )
        with self._lock:
            self._runs.setdefault(user_id, []).insert(0, (summary, result))
        return summary

    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]:
        with self._lock:
            return [summary for summary, _ in self._runs.get(user_id, [])]

    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None:
        with self._lock:
            for summary, result in self._runs.get(user_id, []):
                if summary.run_id == run_id:
                    return result
        return None


store = DemoStore()
