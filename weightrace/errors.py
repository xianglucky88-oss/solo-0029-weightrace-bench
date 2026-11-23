class Problem(Exception):
    def __init__(self, code, message, status=400, **details):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details

    def payload(self):
        return {"error": self.code, "message": str(self), "details": self.details}
