# Attribution Review

Review date: 2026-05-07

This note records a practical open-source attribution review for MindCite. It is an engineering and documentation review, not legal advice.

## Reviewed Upstream Repositories

- `https://github.com/cheneternity/Zotero-Analytical-Workflow-Skills`
- `https://github.com/cheneternity/Research-Vault-Literature-Retrieval`

Both repositories are public and related to Codex skills for Zotero, Obsidian, and local literature retrieval. At review time, neither repository contained a root `LICENSE`, `NOTICE`, or `COPYING` file.

## Similarity Assessment

| Area | Upstream idea | MindCite implementation | Risk |
| --- | --- | --- | --- |
| Zotero workflow | Splits work into batch management, data extraction, and analytical writing. | Uses a separate configurable indexing and reading pipeline with Python scripts, JSONL status, `.env`, schemas, demo data, and safety checks. | Low to medium: conceptual overlap, no copied code found. |
| Vault Q&A | Answers from existing local Vault notes and avoids external unsupported claims. | `Notes-QA-System` restricts answers to `notes/zotero_reading` and generated index data. | Low to medium: shared principle, different wording and scope. |
| Skill framework | Uses Codex `SKILL.md` files to describe task behavior. | Uses MindCite-specific skills plus scripts, config, contracts, and release checks. | Low: common Codex skill format. |
| Templates and text | Upstream includes Markdown skill instructions and a reading-note template. | MindCite does not vendor upstream templates or files. | Low if this remains true; high if upstream text/templates are copied without permission. |
| License compliance | No license found upstream at review time. | MindCite is MIT licensed but treats upstream as inspiration only. | Medium residual risk because attribution alone is not a license grant. |

## Text/Code Copy Check

The public MindCite repository was compared against the cloned upstream Markdown/YAML files. The scan found no meaningful long-line copying and no vendored upstream source files. A generic heading that overlapped with upstream phrasing was renamed to reduce confusion.

This does not prove legal non-infringement; it only supports the practical conclusion that the current public repository is closer to an independently implemented, inspired-by project than a derivative copy.

## Recommended GitHub Practice

- Keep `LICENSE` for MindCite's own license.
- Keep `NOTICE.md` for attribution and provenance notes.
- Do not copy upstream Markdown, templates, or files unless the upstream author grants permission or adds a compatible license.
- If exact upstream content is ever used, record the upstream commit, author, license/permission, and modified files.
- Consider opening a friendly issue with the upstream author asking whether they are willing to add a license or confirm permission for inspiration/attribution.

## Current Decision

MindCite can keep the current public implementation with explicit acknowledgement. The project should describe the upstream repositories as inspiration, not as bundled dependencies or licensed source components.
