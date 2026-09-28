"""Published scoring scales — how a detector's checks turn into its score.

A detector that adopts a :class:`Scale` declares every possible outcome of each
of its checks up front (status, severity, points), builds its findings from that
table, and attaches the table to its result. Behavior and report can then never
disagree: the report shows the points each check scored *and* what it could
have scored, positive and negative alike.

Outcomes with ``score=None`` (typically an inconclusive check) are not counted:
they neither raise nor lower the detector score.

A *parametrized* check applies one row set of the scale to many subjects — e.g.
every attribute of a response envelope. Its findings carry ``check`` (the scale
check) and ``subject`` (what was checked), so the scale stays small however many
subjects there are, and reports can group the subjects under their check.
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

    def __init__(self, *outcomes: ScoringOutcome, titles: dict[str, str] | None = None) -> None:
        self.outcomes = list(outcomes)
        # Display titles of the parametrized checks, for grouping in reports.
        self.titles = dict(titles or {})
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
        subject: str | None = None,
    ) -> Finding:
        """A finding whose status, severity and points come from the scale.

        With ``subject`` the finding is one subject of a parametrized check: its
        id is ``<check>.<subject>`` and it records both.
        """
        o = self.get(check, key)
        return Finding(
            id=f"{check}.{subject}" if subject else check,
            check=check if subject else None,
            subject=subject,
            title=title,
            status=o.status,
            severity=o.severity,
            summary=summary,
            evidence=evidence or {},
            recommendation=recommendation,
            outcome=key,
            score=o.score,
        )

    def keys(self, check: str) -> list[str]:
        """The outcome keys of one check, in scale order."""
        return [o.outcome for o in self.outcomes if o.check == check]

    def scoring(self) -> DetectorScoring:
        return DetectorScoring(
            method=self.method,
            outcomes=[o.model_copy() for o in self.outcomes],
            titles=dict(self.titles),
        )

    @staticmethod
    def mean(findings: list[Finding]) -> float | None:
        """Average points of the counted checks; None when none was counted."""
        points = [f.score for f in findings if f.outcome is not None and f.score is not None]
        return round(sum(points) / len(points), 1) if points else None

    @staticmethod
    def roll_up(findings: list[Finding]) -> Status:
        """Worst-of status across the checks, ignoring purely informational ones."""
        order = [Status.PASS, Status.INCONCLUSIVE, Status.WARN, Status.FAIL]
        worst = Status.PASS
        for finding in findings:
            if finding.status in order and order.index(finding.status) > order.index(worst):
                worst = finding.status
        return worst
