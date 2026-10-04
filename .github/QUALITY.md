# Fork CI checks (gszigethy/vwgroup-connect-ha)

This fork is upstream `main` plus pending upstream pull requests and a thin CI
layer. Upstream workflows are kept unchanged. `ci.yml` remains the test gate on
`main`: pytest with at least 75 % coverage, strict mypy, Ruff, hassfest and HACS.
`release.yml` builds the release from a `v*` tag.

The fork adds `quality.yml`, the same baseline used in the owner's other
repositories. It runs on every push and pull request with read-only permissions:

- Python syntax and Ruff defect checks (E9, F63, F7, F82) are blocking. Ruff
  compares findings by file, rule and message against the pull request base,
  or the previous commit on a push, ignoring line shifts. Existing findings stay
  visible; new ones fail CI.
- Mypy with missing imports skipped is a non-blocking report. The strict mypy
  gate is in `ci.yml`.
- On branches other than `main` it also runs the test suite with the same
  dependencies and coverage threshold as `ci.yml`, and uploads `coverage.xml`.

Action references are pinned to commits and kept current by Dependabot.

## Analyzer dependencies

`.github/ci/requirements.in` lists the analyzer versions. `requirements.txt`
pins every dependency with its artifact hashes for Python 3.13, and CI installs
wheels only. To update it:

```sh
uv pip compile --python-version 3.13 --generate-hashes --only-binary :all: \
  --no-emit-index-url .github/ci/requirements.in -o .github/ci/requirements.txt
```

## SonarCloud

Project `gszigethy_vwgroup-connect-ha` uses SonarCloud automatic analysis.
`.sonarcloud.properties` sets the source, test and Python version scope.
Automatic analysis does not import coverage; the coverage report is the
`python-coverage` artifact of `quality.yml`.

## Keeping upstream merges easy

Changes meant for upstream are developed on branches from upstream `main` and
offered as upstream pull requests. Only the files named here, the README note
and fork release commits differ from upstream on the fork's `main`.
