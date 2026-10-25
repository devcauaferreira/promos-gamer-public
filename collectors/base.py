from typing import Protocol

from database.models import Offer


class SourceError(RuntimeError):
    def __init__(self, state, message):
        self.state = state
        super().__init__(message)


class Source(Protocol):
    store: str
    mode: str

    def status(self) -> dict: ...
    def search(self, category: str, limit: int) -> list[dict]: ...
    def collect(self, entry: dict) -> Offer: ...
