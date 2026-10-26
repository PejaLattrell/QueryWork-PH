"""Async PostgREST client; API keys stay on the server."""
import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class DatabaseUnavailable(Exception):
    """The database could not serve the requested operation."""


class Database:
    def __init__(self, settings: Settings, transport=None):
        key = settings.supabase_key.get_secret_value()
        headers = {'apikey': key, 'Accept': 'application/json'}
        if key.startswith('eyJ'):
            headers['Authorization'] = f'Bearer {key}'
        self.client = httpx.AsyncClient(base_url=str(settings.supabase_url).rstrip('/') + '/rest/v1/',
                                        headers=headers, timeout=20, transport=transport)

    async def rpc(self, name: str, params: dict):
        try:
            response = await self.client.post(f'rpc/{name}', json=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning('Supabase RPC %s unavailable (%s)', name, type(exc).__name__)
            raise DatabaseUnavailable('Database temporarily unavailable. Check Supabase configuration and migration.') from exc

    async def healthy(self) -> bool:
        try:
            response = await self.client.get('job_postings', params={'select': 'id', 'limit': 1})
            return response.is_success
        except httpx.HTTPError:
            return False

    async def close(self):
        await self.client.aclose()
