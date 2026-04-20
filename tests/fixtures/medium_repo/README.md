# medium_repo fixture

Synthetic ~20-file Python project used by Sprint 2 integration tests to
exercise the real tree-sitter parser, Jedi resolver, and networkx ranker
on a graph with:

- cross-module calls (`cli → pkg.services → pkg.repositories`)
- class methods calling helper functions (`UserService.register → validate_email`)
- utility layer consumed by both `pkg` and `cli`
- no cycles, no dynamic imports — Jedi should hit ≥50% resolution

This fixture is NOT executed as code — it is parsed as input to CodeGuide.
