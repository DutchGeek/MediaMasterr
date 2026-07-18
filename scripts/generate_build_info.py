from __future__ import annotations

import argparse
import json
from pathlib import Path


def _optional(value: str) -> str | None:
    cleaned = value.strip()
    return cleaned or None


def build_payload(args: argparse.Namespace) -> dict[str, str | None]:
    payload: dict[str, str | None] = {
        "application_version": args.application_version,
        "git_sha": _optional(args.git_sha),
        "short_sha": _optional(args.short_sha),
        "branch": _optional(args.branch),
        "tag": _optional(args.tag),
        "build_date": _optional(args.build_date),
        "build_time": _optional(args.build_time),
        "build_timestamp": _optional(args.build_timestamp),
        "github_workflow_run": _optional(args.github_workflow_run),
        "github_run_number": _optional(args.github_run_number),
        "github_repository": _optional(args.github_repository),
        "docker_image_tag": _optional(args.docker_image_tag),
        "docker_image_digest": _optional(args.docker_image_digest),
        "backend_version": args.backend_version,
        "frontend_version": args.frontend_version,
        "environment": args.environment,
        "running_sha": _optional(args.running_sha),
        "latest_built_sha": _optional(args.latest_built_sha),
        "frontend_sha": _optional(args.frontend_sha),
        "backend_sha": _optional(args.backend_sha),
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MediaMasterr build_info.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--application-version", required=True)
    parser.add_argument("--backend-version", required=True)
    parser.add_argument("--frontend-version", required=True)
    parser.add_argument("--environment", default="container")
    parser.add_argument("--git-sha", default="")
    parser.add_argument("--short-sha", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--build-date", default="")
    parser.add_argument("--build-time", default="")
    parser.add_argument("--build-timestamp", default="")
    parser.add_argument("--github-workflow-run", default="")
    parser.add_argument("--github-run-number", default="")
    parser.add_argument("--github-repository", default="")
    parser.add_argument("--docker-image-tag", default="")
    parser.add_argument("--docker-image-digest", default="")
    parser.add_argument("--running-sha", default="")
    parser.add_argument("--latest-built-sha", default="")
    parser.add_argument("--frontend-sha", default="")
    parser.add_argument("--backend-sha", default="")

    args = parser.parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_payload(args), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
