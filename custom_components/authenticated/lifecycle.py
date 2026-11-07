"""Cancellation and close hooks for the integration runtime."""

from __future__ import annotations

import asyncio
import inspect
import logging

_LOGGER = logging.getLogger(__name__)


class Lifecycle:
    """Tracks unsubscribe callbacks, tasks, and the enrichment session."""

    def __init__(self) -> None:
        self.closed = False
        self.session = None
        self._unsubs: list = []
        self._tasks: list = []

    def track_unsub(self, unsub) -> None:
        """Remember a callback that removes a listener."""
        if unsub is not None and not self.closed:
            self._unsubs.append(unsub)

    def track_task(self, task) -> None:
        """Remember a task so unload can cancel it."""
        if task is None or self.closed:
            return
        self._tasks = [item for item in self._tasks if not item.done()]
        self._tasks.append(task)

    async def async_shutdown(self) -> None:
        """Unsubscribe, cancel outstanding work, and close the HTTP session."""
        if self.closed:
            return
        self.closed = True
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception as err:
                _LOGGER.debug("Listener cleanup failed (%s)", type(err).__name__)
        self._unsubs.clear()
        await self._cancel_tasks()
        # A callback queued before unsubscribe can still run at the first await.
        # It sees ``closed`` and must not create more work, but cancel anything
        # that was already scheduled.
        await self._cancel_tasks()
        session = self.session
        self.session = None
        if session is not None:
            close = session.close()
            if inspect.isawaitable(close):
                await close

    async def _cancel_tasks(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as err:
                _LOGGER.debug("Task ended during shutdown (%s)", type(err).__name__)
