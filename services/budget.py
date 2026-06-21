"""
PRD §17 — Per-run budget cap.

Instantiate BudgetCap once per orchestration run and pass it into every
call_llm() / call_embedding() call. Raises BudgetExceededError before any
API call that would push cumulative spend past the cap.
"""

import os


class BudgetExceededError(RuntimeError):
    """Raised when a projected API call would breach the per-run budget cap."""


class BudgetCap:
    """
    Thread-unsafe accumulator for a single orchestration run.
    Default cap is $0.50 (dev); override with BUDGET_CAP_USD env var.
    """

    def __init__(self, limit_usd: float | None = None) -> None:
        if limit_usd is None:
            limit_usd = float(os.getenv("BUDGET_CAP_USD", "0.50"))
        self.limit_usd: float = limit_usd
        self._spent_usd: float = 0.0

    def check(self, estimated_cost_usd: float) -> None:
        """Raise BudgetExceededError if adding estimated_cost would breach the cap."""
        projected = self._spent_usd + estimated_cost_usd
        if projected > self.limit_usd:
            raise BudgetExceededError(
                f"Budget cap of ${self.limit_usd:.4f} would be exceeded "
                f"(spent=${self._spent_usd:.4f}, "
                f"estimated=${estimated_cost_usd:.4f}, "
                f"projected=${projected:.4f})"
            )

    def record(self, actual_cost_usd: float) -> None:
        """Accumulate actual spend after a completed call."""
        self._spent_usd += actual_cost_usd

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self._spent_usd)
