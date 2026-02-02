"""Git VCS integration stub."""


class GitRepo:
    def __init__(self, path: str):
        self.path = path

    def status(self) -> str:
        raise NotImplementedError("status not implemented")
