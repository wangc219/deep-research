"""Small live keyword diagnostic; no credentials in saved evidence."""

import asyncio
import json
import time
from pathlib import Path

from platform_core.config.options import aminer_api_opts
from platform_core.services.aminer_client import AMinerClient, AMinerError, normalize_paper
from platform_core.storage.postgres.manager import pg_manager


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            config = await aminer_api_opts.get(db)
        client = AMinerClient(config)
        output = []
        for endpoint, payload in [
            ("search", {"keyword": "FlashAttention", "page": 0, "size": 5}),
            ("search", {"keyword": "sparse attention", "page": 0, "size": 5}),
            (
                "title_search",
                {
                    "title": "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
                    "page": 1,
                    "size": 3,
                },
            ),
            ("search", {"keyword": "retrieval augmented generation", "page": 0, "size": 5}),
            ("search", {"keyword": "long context", "page": 0, "size": 5}),
        ]:
            started = time.monotonic()
            try:
                result = await client.request(endpoint, payload)
                papers = [normalize_paper(x) for x in result["data"] if isinstance(x, dict)]
                record = {
                    "endpoint": endpoint,
                    "payload": payload,
                    "status": "ok",
                    "total": result.get("total"),
                    "papers": papers,
                }
            except AMinerError as exc:
                record = {"endpoint": endpoint, "payload": payload, "status": exc.status, "message": str(exc)}
            record["seconds"] = round(time.monotonic() - started, 3)
            output.append(record)
            print(
                json.dumps(
                    {k: v for k, v in record.items() if k != "papers"}
                    | {
                        "returned": len(record.get("papers", [])),
                        "titles": [x["title"] for x in record.get("papers", [])],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        target = Path("/app/outputs/aminer-conversations-20261019/keyword-diagnostic.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "transport": "real AMiner",
                    "estimated_cost_cents": 4,
                    "ledger": "direct provider diagnostic, excluded from conversation ledger",
                    "cases": output,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await pg_manager.close()


asyncio.run(main())
