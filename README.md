# Excalidraw Diagram Skill

A coding agent skill that generates beautiful and practical Excalidraw diagrams from natural language descriptions. Not just boxes-and-arrows - diagrams that **argue visually**.

Compatible with any coding agent that supports skills. For agents that read from `.claude/skills/` (like [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [OpenCode](https://github.com/nicepkg/OpenCode)), just drop it in and go.

## What Makes This Different

- **Diagrams that argue, not display.** Every shape/group of shapes mirrors the concept it represents — fan-outs for one-to-many, timelines for sequences, convergence for aggregation. No uniform card grids.
- **Evidence artifacts.** As an example, technical diagrams include real code snippets and actual JSON payloads.
- **Built-in visual validation.** A fully offline render pipeline (cairosvg, no browser, no network) lets the agent see its own output, catch layout issues (overlapping text, misaligned arrows, unbalanced spacing), and fix them in a loop before delivering. Output is a `.excalidraw.png` with the editable scene embedded — drop it back into excalidraw.com and keep editing.
- **Brand-customizable.** All colors and brand styles live in a single file (`references/color-palette.md`). Swap it out and every diagram follows your palette.

## Installation

Clone or download this repo, then copy it into your project's `.claude/skills/` directory:

```bash
git clone https://github.com/coleam00/excalidraw-diagram-skill.git
cp -r excalidraw-diagram-skill .claude/skills/excalidraw-diagram
```

## Setup

No setup needed. The renderer is a PEP 723 uv-script: dependencies are declared inline and resolved into uv's cache on first invocation. You need `uv` on PATH; that's it. No `uv sync`, no browser, no `npm`.

## Usage

Ask your coding agent to create a diagram:

> "Create an Excalidraw diagram showing how the AG-UI protocol streams events from an AI agent to a frontend UI"

The skill handles the rest — concept mapping, layout, JSON generation, rendering, and visual validation.

## Customize Colors

Edit `references/color-palette.md` to match your brand. Everything else in the skill is universal design methodology.

## File Structure

```
excalidraw-diagram/
  SKILL.md                          # Design methodology + workflow
  references/
    color-palette.md                # Brand colors (edit this to customize)
    element-templates.md            # JSON templates for each element type
    json-schema.md                  # Excalidraw JSON format reference
    render_offline.py               # PEP 723 uv-script: .excalidraw -> PNG with scene embed
    extract_scene.py                # stdlib script: recover editable scene JSON from a .excalidraw.png
  tests/                            # pytest suite for the two scripts
  pyproject.toml                    # dev deps (pytest, cairosvg) + ruff config
  .pre-commit-config.yaml           # ruff lint + format
  .github/workflows/ci.yml          # runs the tests and lint on push/PR
```

## Development

The scripts are covered by a pytest suite. `cairosvg` needs the system cairo
library (`libcairo2` on Debian/Ubuntu, usually already present elsewhere).

```bash
uv run --group dev pytest        # run the tests
pre-commit install               # enable the ruff hook locally
pre-commit run --all-files       # lint + format everything
```
