"""Command line entry points for validation and the localhost server."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ffcs_studio.config import ConfigurationError, Settings
from ffcs_studio.validation import (
    ValidationSetupError,
    summarize_report,
    validate_json_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ffcs-studio")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the local FFCS Studio website")
    serve.add_argument("--host", help="loopback host (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, help="local TCP port (default: 8765)")

    validate = subparsers.add_parser("validate", help="validate VTOP capture JSON")
    validate.add_argument("files", nargs="+", type=Path)
    validate.add_argument("--schema", type=Path, help="explicit JSON Schema path")
    return parser


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from ffcs_studio.web.app import create_app

    settings = Settings.from_env(host=args.host, port=args.port)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
    )
    return 0


def _validate(args: argparse.Namespace) -> int:
    exit_code = 0
    for path in args.files:
        report = validate_json_file(path, schema_path=args.schema)
        for line in summarize_report(report):
            print(line)
        if not report.valid:
            exit_code = 1
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            return _serve(args)
        if args.command == "validate":
            return _validate(args)
    except (ConfigurationError, ValidationSetupError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2
