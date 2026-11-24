"""Hands notification ids created during a request to a background delivery task."""

from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request

from app.core.deps import DbSession
from app.services import notification_service


class NotificationDispatcher:
    def __init__(self, request: Request, background: BackgroundTasks, db: DbSession) -> None:
        self.state = request.app.state
        self.background = background
        self.db = db

    def flush(self) -> None:
        """Call after the service has committed."""
        ids = notification_service.take_pending_ids(self.db)
        if ids:
            self.background.add_task(
                notification_service.deliver,
                self.state.session_factory,
                self.state.settings,
                self.state.notification_transports,
                ids,
            )


Dispatcher = Annotated[NotificationDispatcher, Depends()]
