"""Local protocol fixture with generic tools; no research or model calls."""

import argparse
import asyncio
import os
from pathlib import Path
import time

from mcp.server.fastmcp import FastMCP


parser = argparse.ArgumentParser()
parser.add_argument("--http", action="store_true")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--handshake-delay", type=float, default=0)
parser.add_argument("--pid-file", type=Path)
args = parser.parse_args()
if args.pid_file is not None:
    args.pid_file.write_text(str(os.getpid()), encoding="ascii")
if args.handshake_delay:
    time.sleep(args.handshake_delay)
server = FastMCP("loopback", host="127.0.0.1", port=args.port, log_level="WARNING")


@server.tool()
async def echo(text: str, delay: float = 0) -> dict[str, str | int]:
    await asyncio.sleep(delay)
    return {"echo": text, "pid": os.getpid()}


@server.tool()
def private_tool() -> str:
    return "must not be mounted"


@server.tool()
def fail() -> str:
    raise RuntimeError("api_key=private-fixture-secret")


if __name__ == "__main__":
    server.run(transport="streamable-http" if args.http else "stdio")
