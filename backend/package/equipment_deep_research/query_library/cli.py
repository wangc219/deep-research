from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from equipment_deep_research.query_library.api import create_app
from equipment_deep_research.query_library.factory import (
    build_service,
    default_seed_manifest,
)
from equipment_deep_research.query_library.models import SourceReference
from equipment_deep_research.query_library.worker import QueryGenerationWorker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and manage equipment-demand Deep Research Queries."
    )
    parser.add_argument("--database-url", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser(
        "serve", help="Start the standalone Query Library API"
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)

    worker = subparsers.add_parser(
        "worker", help="Run the persistent generation worker"
    )
    worker.add_argument("--provider", default=None)
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-interval", type=float, default=1.0)
    worker.add_argument(
        "--max-idle-poll-interval",
        type=float,
        default=10.0,
        help="Maximum polling delay after repeated empty queue checks.",
    )

    generate = subparsers.add_parser("generate", help="Generate and save Query drafts")
    generate.add_argument("--topic", required=True)
    generate.add_argument("--supplemental-information", default="")
    generate.add_argument("--reference-url", action="append", default=[])
    generate.add_argument("--count", type=int, default=12)
    generate.add_argument("--provider", default=None)
    generate.add_argument("--idempotency-key", default="")

    add = subparsers.add_parser("add", help="Add a manual Query")
    add.add_argument("--query", required=True)
    add.add_argument("--supplemental-information", default="")
    add.add_argument("--generation-rationale", default="")
    add.add_argument("--source-json", action="append", default=[])
    add.add_argument("--publish", action="store_true")

    listing = subparsers.add_parser("list", help="List stored Queries")
    listing.add_argument("--status", choices=["draft", "published", "archived"])
    listing.add_argument("--source-type", choices=["manual", "agent", "import"])
    listing.add_argument("--search", default="")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)

    show = subparsers.add_parser("show", help="Show one Query and revisions")
    show.add_argument("query_id")

    publish = subparsers.add_parser("publish", help="Publish a Query")
    publish.add_argument("query_id")
    publish.add_argument("--version", type=int)

    archive = subparsers.add_parser("archive", help="Archive a Query")
    archive.add_argument("query_id")
    archive.add_argument("--version", type=int)

    seed = subparsers.add_parser(
        "import-seeds", help="Import the initial curated library"
    )
    seed.add_argument("--manifest", default=str(default_seed_manifest()))

    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            create_app(database_url=args.database_url),
            host=args.host,
            port=args.port,
        )
        return 0
    if args.command == "worker":
        try:
            service = build_service(
                args.database_url, with_generator=True, provider_name=args.provider
            )
        except ValueError as exc:
            print(
                f"Query generation provider is unavailable: {exc}. "
                "Queued jobs will fail explicitly until the worker is restarted "
                "with valid credentials.",
                file=sys.stderr,
            )
            service = build_service(args.database_url)
        query_worker = QueryGenerationWorker(
            service,
            poll_interval_seconds=args.poll_interval,
            max_idle_poll_interval_seconds=args.max_idle_poll_interval,
        )
        result = asyncio.run(
            query_worker.run_once() if args.once else query_worker.run_forever()
        )
        if result is not None:
            _print_json(result)
        return 0
    if args.command == "generate":
        service = build_service(
            args.database_url, with_generator=True, provider_name=args.provider
        )
        job = service.submit_generation(
            topic=args.topic,
            supplemental_information=args.supplemental_information,
            reference_urls=args.reference_url,
            count=args.count,
            idempotency_key=args.idempotency_key,
        )
        completed = asyncio.run(
            service.process_generation(job.generation_id, worker_id="query-cli")
        )
        _print_json(completed.to_dict())
        return 0 if completed.status == "completed" else 1

    service = build_service(args.database_url)
    if args.command == "add":
        references = [_source_from_json(value) for value in args.source_json]
        _print_json(
            service.create_query(
                query=args.query,
                supplemental_information=args.supplemental_information,
                generation_rationale=args.generation_rationale,
                source_references=references,
                status="published" if args.publish else "draft",
            ).to_dict()
        )
    elif args.command == "list":
        _print_json(
            service.list_queries(
                status=args.status,
                source_type=args.source_type,
                search=args.search,
                limit=args.limit,
                offset=args.offset,
            )
        )
    elif args.command == "show":
        _print_json(service.get_query(args.query_id, include_revisions=True))
    elif args.command == "publish":
        _print_json(
            service.set_status(
                args.query_id, status="published", expected_version=args.version
            ).to_dict()
        )
    elif args.command == "archive":
        _print_json(
            service.set_status(
                args.query_id, status="archived", expected_version=args.version
            ).to_dict()
        )
    elif args.command == "import-seeds":
        _print_json(service.import_seed_manifest(Path(args.manifest)))
    return 0


def _source_from_json(value: str) -> SourceReference:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("--source-json must contain a JSON object")
    return SourceReference.from_dict(payload)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
