"""Phase 1 mail gate: log only. Does not send mail.

No SMTP. GO/ALERT/EXIT → MAIL_WOULD_SEND. WAIT → MAIL_SUPPRESSED.
"""

from v2 import MAIL_VERDICTS, VALID_VERDICTS
from v2.schema import InvalidVerdictError, require_valid_verdict


MAIL_WOULD_SEND = "MAIL_WOULD_SEND"
MAIL_SUPPRESSED = "MAIL_SUPPRESSED"


def would_send(verdict: str, *, strict: bool = True) -> bool:
    if strict:
        require_valid_verdict(verdict)
    elif verdict not in VALID_VERDICTS:
        raise InvalidVerdictError(f"invalid verdict: {verdict!r}")
    return verdict in MAIL_VERDICTS


def dry_run(test_id: str, verdict: str, *, strict: bool = True) -> str:
    """Return MAIL_WOULD_SEND or MAIL_SUPPRESSED. No SMTP."""
    send = would_send(verdict, strict=strict)
    tag = MAIL_WOULD_SEND if send else MAIL_SUPPRESSED
    print(f"{tag} test_id={test_id} verdict={verdict}")
    return tag
