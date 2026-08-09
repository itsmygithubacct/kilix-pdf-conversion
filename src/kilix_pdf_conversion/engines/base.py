from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import EngineName, EngineResult


class EngineUnavailable(RuntimeError):
    pass


class ConversionEngine(ABC):
    name: EngineName

    @abstractmethod
    def convert(self, source: Path, output_dir: Path) -> EngineResult:
        raise NotImplementedError

    def close(self) -> None:
        return None
