from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dreaming", description="Hermes Dreaming MVP")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show project status")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        print("hermes-dreaming: scaffold ready")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
