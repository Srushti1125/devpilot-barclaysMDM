"""Small observer hook for completed generation events."""
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("devpilot.events")


@dataclass
class GenerationEvent:
    project_id: str
    artifact_type: str
    eval_score: float
    model_used: str
    retry_count: int
    usage: dict = field(default_factory=dict)


_listeners: list[Callable[[GenerationEvent], None]] = []


def subscribe(listener: Callable[[GenerationEvent], None]) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def publish(event: GenerationEvent) -> None:
    for listener in tuple(_listeners):
        try:
            listener(event)
        except Exception:
            logger.exception("Generation event listener failed")
