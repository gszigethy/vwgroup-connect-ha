"""Version notifications must not duplicate, regress, or write on lookup failure."""

from __future__ import annotations

import json
import subprocess

import pytest

from scripts import watch_vw_android as watch


def reported(version: str, state: str = "closed") -> dict:
    return {
        "user": {"login": "github-actions[bot]"},
        "body": f"<!-- vw-android-version-watch: {version} -->",
        "state": state,
    }


@pytest.mark.parametrize(
    ("version", "baseline", "issues", "expected"),
    [
        ("4.6.4", "4.6.4", [], False),
        ("4.6.4.0", "4.6.4", [], False),
        ("4.6.5", "4.6.4", [], True),
        ("4.10.0", "4.9.0", [], True),
        ("4.6.5", "4.6.4", [reported("4.6.5", "open")], False),
        ("4.6.5", "4.6.4", [reported("4.6.5")], False),
        ("4.6.5", "4.6.4", [reported("4.7.0")], False),
        ("4.7.1", "4.6.4", [reported("4.7.0")], True),
    ],
)
def test_numeric_order_and_closed_issue_dedup(version, baseline, issues, expected):
    assert watch.newer_than_reported(version, baseline, issues) is expected


def test_public_issue_cannot_spoof_bot_history():
    issue = reported("99.0.0")
    issue["user"]["login"] = "someone-else"
    assert watch.newer_than_reported("4.6.5", "4.6.4", [issue])


@pytest.mark.parametrize("version", ["Varies with device", "4.7.0-beta", "", "4.x.0"])
def test_unknown_version_is_rejected(version):
    with pytest.raises(ValueError):
        watch.version_key(version)


def test_lookup_failure_never_reads_or_writes_issues(monkeypatch):
    monkeypatch.setattr(watch, "scrape_version", lambda *a: (None, None))
    monkeypatch.setattr(watch.subprocess, "run", lambda *a, **kw: pytest.fail("GitHub called"))
    with pytest.raises(RuntimeError, match="no version"):
        watch.check(watch.REPOSITORY, "4.6.4")


def test_current_version_does_not_call_github(monkeypatch):
    monkeypatch.setattr(watch, "scrape_version", lambda *a: ("4.6.4", "google_play"))
    monkeypatch.setattr(watch.subprocess, "run", lambda *a, **kw: pytest.fail("GitHub called"))
    assert watch.check(watch.REPOSITORY, "4.6.4") == "No newer version detected."


def test_only_target_fork_is_allowed(monkeypatch):
    monkeypatch.setattr(watch, "scrape_version", lambda *a: pytest.fail("Lookup called"))
    with pytest.raises(ValueError, match="restricted"):
        watch.check("its-me-prash/vwgroup-connect-ha", "4.6.4")


def test_issue_creation_and_dry_run(monkeypatch):
    calls = []
    monkeypatch.setattr(watch, "scrape_version", lambda *a: ("4.6.5", "google_play"))
    monkeypatch.setattr(watch, "github_issues", lambda repo: [])

    def run(args, **kwargs):
        calls.append((args, json.loads(kwargs["input"])))
        return subprocess.CompletedProcess(args, 0, '{"html_url":"https://example.test/issue/1"}')

    monkeypatch.setattr(watch.subprocess, "run", run)
    assert "would open" in watch.check(watch.REPOSITORY, "4.6.4", dry_run=True)
    assert calls == []
    assert watch.check(watch.REPOSITORY, "4.6.4").startswith("Opened issue:")
    args, payload = calls[0]
    assert "POST" in args
    assert payload["title"] == "New Volkswagen Android app version: 4.6.5"
    assert watch.MARKER.search(payload["body"]).group(1) == "4.6.5"
    assert watch.PACKAGE in payload["body"]


def test_duplicate_never_posts(monkeypatch):
    monkeypatch.setattr(watch, "scrape_version", lambda *a: ("4.6.5", "google_play"))
    monkeypatch.setattr(watch, "github_issues", lambda repo: [reported("4.6.5")])
    monkeypatch.setattr(watch.subprocess, "run", lambda *a, **kw: pytest.fail("POST called"))
    assert "no duplicate" in watch.check(watch.REPOSITORY, "4.6.4")


def test_issues_are_paginated_and_include_closed(monkeypatch):
    def run(args, **kwargs):
        assert "--paginate" in args and "--slurp" not in args
        assert any("state=all" in arg for arg in args)
        assert args[-1] == ".[] | @json"
        return subprocess.CompletedProcess(
            args, 0, "\n".join(json.dumps(reported(v)) for v in ("4.6.5", "4.7.0")),
        )

    monkeypatch.setattr(watch.subprocess, "run", run)
    assert len(watch.github_issues(watch.REPOSITORY)) == 2
