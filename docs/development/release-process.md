# Release Process

MediaMasterr uses GitHub Actions as the canonical release report. A release is only trustworthy when validation, Docker publication, and runtime identity all agree on the same commit.

## Before a Release

- Confirm the application metadata, workflow metadata, and published image all point at the same commit SHA.
- Validate the repo with the backend, frontend, docs, and quality checks.
- Confirm the Docker workflow summary includes the published digest and both tags.

## Release Sequence

1. Push the release-ready commit to `main`.
2. Wait for the Docker workflow to finish and verify the run summary.
3. Confirm `latest` and the full commit SHA both exist in GHCR.
4. Open the About page from the running build and confirm the commit SHA and Docker digest match the published image.

## Versioning Notes

- `pyproject.toml` remains the packaging version source.
- `backend/core/__version__.py` remains the runtime application version source.
- `/api/info/version` is the runtime identity endpoint used by the About page.
- The Docker workflow summary is the release record of truth for published tags and digest.

## After the Release

- Check the GitHub Actions run URL for the build summary.
- Confirm Dockge can pull the new `latest` tag or pin the full SHA tag.
- Update deployment notes if the image or startup contract changes.

## Related Pages

- [Changelog](../reference/changelog.md)
- [API Reference](../reference/api.md)
- [Contributing](contributing.md)
