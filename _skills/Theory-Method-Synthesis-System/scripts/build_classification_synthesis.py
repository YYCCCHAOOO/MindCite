from __future__ import annotations

import argparse
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

from mindcite_config import load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
NOTES_DIR = CONFIG.notes_papers_dir
OUTPUT_DIR = ROOT / "notes" / "classification_synthesis"
TAXONOMY_PATH = CONFIG.taxonomy_path
INDEX_PAGE_NAME = "分类综述入口.md"

DIMENSION_NAMES = {
    "theory": "理论",
    "method": "方法",
    "topic": "主题",
}

TAG_FIELDS_BY_DIMENSION = {
    "theory": ["theory_family_tags", "theory_tags", "theory_sub_tags"],
    "method": ["method_family_tags", "method_model_tags", "method_combo_tags", "method_tags"],
    "topic": ["topic_family_tags", "topic_tags"],
}

LIST_FIELDS = {
    "aliases",
    "tags",
    "publication_tags",
    "journal_rank_tags",
    "elite_journal_tags",
    "zotero_collections",
    "theory_family_tags",
    "theory_tags",
    "theory_sub_tags",
    "method_family_tags",
    "method_model_tags",
    "method_combo_tags",
    "method_tags",
    "topic_family_tags",
    "topic_tags",
    "classification_audit",
}


def today_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def yaml_scalar(value: Any) -> str:
    if value is None:
        value = ""
    return json.dumps(str(value), ensure_ascii=False)


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def compact(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def md_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def safe_path_part(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", str(text)).strip(" ._")
    return cleaned or "未归类"


def parse_scalar(value: str) -> Any:
    raw = value.strip()
    if not raw:
        return ""
    if raw == "[]":
        return []
    try:
        return json.loads(raw)
    except Exception:
        return raw.strip('"').strip("'")


def split_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in parts[1].splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            if not isinstance(parsed.get(current_key), list):
                parsed[current_key] = []
            parsed[current_key].append(parse_scalar(line[4:]))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value == "[]":
                parsed[key] = []
            elif not value:
                parsed[key] = [] if key in LIST_FIELDS else ""
            else:
                parsed[key] = parse_scalar(value)
    return parsed, parts[2]


def clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        return [value.strip()]
    if isinstance(value, list):
        return unique([str(item).strip() for item in value if str(item).strip()])
    return []


def note_link(path: Path, title: str) -> str:
    stem = path.stem.replace("[", "(").replace("]", ")")
    alias = str(title or path.stem).replace("[", "(").replace("]", ")").replace("|", "-")
    return f"[[{stem}|{alias}]]"


def load_taxonomy() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    if not TAXONOMY_PATH.exists():
        return {}, {}
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8-sig"))
    label_dimension: dict[str, str] = {}
    label_entry: dict[str, dict[str, Any]] = {}
    for dimension, entries in (data.get("dimensions") or {}).items():
        for entry in entries or []:
            label = str(entry.get("label") or "").strip()
            if label:
                label_dimension[label] = dimension
                label_entry[label] = entry | {"dimension": dimension}
    return label_dimension, label_entry


def infer_dimension(label: str, label_dimension: dict[str, str]) -> str:
    if label in label_dimension:
        return label_dimension[label]
    lowered = label.lower()
    if any(term in lowered for term in ["garch", "midas", "var", "covar", "copula", "ardl", "panel", "面板", "方法", "模型"]):
        return "method"
    if any(term in label for term in ["理论", "传染", "周期", "避险", "货币国际化"]):
        return "theory"
    return "topic"


def output_path_for_label(output_root: Path, label: str, dimension: str, entry: dict[str, Any] | None) -> Path:
    parts = [DIMENSION_NAMES.get(dimension, "其他")]
    if entry:
        level = str(entry.get("level") or "")
        parent = entry.get("parent")
        parents = clean_list(entry.get("parents"))
        if dimension == "method" and level == "combo":
            parts.append("组合模型")
            if parents:
                parts.append(" + ".join(parents))
        elif parent:
            parts.append(str(parent))
        elif parents:
            parts.append(" + ".join(parents))
        elif level:
            parts.append(level)
    else:
        parts.append("未入词表")

    folder = output_root
    for part in parts:
        folder = folder / safe_path_part(part)
    return folder / f"{safe_path_part(label)}.md"


def field_match(label: str, fm: dict[str, Any], dimension: str) -> bool:
    fields = TAG_FIELDS_BY_DIMENSION.get(dimension, [])
    return any(label in clean_list(fm.get(field)) for field in fields)


def fallback_text_match(label: str, fm: dict[str, Any], path: Path) -> bool:
    haystack = " ".join(
        str(fm.get(field, ""))
        for field in [
            "title",
            "theme",
            "methodology",
            "theory",
            "key_finding",
            "primary_collection",
        ]
    )
    return label.lower() in (haystack + " " + path.name).lower()


def extract_section(body: str, heading_names: list[str]) -> str:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s*(.+?)\s*$", line)
        if not match:
            continue
        level = len(match.group(1))
        heading = match.group(2).strip()
        if not any(name in heading for name in heading_names):
            continue
        collected: list[str] = []
        for next_line in lines[i + 1 :]:
            next_match = re.match(r"^(#{2,6})\s+", next_line)
            if next_match and len(next_match.group(1)) <= level:
                break
            collected.append(next_line)
        return "\n".join(collected).strip()
    return ""


def normalize_markdown_block(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return "当前笔记没有可抽取的完整发现段落。"
    lines = [line.rstrip() for line in cleaned.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def full_key_finding(fm: dict[str, Any], body: str) -> str:
    section = extract_section(body, ["研究结论", "主要结论", "研究发现", "主要发现", "核心发现"])
    if section:
        return normalize_markdown_block(section)
    return normalize_markdown_block(str(fm.get("key_finding") or ""))


def scan_notes(label: str, dimension: str, limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        fm, body = split_frontmatter(path)
        matched_by = "tag"
        if not field_match(label, fm, dimension):
            if not fallback_text_match(label, fm, path):
                continue
            matched_by = "text"
        row = {
            "path": path,
            "link": note_link(path, str(fm.get("title") or path.stem)),
            "title": str(fm.get("title") or path.stem),
            "year": str(fm.get("year") or ""),
            "publication_title": str(fm.get("publication_title") or fm.get("source") or ""),
            "publication_tags": clean_list(fm.get("publication_tags")),
            "journal_rank_tags": clean_list(fm.get("journal_rank_tags")),
            "elite_journal_tags": clean_list(fm.get("elite_journal_tags")),
            "impact_factor": fm.get("impact_factor") or "",
            "theory_family_tags": clean_list(fm.get("theory_family_tags")),
            "theory_tags": clean_list(fm.get("theory_tags")),
            "theory_sub_tags": clean_list(fm.get("theory_sub_tags")),
            "method_family_tags": clean_list(fm.get("method_family_tags")),
            "method_model_tags": clean_list(fm.get("method_model_tags")),
            "method_combo_tags": clean_list(fm.get("method_combo_tags")),
            "topic_family_tags": clean_list(fm.get("topic_family_tags")),
            "topic_tags": clean_list(fm.get("topic_tags")),
            "theme": str(fm.get("theme") or ""),
            "methodology": str(fm.get("methodology") or ""),
            "theory": str(fm.get("theory") or ""),
            "key_finding": str(fm.get("key_finding") or ""),
            "full_key_finding": full_key_finding(fm, body),
            "relevance": str(fm.get("relevance") or ""),
            "primary_collection": str(fm.get("primary_collection") or ""),
            "matched_by": matched_by,
        }
        matches.append(row)
        if len(matches) >= limit:
            break
    return matches


def quality_score(row: dict[str, Any]) -> tuple[int, float, str]:
    tags = set(row.get("publication_tags") or [])
    score = 0
    if "FT50" in tags:
        score += 6
    if "UTD24" in tags:
        score += 5
    if "JCR Q1" in tags:
        score += 4
    if any("1区" in tag for tag in tags):
        score += 3
    if "JCR Q2" in tags:
        score += 2
    try:
        impact = float(row.get("impact_factor") or 0)
    except ValueError:
        impact = 0.0
    return (score, impact, row.get("year") or "")


def top_counts(rows: list[dict[str, Any]], field: str, limit: int = 12) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(row.get(field) or [])
    return counter.most_common(limit)


def year_buckets(rows: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {"1999及以前": 0, "2000-2009": 0, "2010-2019": 0, "2020以后": 0, "未知": 0}
    for row in rows:
        try:
            year = int(str(row.get("year") or "")[:4])
        except ValueError:
            buckets["未知"] += 1
            continue
        if year <= 1999:
            buckets["1999及以前"] += 1
        elif year <= 2009:
            buckets["2000-2009"] += 1
        elif year <= 2019:
            buckets["2010-2019"] += 1
        else:
            buckets["2020以后"] += 1
    return buckets


def bullet_counts(items: list[tuple[str, int]]) -> str:
    if not items:
        return "- 当前匹配文献中没有形成稳定共现标签。"
    return "\n".join(f"- `{label}`：{count} 篇" for label, count in items)


def top_labels_text(items: list[tuple[str, int]], limit: int = 4) -> str:
    labels = [label for label, _ in items[:limit]]
    return "、".join(labels) if labels else "暂未形成稳定标签"


def contribution_sentence(label: str, dimension: str, row: dict[str, Any]) -> str:
    theme = compact(row.get("theme"), 80) or "该文的研究问题"
    methods = row.get("method_combo_tags") or row.get("method_model_tags") or row.get("method_family_tags") or []
    topics = row.get("topic_tags") or []
    theories = row.get("theory_tags") or []
    method_text = "、".join(methods[:3]) if methods else compact(row.get("methodology"), 60)
    topic_text = "、".join(topics[:3]) if topics else theme
    theory_text = "、".join(theories[:3]) if theories else label

    if dimension == "method":
        return f"展示了 `{label}` 在“{theme}”中的应用，并与 {topic_text} 等主题相连。"
    if dimension == "theory":
        return f"为 `{label}` 提供了关于“{topic_text}”的理论或经验证据，常见方法线索是 {method_text or '待补'}。"
    return f"为 `{label}` 这个主题提供了关于“{theme}”的核心结论，并连接到 {theory_text} / {method_text or '待补'}。"


def render_core_literature(label: str, dimension: str, rows: list[dict[str, Any]], max_items: int = 12) -> str:
    if not rows:
        return "当前 Vault 中没有匹配到已精读笔记。"
    ranked = sorted(rows, key=quality_score, reverse=True)[:max_items]
    sections: list[str] = []
    for index, row in enumerate(ranked, start=1):
        tags = ", ".join(row.get("publication_tags") or []) or "暂无期刊等级"
        methods = ", ".join(row.get("method_combo_tags") or row.get("method_model_tags") or row.get("method_family_tags") or [])
        finding = normalize_markdown_block(row.get("full_key_finding"))
        sections.append(
            f"### {index}. {row['link']} ({row.get('year') or '未知年份'})\n\n"
            f"**期刊/等级**：{md_escape(row.get('publication_title')) or '未知期刊'}；{md_escape(tags)}\n\n"
            f"**研究主题**：{compact(row.get('theme'), 220) or '当前笔记未填写'}\n\n"
            f"**方法/模型**：{compact(methods or row.get('methodology'), 220) or '当前笔记未填写'}\n\n"
            f"**关键发现**\n\n{finding}\n\n"
            f"**对 `{label}` 的贡献**：{contribution_sentence(label, dimension, row)}"
        )
    return "\n\n".join(sections)


def render_timeline(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 当前 Vault 证据不足。"
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        year = row.get("year") or "未知年份"
        grouped[str(year)].append(row)
    lines: list[str] = []
    for year in sorted(grouped, key=lambda y: (y == "未知年份", y)):
        sample = sorted(grouped[year], key=quality_score, reverse=True)[:3]
        refs = "；".join(row["link"] for row in sample)
        lines.append(f"- **{year}**：{len(grouped[year])} 篇。代表笔记：{refs}")
    return "\n".join(lines)


def render_all_links(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 当前没有可链接文献。"
    lines = []
    for row in sorted(rows, key=lambda r: (r.get("year") or "9999", r.get("title") or "")):
        lines.append(f"- {row['link']} | {row.get('year') or '未知年份'} | {compact(row.get('publication_title'), 80)}")
    return "\n".join(lines)


def taxonomy_description(label: str, entry: dict[str, Any] | None) -> str:
    if not entry:
        return "当前标签不在 taxonomy 中，按笔记文本匹配生成测试综述。"
    description = str(entry.get("description") or "").strip()
    parts = [
        f"维度：`{DIMENSION_NAMES.get(str(entry.get('dimension')), entry.get('dimension'))}`",
        f"层级：`{entry.get('level')}`",
    ]
    if entry.get("parent"):
        parts.append(f"父级：`{entry.get('parent')}`")
    if entry.get("parents"):
        parts.append(f"父级：`{', '.join(entry.get('parents') or [])}`")
    if entry.get("combines"):
        parts.append(f"组合：`{', '.join(entry.get('combines') or [])}`")
    if description:
        parts.append(f"定义：{description}")
    return "；".join(parts)


def render_opening_summary(label: str, dimension: str, rows: list[dict[str, Any]], entry: dict[str, Any] | None) -> str:
    description = str((entry or {}).get("description") or "").strip()
    methods = top_counts(rows, "method_model_tags", 5)
    method_families = top_counts(rows, "method_family_tags", 5)
    method_combos = top_counts(rows, "method_combo_tags", 5)
    theories = top_counts(rows, "theory_tags", 5)
    topics = top_counts(rows, "topic_tags", 5)

    if not description:
        description = f"`{label}` 是当前 Vault 中由标签或笔记文本识别出的一个分类入口。"
    if dimension == "method":
        focus = f"它在当前文献中主要服务于 {top_labels_text(topics)} 等主题，常与 {top_labels_text(method_combos or methods or method_families)} 搭配。"
    elif dimension == "theory":
        focus = f"当前文献主要把它用于解释 {top_labels_text(topics)} 等问题，常见实证工具包括 {top_labels_text(methods or method_families)}。"
    else:
        focus = f"当前文献围绕这一主题连接了 {top_labels_text(theories)} 等理论，并常用 {top_labels_text(methods or method_families)} 做实证识别。"
    return (
        f"从当前 Vault 的 `{len(rows)}` 篇匹配笔记看，{description}"
        f"{focus} 这页的阅读顺序建议是：先看下面的核心文献入口和完整关键发现，再按发展脉络、方法搭配和全部匹配文献继续扩展。"
    )


def render_statistics(rows: list[dict[str, Any]]) -> str:
    buckets = year_buckets(rows)
    publication_count = sum(1 for row in rows if row.get("publication_tags"))
    exact_count = sum(1 for row in rows if row.get("matched_by") == "tag")
    return f"""- **匹配数量**：`{len(rows)}` 篇；其中 `{exact_count}` 篇来自 frontmatter 标签精确匹配。
- **期刊等级覆盖**：`{publication_count}` 篇带有 `publication_tags`。
- **时间分布**：1999及以前 `{buckets['1999及以前']}`；2000-2009 `{buckets['2000-2009']}`；2010-2019 `{buckets['2010-2019']}`；2020以后 `{buckets['2020以后']}`；未知 `{buckets['未知']}`。

**共现理论标签**
{bullet_counts(top_counts(rows, "theory_tags"))}

**共现方法族**
{bullet_counts(top_counts(rows, "method_family_tags"))}

**共现方法模型**
{bullet_counts(top_counts(rows, "method_model_tags"))}

**共现组合模型**
{bullet_counts(top_counts(rows, "method_combo_tags"))}

**共现主题标签**
{bullet_counts(top_counts(rows, "topic_tags"))}

**期刊等级信号**
{bullet_counts(top_counts(rows, "publication_tags"))}"""


def render(label: str, dimension: str, rows: list[dict[str, Any]], entry: dict[str, Any] | None) -> str:
    output_tags = {
        "theory": "theory-synthesis",
        "method": "method-synthesis",
        "topic": "topic-synthesis",
    }
    exact_count = sum(1 for row in rows if row.get("matched_by") == "tag")

    return f"""---
title: {yaml_scalar(label)}
aliases: []
tags:
  - classification-synthesis
  - literature-map
  - {output_tags.get(dimension, "classification-synthesis")}
created: {yaml_scalar(today_str())}
generated_at: {yaml_scalar(now_iso())}
classification_label: {yaml_scalar(label)}
classification_type: {yaml_scalar(dimension)}
source_scope: "仅基于 MindCite 已有精读 notes"
matched_notes: {len(rows)}
exact_tag_matches: {exact_count}
review_status: "draft"
---

# {label}

{render_opening_summary(label, dimension, rows, entry)}

> 本综述只基于当前 Vault 中已经生成的精读 notes，不补外部知识。文献标题均为 Obsidian 交叉引用，点击即可跳转到单篇精读笔记。

## 核心文献入口

{render_core_literature(label, dimension, rows)}

## 名称核验

- **当前名称**：`{label}`
- **标签说明**：{taxonomy_description(label, entry)}
- **后续确认**：如果要写正式论文综述，还需要补充外部高被引、奠基文献和标准英文名称核验。

## 发展脉络

{render_timeline(rows)}

## 方法搭配

**方法族搭配**
{bullet_counts(top_counts(rows, "method_family_tags"))}

**具体模型搭配**
{bullet_counts(top_counts(rows, "method_model_tags"))}

**组合模型搭配**
{bullet_counts(top_counts(rows, "method_combo_tags"))}

## 缺口文献

- 当前稿件没有外部检索，因此不能断言“核心文献已经齐全”。
- 需要补检索：`{label}` + `review`、`survey`、`seminal paper`、`highly cited`。
- 对期刊等级缺失的文献，可在 [[高质量期刊|高质量期刊视图]] 的“缺期刊标签”中继续处理。

## 对我研究的启发

- 可以把本页作为 `{label}` 的研究入口：先看核心文献入口，再按方法/主题共现扩展。
- 如果要写论文综述，优先打开 FT50、UTD24、JCR Q1 或中科院 1 区文献的精读笔记。
- 如果要找方法路线，优先看“方法搭配”中的高频模型，再跳转到对应单篇。
- 如果要继续写作文献综述，可先把本页压缩成“问题-代表文献-方法-结论-启发”的结构。

## 统计概览

{render_statistics(rows)}

## 全部匹配文献

{render_all_links(rows)}
"""


def write_index_page(output_root: Path) -> Path:
    path = output_root / INDEX_PAGE_NAME
    pages = [
        item
        for item in output_root.rglob("*.md")
        if item.name != INDEX_PAGE_NAME and not item.name.startswith("classification_synthesis_")
    ]
    grouped: dict[str, list[Path]] = defaultdict(list)
    for page in pages:
        try:
            top = page.relative_to(output_root).parts[0]
        except Exception:
            top = "其他"
        grouped[top].append(page)

    lines = [
        "# 分类综述入口",
        "",
        "这里收集理论、方法和主题分类综述。每篇综述里的论文标题都使用 Obsidian 双链，可以直接跳转到单篇精读笔记。",
        "",
    ]
    for group in ["理论", "方法", "主题", "其他"]:
        items = sorted(grouped.get(group, []), key=lambda p: str(p))
        if not items:
            continue
        lines.extend([f"## {group}", ""])
        for item in items:
            rel_folder = " / ".join(item.relative_to(output_root).parts[:-1])
            lines.append(f"- [[{item.stem}|{item.stem}]] — `{rel_folder}`")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def build(label: str, limit: int = 80, output_root: Path = OUTPUT_DIR) -> dict[str, Any]:
    label_dimension, label_entry = load_taxonomy()
    dimension = infer_dimension(label, label_dimension)
    entry = label_entry.get(label)
    rows = scan_notes(label, dimension, limit)
    output_path = output_path_for_label(output_root, label, dimension, entry)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(label, dimension, rows, entry), encoding="utf-8")
    index_path = write_index_page(output_root)
    return {
        "ok": True,
        "label": label,
        "dimension": dimension,
        "output_path": str(output_path),
        "index_path": str(index_path),
        "matched_notes": len(rows),
        "exact_tag_matches": sum(1 for row in rows if row.get("matched_by") == "tag"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a classification synthesis draft from existing notes.")
    parser.add_argument("--label", required=True, help="Theory, method, or topic label to synthesize.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum matching notes.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    print(json.dumps(build(args.label, args.limit, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
