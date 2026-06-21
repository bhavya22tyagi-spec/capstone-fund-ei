"""
PRD §17, CLAUDE.md rule 10 — synthetic_static Fund guard.

Every AI surface (LLM extraction, embedding, RAG retrieval, narrative generation)
must call assert_fund_allows_ai() before doing any work. synthetic_static funds
are physically incapable of triggering these calls — enforced in code, not convention.
"""


class StaticFundAIError(RuntimeError):
    """Raised when an LLM or embedding call is attempted on a synthetic_static Fund."""


def assert_fund_allows_ai(fund_id: str, synthetic_static: bool) -> None:
    """
    Guard called before any LLM or embedding operation.
    Raises StaticFundAIError if the fund is tagged synthetic_static.

    Args:
        fund_id:          The Fund's identifier (for error messages).
        synthetic_static: The value of funds.synthetic_static from the DB row.
    """
    if synthetic_static:
        raise StaticFundAIError(
            f"Fund '{fund_id}' is tagged synthetic_static — LLM and embedding calls "
            "are prohibited (PRD §17, CLAUDE.md rule 10). "
            "Only the 5 designated live Fund IDs may trigger AI operations."
        )
