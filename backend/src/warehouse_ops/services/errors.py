class NotFoundError(LookupError):
    """A requested record (e.g. a SKU code) does not exist."""


class RuleViolationError(ValueError):
    """A request breaks a business rule (e.g. replenishing past a pick face's max)."""
