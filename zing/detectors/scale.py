"""Published scoring scales — how a detector's checks turn into its score.

A detector that adopts a :class:`Scale` declares every possible outcome of each
of its checks up front (status, severity, points), builds its findings from that
table, and attaches the table to its result. Behavior and report can then never
disagree: the report shows the points each check scored *and* what it could
have scored, positive and negative alike.

Outcomes with ``score=None`` (typically an inconclusive check) are not counted:
they neither raise nor lower the detector score.
"""

from __future__ import annotations

from typing import Any

from zing.models import DetectorScoring, Finding, ScoringOutcome, Severity, Status


def outcome(
    check: str,
    key: str,
    score: float | None,
    status: Status,
    severity: Severity = Severity.INFO,
    *,
    label: str,
) -> ScoringOutcome:
    return ScoringOutcome(
        check=check, outcome=key, score=score, status=status, severity=severity, label=label
    )


class Scale:
    """A detector's scoring scale: every (check, outcome) it can report."""

    method = "mean_of_checks"

    def __init__(self, *outcomes: ScoringOutcome) -> None:
        self.outcomes = list(outcomes)
        self._by_key = {(o.check, o.outcome): o for o in self.outcomes}
        if len(self._by_key) != len(self.outcomes):
            raise ValueError("duplicate (check, outcome) in scoring scale")

    def get(self, check: str, key: str) -> ScoringOutcome:
        return self._by_key[(check, key)]

    def finding(
        self,
        check: str,
        key: str,
        *,
        title: str,
        summary: str = "",
        evidence: dict[str, Any] | None = None,
        recommendation: str | None = None,
    ) -> Finding:
        """A finding whose status, severity and points come from the scale."""
        o = self.get(check, key)
        return Finding(
            id=check,
            title=title,
            status=o.status,
            severity=o.severity,
            summary=summary,
            evidence=evidence or {},
            recommendation=recommendation,
            outcome=key,
            score=o.score,
        )

    def scoring(self) -> DetectorScoring:
        return DetectorScoring(method=self.method, outcomes=[o.model_copy() for o in self.outcomes])

    @staticmethod
    def mean(findings: list[Finding]) -> float | None:
        """Average points of the counted checks; None when none was counted."""
        points = [f.score for f in findings if f.outcome is not None and f.score is not None]
        return round(sum(points) / len(points), 1) if points else None
