"""Run a local collection or replay saved originals from the command line."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ingestion.runner import IngestionRunner, sources_configured


async def execute(args) -> int:
    if not sources_configured():
        print('Ingestion is not configured: no sources have been selected. '
              'Choose and implement an authorized source before collecting.', file=sys.stderr)
        return 2
    from app.config import get_settings

    settings = get_settings()
    key = settings.supabase_service_role_key
    if not key:
        print('Ingestion is not configured: set SUPABASE_SERVICE_ROLE_KEY in goodjob/.env.', file=sys.stderr)
        return 2
    runner = IngestionRunner(str(settings.supabase_url), key.get_secret_value(),
                             settings.fx_usd_rates, args.landing_dir or settings.ingestion_landing_dir)
    try:
        result = await runner.replay(args.replay) if args.replay else await runner.run()
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.status == 'completed' else 1
    finally:
        await runner.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Run configured Python ingestion, preserving originals before publishing. Sources are not selected.')
    parser.add_argument('--replay', type=Path, metavar='BATCH_DIRECTORY',
                        help='process a saved manifest and response files without fetching sources again')
    parser.add_argument('--landing-dir', type=Path, help='override the local raw-response landing directory')
    args = parser.parse_args()
    try:
        return asyncio.run(execute(args))
    except (ValueError, OSError, KeyError) as exc:
        print(f'Ingestion could not start ({type(exc).__name__}). Check configuration and the saved batch path.', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Collection interrupted. Inspect the landing directory for saved originals.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
