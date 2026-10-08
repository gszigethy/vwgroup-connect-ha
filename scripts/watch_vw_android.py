#!/usr/bin/env python3
"""Report newer Volkswagen Android versions once, using public Google Play data."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Reuse the existing parser, which excludes app versions in review metadata.
sys.path.insert(0, str(Path(__file__).resolve().parent / "app_atlas"))
from build_atlas import scrape_version  # noqa: E402

REPOSITORY = "gszigethy/vwgroup-connect-ha"
PACKAGE = "com.volkswagen.weconnect"
SOURCE_URL = f"https://play.google.com/store/apps/details?id={PACKAGE}&hl=en&gl=US"
MARKER = re.compile(r"<!-- vw-android-version-watch: ([0-9]+(?:\.[0-9]+){1,3}) -->")


def version_key(value: str) -> tuple[int, ...]:
    """Compare numeric components, refusing unknown or prerelease formats."""
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
        raise ValueError(f"Cannot safely compare app version {value!r}")
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (4 - len(parts))


def newer_than_reported(version: str, baseline: str, issues: list[dict[str, Any]]) -> bool:
    """Closed bot issues count too; a stale listing must never trigger a rollback."""
    latest = version_key(baseline)
    for issue in issues:
        if "pull_request" in issue or issue.get("user", {}).get("login") != "github-actions[bot]":
            continue
        match = MARKER.search(issue.get("body") or "")
        if match:
            latest = max(latest, version_key(match.group(1)))
    return version_key(version) > latest


def github_issues(repo: str) -> list[dict[str, Any]]:
    """Read all pages and both states so old/closed notifications are remembered."""
    result = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/issues?state=all&per_page=100",
         "--jq", ".[] | @json"],
        check=True, capture_output=True, text=True, timeout=120,
    )
    # JSON Lines works with both older host gh and current GitHub runners.
    issues = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if any(not isinstance(issue, dict) for issue in issues):
        raise ValueError("Unexpected GitHub issues response; refusing to open an issue")
    return issues


def issue_body(version: str, baseline: str) -> str:
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return (
        f"<!-- vw-android-version-watch: {version} -->\n\n"
        f"Google Play lists a newer **Volkswagen Android app version: {version}**.\n\n"
        f"- Package: `{PACKAGE}`\n"
        f"- Configured verified baseline: **{baseline}**\n"
        f"- Source: [Volkswagen on Google Play]({SOURCE_URL})\n"
        f"- Checked at: {checked}\n\n"
        "Review the APK changes and companion UI compatibility before treating this "
        "version as verified. This watcher does not download or install the APK.\n\n"
        "Google Play rollouts can vary by country and device; this observes the public "
        "US listing and does not guarantee availability on every phone.\n\n"
        "The watcher remembers this version even after the issue is closed. "
        "After verifying a newer APK, update the `VW_ANDROID_BASELINE_VERSION` "
        "repository variable if needed.\n"
    )


def check(repo: str, baseline: str, dry_run: bool = False) -> str:
    if repo != REPOSITORY:
        raise ValueError(f"This watcher is restricted to {REPOSITORY}")
    version_key(baseline)
    version, source = scrape_version("volkswagen", {"package_id": PACKAGE})
    if not version or source != "google_play":
        raise RuntimeError("Google Play returned no version; no issue was opened")
    version_key(version)
    print(f"Google Play: {version}; verified baseline: {baseline}")
    if version_key(version) <= version_key(baseline):
        return "No newer version detected."
    if not newer_than_reported(version, baseline, github_issues(repo)):
        return "This version or a newer version was already reported; no duplicate issue."
    body = issue_body(version, baseline)
    if dry_run:
        print(body)
        return f"Dry run: would open an issue for {version}."
    result = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repo}/issues", "--input", "-"],
        input=json.dumps({"title": f"New Volkswagen Android app version: {version}", "body": body}),
        check=True, capture_output=True, text=True, timeout=60,
    )
    return f"Opened issue: {json.loads(result.stdout)['html_url']}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--baseline", default="4.6.4")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        message = check(args.repo, args.baseline, args.dry_run)
    except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Version watch failed: {exc}\n")
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"### Volkswagen Android app version watch\n\n{message}\n")


if __name__ == "__main__":
    main()
