from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from researchvault_config import load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
TAXONOMY_PATH = CONFIG.taxonomy_path
BACKFILL_PREVIEW_PATH = CONFIG.indexes_dir / "note_frontmatter_backfill_preview.jsonl"
PROPOSAL_PATH = CONFIG.indexes_dir / "audited_tag_taxonomy_proposal.json"
CURRENT_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_current.md"
AUDIT_MD_PATH = CONFIG.indexes_dir / "tag_taxonomy_audit.md"
AUDIT_JSON_PATH = CONFIG.indexes_dir / "tag_taxonomy_audit.json"

COUNT_FIELDS = {
    "theory_family_tags": "proposed_theory_family_tags",
    "theory_tags": "proposed_theory_tags",
    "theory_sub_tags": "proposed_theory_sub_tags",
    "method_family_tags": "proposed_method_family_tags",
    "method_model_tags": "proposed_method_model_tags",
    "method_combo_tags": "proposed_method_combo_tags",
    "topic_family_tags": "proposed_topic_family_tags",
    "topic_tags": "proposed_topic_tags",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def md_cell(value: Any, limit: int = 180) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if str(item).strip())
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return text[:limit]


def collect_usage(preview_rows: list[dict[str, Any]]) -> tuple[Counter[str], dict[str, Counter[str]], dict[str, list[dict[str, str]]]]:
    counts: Counter[str] = Counter()
    evidence: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in preview_rows:
        title = str(row.get("title") or "")
        item_key = str(row.get("item_key") or "")
        for preview_field in COUNT_FIELDS.values():
            for label in clean_list(row.get(preview_field)):
                counts[label] += 1
                if len(samples[label]) < 3:
                    samples[label].append(
                        {
                            "item_key": item_key,
                            "title": title,
                            "note_path": str(row.get("note_path") or ""),
                        }
                    )

        matched = row.get("candidate_matched_keywords") or {}
        for labels in matched.values():
            if not isinstance(labels, dict):
                continue
            for label, hits in labels.items():
                evidence[str(label)].update(clean_list(hits))

    return counts, evidence, samples


def current_labels(taxonomy: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for entries in (taxonomy.get("dimensions") or {}).values():
        for entry in entries or []:
            label = str(entry.get("label") or "").strip()
            if label:
                labels.add(label)
    return labels


def proposal_lookup(proposal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for dimension, rows in (proposal.get("dimensions") or {}).items():
        for row in rows or []:
            label = str(row.get("label") or "").strip()
            if label:
                out[label] = row | {"dimension": dimension}
    return out


def audit_suggestion(entry: dict[str, Any], matched_notes: int) -> str:
    level = str(entry.get("level") or "")
    if matched_notes == 0:
        return "待确认：当前 notes 未命中；若是未来研究框架核心概念可保留，否则可删除或暂存。"
    if level in {"family", "theory_family"}:
        return "建议作为父级保留；父级用于组织，不一定直接作为论文细粒度标签。"
    if level == "combo":
        return "建议保留为组合模型；命中文献会同时继承方法族和组成模型。"
    return "可作为自动回填标签；用户只需审核该标签是否值得存在。"


def build_audit_rows(
    taxonomy: dict[str, Any],
    proposal: dict[str, Any],
    counts: Counter[str],
    evidence: dict[str, Counter[str]],
    samples: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    proposal_by_label = proposal_lookup(proposal)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for dimension, entries in (taxonomy.get("dimensions") or {}).items():
        for entry in entries or []:
            label = str(entry.get("label") or "").strip()
            if not label:
                continue
            seen.add(label)
            matched_notes = counts.get(label, 0)
            rows.append(
                {
                    "review_status": "keep",
                    "decision_options": ["keep", "rename", "merge", "split", "retire"],
                    "action": "review_existing_tag",
                    "dimension": dimension,
                    "label": label,
                    "level": entry.get("level") or "",
                    "tag_field": entry.get("tag_field") or "",
                    "parent": entry.get("parent") or "",
                    "parents": clean_list(entry.get("parents")),
                    "combines": clean_list(entry.get("combines")),
                    "target_collection_path": entry.get("target_collection_path") or "",
                    "matched_notes": matched_notes,
                    "top_evidence": evidence.get(label, Counter()).most_common(6),
                    "sample_notes": samples.get(label, []),
                    "suggestion": audit_suggestion(entry, matched_notes),
                    "decision_note": "",
                }
            )

    for label, row in proposal_by_label.items():
        if label in seen:
            continue
        rows.append(
            {
                "review_status": "pending",
                "decision_options": ["add", "rename", "merge", "reject"],
                "action": "candidate_new_tag",
                "dimension": row.get("dimension") or "",
                "label": label,
                "level": "",
                "tag_field": "",
                "parent": row.get("parent") or "",
                "parents": [],
                "combines": [],
                "target_collection_path": "",
                "matched_notes": row.get("matched_note_count") or 0,
                "top_evidence": row.get("top_keywords") or [],
                "sample_notes": row.get("sample_notes") or [],
                "suggestion": "这是候选新标签；只有用户确认后才进入正式 taxonomy。",
                "decision_note": "",
            }
        )

    order = {"theory": 0, "method": 1, "topic": 2}
    rows.sort(key=lambda r: (order.get(r["dimension"], 9), str(r.get("parent") or r.get("parents") or ""), str(r["label"])))
    return rows


def parent_text(entry: dict[str, Any]) -> str:
    parents = clean_list(entry.get("parents"))
    if parents:
        return ", ".join(parents)
    return str(entry.get("parent") or "")


def write_current_md(path: Path, taxonomy: dict[str, Any], counts: Counter[str]) -> None:
    dimensions = taxonomy.get("dimensions") or {}
    lines = [
        "# ResearchVault 当前标签体系",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Taxonomy version: `{taxonomy.get('version', '')}`",
        f"- Schema: `{taxonomy.get('schema_version', '')}`",
        "- 这是用于自动分类和回填的标签体系草案；分类不是文件夹，分类写入 note frontmatter 属性。",
        "- 用户主要审核标签是否值得存在，不逐篇审核标签归属。",
        "",
    ]

    names = {"theory": "理论标签", "method": "方法标签", "topic": "主题标签"}
    for dimension in ["theory", "method", "topic"]:
        lines.extend([f"## {names[dimension]}", ""])
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in dimensions.get(dimension) or []:
            group = parent_text(entry) or "未分组"
            if dimension == "method" and entry.get("level") == "family":
                group = "方法族"
            if dimension == "method" and entry.get("level") == "combo":
                group = "组合模型"
            groups[group].append(entry)
        for group in sorted(groups):
            lines.extend([f"### {group}", ""])
            for entry in groups[group]:
                label = entry.get("label") or ""
                pieces = [
                    f"`{label}`",
                    f"level=`{entry.get('level', '')}`",
                    f"field=`{entry.get('tag_field', '')}`",
                    f"matched_notes=`{counts.get(label, 0)}`",
                ]
                if clean_list(entry.get("combines")):
                    pieces.append(f"combines=`{', '.join(clean_list(entry.get('combines')))}`")
                if entry.get("target_collection_path"):
                    pieces.append(f"zotero=`{entry.get('target_collection_path')}`")
                lines.append("- " + " | ".join(pieces))
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_audit_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# 标签体系审计表",
        "",
        f"- Generated at: `{now_iso()}`",
        "- 审计对象是标签本身，不是单篇论文。",
        "- `matched_notes` 只是说明这个标签在当前 notes 中的覆盖量；覆盖量低不一定删除，关键看它是不是你的理论/方法/主题体系需要的概念。",
        "- 你可以把 `review_status` 改成 `keep`、`rename`、`merge`、`split`、`retire`；对候选新标签也可以写 `add` 或 `reject`。",
        "- 被确认的标签进入正式 taxonomy；后续 AI 可以自动给论文打这些已批准标签。",
        "",
        "| review_status | action | dimension | label | level | parent | combines | matched_notes | top_evidence | suggestion | decision_note |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        top_evidence = "；".join(f"{kw}({n})" for kw, n in (row.get("top_evidence") or [])[:5])
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(row.get("review_status"), 40),
                    md_cell(row.get("action"), 40),
                    md_cell(row.get("dimension"), 24),
                    md_cell(row.get("label"), 80),
                    md_cell(row.get("level"), 40),
                    md_cell(row.get("parents") or row.get("parent"), 100),
                    md_cell(row.get("combines"), 100),
                    md_cell(row.get("matched_notes"), 16),
                    md_cell(top_evidence, 160),
                    md_cell(row.get("suggestion"), 180),
                    md_cell(row.get("decision_note"), 120),
                ]
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    taxonomy = read_json(TAXONOMY_PATH, {})
    proposal = read_json(PROPOSAL_PATH, {})
    preview_rows = read_jsonl(BACKFILL_PREVIEW_PATH)
    counts, evidence, samples = collect_usage(preview_rows)
    audit_rows = build_audit_rows(taxonomy, proposal, counts, evidence, samples)

    write_current_md(CURRENT_MD_PATH, taxonomy, counts)
    write_audit_md(AUDIT_MD_PATH, audit_rows)
    AUDIT_JSON_PATH.write_text(json.dumps(audit_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "current_md": str(CURRENT_MD_PATH),
                "audit_md": str(AUDIT_MD_PATH),
                "audit_json": str(AUDIT_JSON_PATH),
                "taxonomy_tags": len(current_labels(taxonomy)),
                "audit_rows": len(audit_rows),
                "candidate_new_tags": sum(1 for row in audit_rows if row.get("action") == "candidate_new_tag"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

