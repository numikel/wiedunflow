## CodeGuide ${{ github.ref_name }}

Self-contained HTML tutorials from local Git repositories. Offline-first, BYOK (Anthropic / OpenAI / Ollama), no telemetry.

### Install

Install directly from this release tag:

```bash
uv pip install git+https://github.com/numikel/code-guide@${{ github.ref_name }}
```

Or download the `.whl` from the assets below and install offline:

```bash
uv pip install codeguide-X.Y.Z-py3-none-any.whl
```

### Usage

```bash
codeguide /path/to/your/repo
```

This generates a `tutorial.html` in your current directory. Open it in any browser — no server required.

### What's new

<!-- GitHub auto-generates release notes from merged PR titles below this marker -->
