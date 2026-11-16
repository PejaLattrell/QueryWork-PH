"""Run one local Python collection at a time without blocking dashboard reads."""
import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import Settings
from app.models.schemas import IngestionStatus, TriggerResponse

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, settings: Settings, runner=None):
        self.settings = settings
        self.runner = runner
        if self.runner is None and settings.supabase_service_role_key:
            from ingestion.runner import IngestionRunner

            self.runner = IngestionRunner(
                supabase_url=str(settings.supabase_url),
                write_key=settings.supabase_service_role_key.get_secret_value(),
                fx_rates=settings.fx_usd_rates,
                landing_dir=settings.ingestion_landing_dir,
            )
        self.lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._last_trigger = float('-inf')
        self._state = 'idle' if self.runner is not None else 'not_configured'
        self._last_result = None
        self._closed = False

    async def trigger(self) -> TriggerResponse:
        if self.runner is None:
            return TriggerResponse(
                status='not_configured',
                message='Collection is not configured. Set the server-only SUPABASE_SERVICE_ROLE_KEY to collect jobs.',
            )
        async with self.lock:
            if self._closed:
                raise HTTPException(503, 'Collection is shutting down. Try again after the app restarts.')
            if self._task is not None and not self._task.done():
                raise HTTPException(429, 'A collection is already running. Try again after it finishes.', headers={'Retry-After': '1'})
            remaining = self.settings.scrape_cooldown_seconds - (time.monotonic() - self._last_trigger)
            if remaining > 0:
                raise HTTPException(429, 'A collection was recently requested. Try again shortly.', headers={'Retry-After': str(int(remaining) + 1)})
            self._state = 'running'
            self._last_result = None
            self._last_trigger = time.monotonic()
            self._task = asyncio.create_task(self._execute(), name='job-ingestion')
        return TriggerResponse(
            status='accepted',
            message='Python collection started. Collection status updates here; dashboard data refreshes every 60 seconds.',
            triggered_at=datetime.now(timezone.utc),
        )

    async def _execute(self):
        try:
            result = await self.runner.run()
            self._last_result = result
            self._state = 'completed' if result.status == 'completed' else 'failed'
            if self._state == 'failed':
                logger.warning('Python collection failed; inspect saved collection history for details')
        except asyncio.CancelledError:
            self._state = 'failed'
            logger.warning('Python collection interrupted during application shutdown')
            raise
        except Exception as exc:
            self._state = 'failed'
            logger.warning('Python collection stopped unexpectedly (%s)', type(exc).__name__)

    def status(self) -> IngestionStatus:
        result = self._last_result
        found = result.jobs_found if result else 0
        saved = result.jobs_upserted if result else 0
        rejected = result.rejected if result else 0
        messages = {
            'idle': 'Ready to collect jobs.',
            'running': 'Python collection is running.',
            'completed': f'Collection completed: {saved} listings saved.',
            'failed': f'Collection failed after saving {saved} listings. Review collection history before retrying.',
            'not_configured': 'Collection is not configured. Dashboard reads remain available.',
        }
        return IngestionStatus(
            status=self._state,
            run_id=result.run_id if result else None,
            jobs_found=found,
            jobs_upserted=saved,
            rejected=rejected,
            message=messages[self._state],
        )

    async def close(self):
        self._closed = True
        if self._task is not None:
            if not self._task.done():
                self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if self.runner is not None:
            await self.runner.close()
