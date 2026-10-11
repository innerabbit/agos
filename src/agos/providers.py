from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .schema import Json
class Provider(Protocol):
    def complete(self, prompt: str) -> Json: ...
@dataclass
class DeterministicProvider:
    """Explicit local fixture provider; it makes no network requests."""
    responses: dict[str, Json]
    def complete(self, prompt: str) -> Json: return self.responses[prompt]
