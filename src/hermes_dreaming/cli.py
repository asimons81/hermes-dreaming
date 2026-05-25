from __future__ import annotations

import argparse
from pathlib import Path

from .analyze import DreamRunConfig, create_dream_artifact, list_artifacts
from .apply import DreamApplyError, apply_artifact, discard_artifact
from .artifact import load_artifact
from .validation import validate_artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dreaming", description="Hermes Dreaming MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a staged dream artifact")
    create.add_argument("--live-root", type=Path, default=Path.cwd(), help="Root of the live workspace")
    create.add_argument("--artifact-root", type=Path, default=Path.cwd() / ".dreaming" / "artifacts", help="Where artifacts are stored")
    create.add_argument("--source", action="append", required=True, type=Path, help="Source file or directory to scan")
    create.add_argument("--provider", default="offline-marker", help="Analysis provider to use")
    create.add_argument("--model", default=None, help="Optional provider model name")
    create.add_argument("--api-key", default=None, help="Optional provider API key")
    create.add_argument("--base-url", default=None, help="Optional provider base URL")

    diff = sub.add_parser("diff", help="Show a staged artifact")
    diff.add_argument("artifact", type=Path, help="Artifact directory")

    validate = sub.add_parser("validate", help="Validate a staged artifact")
    validate.add_argument("artifact", type=Path, help="Artifact directory")
    validate.add_argument("--live-root", type=Path, default=Path.cwd(), help="Root of the live workspace")

    apply = sub.add_parser("apply", help="Apply approved changes from an artifact")
    apply.add_argument("artifact", type=Path, help="Artifact directory")
    apply.add_argument("--live-root", type=Path, default=Path.cwd(), help="Root of the live workspace")
    apply.add_argument("--backup-root", type=Path, default=Path.cwd() / ".dreaming" / "backups", help="Where backups are stored")
    apply.add_argument("--approve", action="append", default=[], help="Approve a proposal id or 'all'")

    discard = sub.add_parser("discard", help="Discard a staged artifact")
    discard.add_argument("artifact", type=Path, help="Artifact directory")
    discard.add_argument("--archive-root", type=Path, default=Path.cwd() / ".dreaming" / "discarded", help="Where discarded artifacts are archived")

    status = sub.add_parser("status", help="List known artifacts")
    status.add_argument("--artifact-root", type=Path, default=Path.cwd() / ".dreaming" / "artifacts", help="Where artifacts are stored")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "create":
        result = create_dream_artifact(
            DreamRunConfig(
                live_root=args.live_root,
                artifact_root=args.artifact_root,
                source_paths=list(args.source),
                provider_name=args.provider,
                model=args.model,
                api_key=args.api_key,
                base_url=args.base_url,
            )
        )
        print(f"artifact: {result.artifact_dir}")
        print(f"status: {result.artifact.status}")
        print(f"proposals: {len(result.artifact.proposals)}")
        if result.validation_errors:
            print("validation: invalid")
            for error in result.validation_errors:
                print(f"- {error}")
            return 1
        print("validation: valid")
        return 0

    if args.command == "diff":
        artifact = load_artifact(args.artifact)
        print(artifact.report.rstrip())
        if artifact.proposals:
            print()
            for proposal in artifact.proposals:
                print(f"- {proposal.id}: {proposal.target_kind} -> {proposal.target_path} [{proposal.mode}]")
                print(f"  {proposal.summary}")
        return 0

    if args.command == "validate":
        artifact = load_artifact(args.artifact)
        errors = validate_artifact(artifact, live_root=args.live_root)
        if errors:
            print("artifact is invalid")
            for error in errors:
                print(f"- {error}")
            return 1
        print("artifact is valid")
        return 0

    if args.command == "apply":
        approve_all = any(item.lower() in {"all", "*", "true", "yes"} for item in args.approve)
        approve_ids = [item for item in args.approve if item.lower() not in {"all", "*", "true", "yes"}]
        try:
            artifact = apply_artifact(
                args.artifact,
                live_root=args.live_root,
                backup_root=args.backup_root,
                approve_all=approve_all,
                approve_ids=approve_ids,
            )
        except DreamApplyError as exc:
            print(str(exc))
            return 1
        print(f"applied artifact: {artifact.artifact_id}")
        print(f"status: {artifact.status}")
        return 0

    if args.command == "discard":
        archived = discard_artifact(args.artifact, archive_root=args.archive_root)
        print(f"discarded artifact: {archived}")
        return 0

    if args.command == "status":
        artifacts = list_artifacts(args.artifact_root)
        if not artifacts:
            print("No dream artifacts found.")
            return 0
        for artifact in artifacts:
            print(f"{artifact.artifact_id}\t{artifact.status}\t{len(artifact.proposals)} proposal(s)\t{artifact.provider}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
