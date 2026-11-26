class ToolError(Exception):
    """Raised by tools. ``retryable`` tells the caller whether backoff+retry makes sense."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable
