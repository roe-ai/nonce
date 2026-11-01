class AccessError(Exception):
    """A refused agent call. `code` is stable for agents to branch on."""

    def __init__(self, code: str, message: str, status: int = 403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
