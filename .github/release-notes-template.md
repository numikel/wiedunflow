## WiedunFlow ${RELEASE_TAG}

Self-contained HTML tutorials from local Git repositories. Offline-first, BYOK (Anthropic / OpenAI / Ollama), no telemetry.

### Install

Install directly from this release tag:

```bash
uv pip install git+https://github.com/numikel/wiedunflow@${RELEASE_TAG}
```

Or download the `.whl` from the assets below and install offline:

```bash
uv pip install wiedunflow-${RELEASE_VERSION}-py3-none-any.whl
```

### Usage

```bash
wiedunflow /path/to/your/repo
```

This generates a `wiedunflow-<repo>.html` next to the source repo. Open it in any browser — no server required.

### What's new

<!-- GitHub auto-generates release notes from merged PR titles below this marker -->
<!-- See CHANGELOG.md for the curated changelog. -->
