class CommandExecutionError(Exception):

    def __init__(
        self, message: str, return_code: int, stdout: str = "", stderr: str = ""
    ):
        super().__init__(message)
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr