import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.models.schemas import TriggerResponse

logger = logging.getLogger(__name__)


class N8NService:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=15, transport=transport)
        self.lock = asyncio.Lock()
        self.last_trigger = float('-inf')

    async def trigger(self) -> TriggerResponse:
        if not self.settings.n8n_webhook_url:
            logger.info('Scrape requested; N8N_WEBHOOK_URL is not configured')
            return TriggerResponse(status='not_configured', message='Scraper is not connected. Configure N8N_WEBHOOK_URL to collect live jobs.')
        async with self.lock:
            remaining = self.settings.scrape_cooldown_seconds - (time.monotonic() - self.last_trigger)
            if remaining > 0:
                raise HTTPException(429, 'A scrape was recently requested. Try again shortly.', headers={'Retry-After': str(int(remaining) + 1)})
            try:
                response = await self.client.post(str(self.settings.n8n_webhook_url), json={'requested_by': 'goodjob-dashboard'})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning('n8n trigger failed (%s)', type(exc).__name__)
                raise HTTPException(502, 'n8n could not accept the scrape. Check that the workflow is published and the webhook is reachable.') from exc
            self.last_trigger = time.monotonic()
            return TriggerResponse(status='accepted', message='Scrape accepted. The dashboard refreshes every 60 seconds.', triggered_at=datetime.now(timezone.utc))

    async def close(self):
        await self.client.aclose()
