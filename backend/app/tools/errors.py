class ToolError(Exception):
    """Raised by tools. ``retryable`` tells the caller whether backoff+retry makes sense."""

    def __init__(self, message: str, retryable: bool = True, not_possible: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.not_possible = not_possible          # a correct "that can't be done" answer, not a broken tool
