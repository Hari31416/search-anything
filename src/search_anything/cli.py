"""Command line entry points for the API and durable worker."""

from __future__ import annotations

import argparse
import asyncio
import logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="search-anything")
    commands = parser.add_subparsers(dest="command", required=True)
    api = commands.add_parser("api", help="run the local HTTP API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    commands.add_parser("worker", help="run the durable background worker")
    commands.add_parser("migrate", help="apply database migrations")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "api":
        import uvicorn

        uvicorn.run("search_anything.api:app", host=args.host, port=args.port)
    elif args.command == "worker":
        from search_anything.worker import run_worker

        asyncio.run(run_worker())
    else:
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
