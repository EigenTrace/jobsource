"""Tiny progress-event helper shared by the pipeline stages."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from .schemas import ProgressEvent

Emit = Optional[Callable[[ProgressEvent], Awaitable[None]]]


async def emit(sink: Emit, stage: str, message: str, **data) -> None:
    if sink is None:
        return
    try:
        await sink(ProgressEvent(stage=stage, message=message, data=data))
    except Exception:
        pass
