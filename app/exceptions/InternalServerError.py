class InternalServerError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.statusCode = 500
