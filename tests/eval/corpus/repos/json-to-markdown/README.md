# json-to-markdown

A tiny single-file Python CLI that converts arbitrary JSON content into a readable
Markdown document — used as one of WiedunFlow's evaluation corpus repos because it
exercises recursion, multiple rendering branches, and a small but real CLI surface.

## What it does

Reads JSON from a file or an inline string, walks the tree recursively, and emits
Markdown using format-aware rules:

- **Scalars** (strings, numbers, booleans, null) are escaped and inlined.
- **Dictionaries with simple values** become bold key/value pairs.
- **Dictionaries with nested structures** become Markdown tables.
- **Lists of dictionaries** become Markdown tables with the union of keys as columns.
- **Nested objects** are emitted as `## Subheading` sections (recursive).

The output goes to a file (auto-appending `.md`) or to stdout.

## Usage

```bash
python main.py --from-file example.json --to-file output.md
python main.py --from-content '{"key":"value"}' --to-file out.md
python main.py --from-file example.json   # prints to stdout
```

## Project layout

Everything lives in `main.py`:

- `load_json_file(file_path)` / `load_json_content(content)` — read input.
- `convert_json_to_markdown(json_data)` — top-level transformation entry point.
- `build_section_markdown(key, value, level)` — recursive section builder.
- `format_value(v)`, `is_simple(v)` — formatting predicates.
- `dict_to_bold_pairs`, `dict_to_table`, `list_of_dicts_to_table` — rendering helpers.
- `write_markdown_file(content, file_path)` — writes the result to disk.

## Why this repo is in the eval corpus

It is small enough to inspect by hand, has zero dependencies, exercises recursion
and a couple of cyclic helper relationships, and the expected lesson plan is
unambiguous — making it a good acceptance signal for tutorial-quality changes.
