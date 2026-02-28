"""Base collector ABC — all data sources implement this interface."""

from abc import ABC, abstractmethod

from models.schemas import Signal


class BaseCollector(ABC):
    """Abstract base for all signal collectors."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name."""
        ...

    @abstractmethod
    def collect(self) -> list[Signal]:
        """Fetch and return signals from this source."""
        ...
