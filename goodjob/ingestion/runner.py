"""Collect bounded feeds, preserve originals locally, and publish serving rows."""

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ingestion.normalize import normalize_job


SOURCES = {
    'remotive': ('https://remotive.com/api/remote-jobs?category=software-dev&limit=50', 'jobs'),
    'arbeitnow': ('https://www.arbeitnow.com/api/job-board-api', 'data'),
}
TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if parsed.port:
        host += ':' + str(parsed.port)
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query)
                       if key in {'category', 'limit', 'page'}])
    return urlunsplit((parsed.scheme, host, parsed.path, query, ''))


def write_json(path: Path, value: dict) -> None:
    """Replace local state only after its complete contents have been flushed."""
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass
class RunResult:
    run_id: str
    status: str = 'failed'
    jobs_found: int = 0
    jobs_upserted: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)
    batch_dir: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


class IngestionRunner:
    def __init__(self, supabase_url: str, write_key: str, fx_rates: dict | None = None,
                 landing_dir: Path | str = 'data/landing', *, source_transport=None,
                 database_transport=None, sleep=asyncio.sleep):
        if not write_key:
            raise ValueError('A server-side Supabase write key is required for ingestion.')
        self.fx_rates = fx_rates or {}
        self.landing_dir = Path(landing_dir).resolve()
        self.sleep = sleep
        self.lock = asyncio.Lock()
        self.source_client = httpx.AsyncClient(
            headers={'User-Agent': 'GoodJob/1.0 (public job market analytics)'},
            timeout=30, follow_redirects=True, transport=source_transport)
        headers = {'apikey': write_key, 'Prefer': 'return=minimal'}
        if write_key.startswith('eyJ'):
            headers['Authorization'] = 'Bearer ' + write_key
        self.database_client = httpx.AsyncClient(
            base_url=supabase_url.rstrip('/') + '/rest/v1/', headers=headers,
            timeout=30, transport=database_transport)

    async def close(self):
        await self.source_client.aclose()
        await self.database_client.aclose()

    @staticmethod
    def retry_delay(response: httpx.Response | None, attempt: int) -> float | None:
        """Long server-requested waits stop this bounded run instead of retrying early."""
        value = response.headers.get('Retry-After') if response is not None else None
        if value:
            try:
                delay = max(0, float(value))
            except ValueError:
                try:
                    delay = max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    return None
            return delay if delay <= 60 else None
        return float(2 ** attempt)

    async def _database_request(self, method: str, path: str, **kwargs):
        for attempt in range(3):
            response = None
            try:
                response = await self.database_client.request(method, path, **kwargs)
                if response.is_success:
                    return
                if response.status_code not in TRANSIENT_STATUSES:
                    raise RuntimeError(f'Database request failed (HTTP {response.status_code}).')
            except httpx.TransportError:
                pass
            if attempt == 2:
                break
            delay = self.retry_delay(response, attempt)
            if delay is None:
                break
            await self.sleep(delay)
        code = f'HTTP {response.status_code}' if response is not None else 'connection failure'
        raise RuntimeError(f'Database request failed ({code}); saved responses can be replayed.')

    def _save_response(self, batch: Path, source: str, attempt: int, response: httpx.Response) -> dict:
        name = f'{source}-attempt-{attempt + 1}'
        body_path = batch / (name + '.body')
        body = response.content
        with body_path.open('xb') as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        checksum = hashlib.sha256(body).hexdigest()
        if hashlib.sha256(body_path.read_bytes()).hexdigest() != checksum:
            raise OSError('Saved response checksum did not match.')
        metadata = dict(source=source, request_url=safe_url(str(response.request.url)),
                        received_at=utc_now(), status_code=response.status_code,
                        content_type=response.headers.get('content-type', ''),
                        raw_file=body_path.name, sha256=checksum, byte_count=len(body))
        write_json(batch / (name + '.json'), metadata)
        return metadata

    async def _fetch(self, batch: Path, source: str) -> tuple[dict | None, str | None]:
        for attempt in range(3):
            response = None
            try:
                response = await self.source_client.get(SOURCES[source][0])
                metadata = self._save_response(batch, source, attempt, response)
                if response.is_success:
                    return metadata, None
                if response.status_code not in TRANSIENT_STATUSES:
                    return None, f'{source}: source request failed (HTTP {response.status_code}).'
            except httpx.TransportError:
                pass
            if attempt == 2:
                break
            delay = self.retry_delay(response, attempt)
            if delay is None:
                break
            await self.sleep(delay)
        code = f'HTTP {response.status_code}' if response is not None else 'connection failure'
        return None, f'{source}: source request failed ({code}).'

    def _load_jobs(self, batch: Path, manifest: dict, result: RunResult) -> list[dict]:
        jobs = {}
        for metadata in manifest['responses']:
            source = metadata.get('source')
            try:
                if source not in SOURCES:
                    raise ValueError('unknown source')
                path = (batch / metadata['raw_file']).resolve()
                if path.parent != batch.resolve():
                    raise ValueError('invalid response path')
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != metadata['sha256']:
                    raise ValueError('checksum mismatch')
                document = json.loads(body)
                rows = document.get(SOURCES[source][1]) if isinstance(document, dict) else None
                if not isinstance(rows, list):
                    raise ValueError('expected a job list')
                observed = datetime.fromisoformat(metadata['received_at'])
                if observed.tzinfo is None:
                    raise ValueError('missing collection timezone')
                result.jobs_found += len(rows)
                for row in rows:
                    normalized = normalize_job(row, source, self.fx_rates, now=observed)
                    if normalized is None:
                        result.rejected += 1
                    else:
                        jobs[normalized['fingerprint']] = normalized
            except (OSError, ValueError, TypeError, KeyError) as exc:
                result.errors.append(f'{source or "unknown source"}: saved response could not be processed ({type(exc).__name__}).')
        return list(jobs.values())

    async def _process(self, batch: Path, manifest: dict, *, collect: bool) -> RunResult:
        result = RunResult(run_id=manifest['run_id'], batch_dir=str(batch),
                           errors=list(manifest.get('source_errors', [])))
        started = False
        try:
            await self._database_request('POST', 'scrape_runs', params={'on_conflict': 'id'},
                                         headers={'Prefer': 'resolution=merge-duplicates,return=minimal'},
                                         json={'id': result.run_id, 'source': '+'.join(SOURCES),
                                               'status': 'running', 'started_at': manifest['started_at'],
                                               'completed_at': None, 'jobs_found': 0, 'jobs_upserted': 0,
                                               'error_message': None})
            started = True
            if collect:
                for source in SOURCES:
                    metadata, error = await self._fetch(batch, source)
                    if metadata is not None:
                        manifest['responses'].append(metadata)
                    if error:
                        manifest['source_errors'].append(error)
                        result.errors.append(error)
                    write_json(batch / 'manifest.json', manifest)
            jobs = self._load_jobs(batch, manifest, result)
            if not manifest['responses'] and not result.errors:
                result.errors.append('No completed source responses are available in this saved batch.')
            for offset in range(0, len(jobs), 100):
                chunk = jobs[offset:offset + 100]
                try:
                    await self._database_request('POST', 'job_postings', params={'on_conflict': 'fingerprint'},
                                                 headers={'Prefer': 'resolution=merge-duplicates,return=minimal'}, json=chunk)
                    result.jobs_upserted += len(chunk)
                except RuntimeError as exc:
                    result.errors.append(f'Batch {offset // 100 + 1}: {exc}')
            result.status = 'failed' if result.errors else 'completed'
        except (RuntimeError, OSError, ValueError) as exc:
            result.errors.append(f'Collection could not finish ({type(exc).__name__}). Check the saved batch and database access.')
        except asyncio.CancelledError:
            result.errors.append('Collection was interrupted; replay the saved batch to recover any saved responses.')
            raise
        finally:
            result.status = 'failed' if result.errors else 'completed'
            if started:
                try:
                    await self._database_request('PATCH', 'scrape_runs', params={'id': 'eq.' + result.run_id},
                                                 json={'status': result.status, 'jobs_found': result.jobs_found,
                                                       'jobs_upserted': result.jobs_upserted,
                                                       'error_message': '; '.join(result.errors)[:1500] or None,
                                                       'completed_at': utc_now()})
                except (RuntimeError, httpx.HTTPError):
                    result.errors.append('Could not finalize database collection history; inspect the saved batch before replaying.')
                    result.status = 'failed'
            manifest['result'] = result.to_dict()
            manifest['finished_at'] = utc_now()
            write_json(batch / 'manifest.json', manifest)
        return result

    async def run(self) -> RunResult:
        async with self.lock:
            run_id = str(uuid.uuid4())
            batch = self.landing_dir / run_id
            batch.mkdir(parents=True, exist_ok=False)
            manifest = dict(version=1, run_id=run_id, started_at=utc_now(), responses=[], source_errors=[])
            write_json(batch / 'manifest.json', manifest)
            return await self._process(batch, manifest, collect=True)

    async def replay(self, batch_dir: Path | str) -> RunResult:
        """Reprocess original saved bytes with the original run ID and no feed requests."""
        async with self.lock:
            batch = Path(batch_dir).resolve()
            manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
            uuid.UUID(manifest['run_id'])
            if manifest.get('version') != 1 or not isinstance(manifest.get('responses'), list):
                raise ValueError('This is not a supported ingestion batch manifest.')
            return await self._process(batch, manifest, collect=False)
