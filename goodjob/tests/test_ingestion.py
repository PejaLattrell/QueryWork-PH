import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ingestion.runner import IngestionRunner, SourcesNotConfigured, sources_configured


FIXTURE_SOURCES = {'fixture-source': ('https://fixture.invalid/feed', 'records')}

def raw_job(number):
    return dict(external_id=str(number), title='Python Developer', company_name='Example', job_url=f'https://jobs.invalid/jobs/{number}',
                posted_at='2026-01-01T00:00:00Z', description='Python and FastAPI', location_raw='Philippines', work_arrangement='Remote')


async def no_sleep(_):
    pass


def test_original_bytes_are_preserved_before_serving_writes(tmp_path):
    original = b'{ "records": [ ' + json.dumps(raw_job(1)).encode() + b' ] }\n'
    writes = []
    def source(request):
        assert str(request.url) == 'https://fixture.invalid/feed'
        return httpx.Response(200, content=original, headers={'content-type': 'application/json'})
    def database(request):
        if request.url.path.endswith('job_postings'):
            saved = list(tmp_path.glob('*/fixture-source-attempt-1.body'))
            assert len(saved) == 1 and saved[0].read_bytes() == original
            writes.extend(json.loads(request.content))
        assert request.headers['apikey'] == 'sb_secret_example'
        assert 'authorization' not in request.headers
        return httpx.Response(201)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'sb_secret_example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source), database_transport=httpx.MockTransport(database))
        try:
            result = await runner.run()
            assert result.status == 'completed' and result.jobs_upserted == 1
            metadata = json.loads((Path(result.batch_dir) / 'fixture-source-attempt-1.json').read_text())
            assert metadata['sha256'] == hashlib.sha256(original).hexdigest()
            assert 'sb_secret_example' not in json.dumps(metadata)
            assert writes[0]['external_id'] == '1'
        finally:
            await runner.close()
    asyncio.run(check())


def test_partial_writes_replay_saved_bytes_without_refetching(tmp_path):
    fetched = []
    batch_sizes = []
    fail_second = True
    def source(request):
        fetched.append(str(request.url))
        return httpx.Response(200, json={'records': [raw_job(i) for i in range(101)]})
    def database(request):
        nonlocal fail_second
        if request.url.path.endswith('job_postings'):
            size = len(json.loads(request.content))
            batch_sizes.append(size)
            return httpx.Response(400 if size == 1 and fail_second else 201)
        return httpx.Response(201)
    async def check():
        nonlocal fail_second
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source), database_transport=httpx.MockTransport(database))
        try:
            first = await runner.run()
            assert first.status == 'failed' and first.jobs_found == 101 and first.jobs_upserted == 100
            assert batch_sizes == [100, 1] and len(fetched) == 1
            fail_second = False
            second = await runner.replay(first.batch_dir)
            assert second.status == 'completed' and second.run_id == first.run_id and second.jobs_upserted == 101
            assert len(fetched) == 1 and batch_sizes == [100, 1, 100, 1]
        finally:
            await runner.close()
    asyncio.run(check())


def test_transient_source_responses_are_archived_and_retry_after_is_respected(tmp_path):
    attempts = 0
    waits = []
    def source(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, content=b'rate limited', headers={'Retry-After': '7'})
        return httpx.Response(200, json={'records': []})
    async def sleep(seconds):
        waits.append(seconds)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source), database_transport=httpx.MockTransport(lambda _: httpx.Response(201)),
                                 sleep=sleep)
        try:
            result = await runner.run()
            assert result.status == 'completed' and waits == [7]
            assert (Path(result.batch_dir) / 'fixture-source-attempt-1.body').read_bytes() == b'rate limited'
            assert (Path(result.batch_dir) / 'fixture-source-attempt-2.body').exists()
        finally:
            await runner.close()
    asyncio.run(check())


def test_error_page_is_preserved_and_does_not_become_successful_empty_feed(tmp_path):
    writes = []
    def source(request):
        return httpx.Response(200, content=b'<html>Access blocked</html>')
    def database(request):
        if request.url.path.endswith('job_postings'):
            writes.append(request)
        return httpx.Response(201)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source), database_transport=httpx.MockTransport(database))
        try:
            result = await runner.run()
            assert result.status == 'failed' and result.errors and not writes
            assert (Path(result.batch_dir) / 'fixture-source-attempt-1.body').read_bytes().startswith(b'<html>')
        finally:
            await runner.close()
    asyncio.run(check())


def test_database_failure_stops_collection_and_keeps_local_failure_record(tmp_path):
    source_calls = []
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(lambda r: source_calls.append(r)),
                                 database_transport=httpx.MockTransport(lambda _: httpx.Response(503)), sleep=no_sleep)
        try:
            result = await runner.run()
            assert result.status == 'failed' and not source_calls
            manifest = json.loads((Path(result.batch_dir) / 'manifest.json').read_text())
            assert manifest['result']['status'] == 'failed'
        finally:
            await runner.close()
    asyncio.run(check())


def test_saved_checksum_failure_cannot_publish_changed_bytes(tmp_path):
    writes = []
    def database(request):
        if request.url.path.endswith('job_postings'):
            writes.append(request)
        return httpx.Response(201)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'records': []})),
                                 database_transport=httpx.MockTransport(database))
        try:
            first = await runner.run()
            (Path(first.batch_dir) / 'fixture-source-attempt-1.body').write_text(json.dumps({'records': [raw_job(1)]}))
            replay = await runner.replay(first.batch_dir)
            assert replay.status == 'failed' and not writes
        finally:
            await runner.close()
    asyncio.run(check())


@pytest.mark.parametrize(('status', 'expected_attempts', 'expected_waits'), [
    (403, 1, []), (503, 3, [1, 2]),
])
def test_permanent_failures_stop_and_transient_retries_are_bounded(tmp_path, status, expected_attempts, expected_waits):
    attempts = []
    waits = []
    def source(request):
        attempts.append(request)
        return httpx.Response(status, content=b'feed unavailable')
    async def sleep(seconds):
        waits.append(seconds)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source), database_transport=httpx.MockTransport(lambda _: httpx.Response(201)),
                                 sleep=sleep)
        try:
            result = await runner.run()
            assert result.status == 'failed' and len(attempts) == expected_attempts and waits == expected_waits
            assert len(list(Path(result.batch_dir).glob('fixture-source-attempt-*.body'))) == expected_attempts
        finally:
            await runner.close()
    asyncio.run(check())


def test_final_database_history_failure_remains_visible_in_durable_manifest(tmp_path):
    def database(request):
        return httpx.Response(403 if request.method == 'PATCH' else 201)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'records': [raw_job(1)]})),
                                 database_transport=httpx.MockTransport(database))
        try:
            result = await runner.run()
            assert result.status == 'failed' and result.jobs_upserted == 1
            assert any('finalize' in message for message in result.errors)
            manifest = json.loads((Path(result.batch_dir) / 'manifest.json').read_text())
            assert manifest['result']['status'] == 'failed' and manifest['responses']
        finally:
            await runner.close()
    asyncio.run(check())


@pytest.mark.parametrize('retry_after', ['120', 'nan', 'inf', 'not-a-date'])
def test_unusable_or_long_retry_after_stops_instead_of_retrying_early(retry_after):
    response = httpx.Response(429, headers={'Retry-After': retry_after})
    assert IngestionRunner.retry_delay(response, 0) is None


def test_replay_refuses_unsupported_source_before_any_http_or_serving_write(tmp_path):
    source_calls, database_calls = [], []
    def source(request):
        source_calls.append(request)
        return httpx.Response(200, json={'records': [raw_job(1)]})
    def database(request):
        database_calls.append(request)
        return httpx.Response(201)
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source), database_transport=httpx.MockTransport(database))
        try:
            original = await runner.run()
            source_calls.clear()
            database_calls.clear()
            manifest_path = Path(original.batch_dir) / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['responses'][0]['source'] = 'unsupported-provider'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            with pytest.raises(ValueError, match='unsupported source'):
                await runner.replay(original.batch_dir)
            assert not source_calls and not database_calls
        finally:
            await runner.close()
    asyncio.run(check())


def test_source_redirect_cannot_contact_an_unapproved_provider(tmp_path):
    requested = []
    def source(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={'Location': 'https://unapproved.example/feed'})
    async def check():
        runner = IngestionRunner('https://database.invalid', 'eyJ.example', landing_dir=tmp_path, sources=FIXTURE_SOURCES,
                                 source_transport=httpx.MockTransport(source),
                                 database_transport=httpx.MockTransport(lambda _: httpx.Response(201)))
        try:
            result = await runner.run()
            assert result.status == 'failed'
            assert requested == ['https://fixture.invalid/feed']
        finally:
            await runner.close()
    asyncio.run(check())


def test_default_source_registry_blocks_collection_and_replay_before_any_io(tmp_path):
    requested = []
    landing = tmp_path / 'not-created'
    def unexpected_http(request):
        requested.append(request)
        raise AssertionError('An unconfigured runner must not make HTTP requests.')
    async def check():
        runner = IngestionRunner('https://database.invalid', 'sb_secret_example', landing_dir=landing,
                                 source_transport=httpx.MockTransport(unexpected_http),
                                 database_transport=httpx.MockTransport(unexpected_http))
        try:
            assert not sources_configured() and not runner.sources_configured
            with pytest.raises(SourcesNotConfigured, match='No ingestion sources'):
                await runner.run()
            with pytest.raises(SourcesNotConfigured, match='No ingestion sources'):
                await runner.replay(landing / 'missing-batch')
            assert not requested and not landing.exists()
        finally:
            await runner.close()
    asyncio.run(check())


def test_cli_reports_unselected_sources_before_loading_credentials(monkeypatch, capsys):
    from app import config
    from ingestion.__main__ import execute

    def unexpected_settings():
        raise AssertionError('The no-source CLI path must not load credentials.')
    monkeypatch.setattr(config, 'get_settings', unexpected_settings)
    assert asyncio.run(execute(SimpleNamespace(replay=None, landing_dir=None))) == 2
    assert 'no sources have been selected' in capsys.readouterr().err
