from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import configured_existing_paths, load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
INDEX_PATH = CONFIG.index_path
STATUS_PATH = CONFIG.status_path
LOG_DIR = CONFIG.logs_dir
NOTES_DIR = CONFIG.notes_dir
DB_PATHS = configured_existing_paths(CONFIG.zotero_db_path, CONFIG.zotero_snapshot_path)
DEFAULT_BATCH_SIZE = 20


INVALID_FILE_CHARS = '<>:"/\\|?*'


@dataclass
class ItemRecord:
    item_key: str
    title: str
    item_type: str
    year: str | None
    doi: str | None
    zotero_item_id: int
    collection_paths: list[str]
    pdf_paths: list[str]
    reading_status: str | None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def sanitize_filename(text: str) -> str:
    out = "".join("_" if ch in INVALID_FILE_CHARS else ch for ch in text.strip())
    out = out.rstrip(" .")
    return out or "_"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def load_status_map() -> dict[str, dict[str, Any]]:
    return {row["item_key"]: row for row in read_jsonl(STATUS_PATH) if row.get("item_key")}


def load_index_items() -> list[ItemRecord]:
    items: list[ItemRecord] = []
    for row in read_jsonl(INDEX_PATH):
        items.append(
            ItemRecord(
                item_key=row["item_key"],
                title=row["title"],
                item_type=row["item_type"],
                year=row.get("year"),
                doi=row.get("doi"),
                zotero_item_id=row["zotero_item_id"],
                collection_paths=row.get("collection_paths") or [],
                pdf_paths=row.get("pdf_paths") or [],
                reading_status=row.get("reading_status"),
            )
        )
    return items


def choose_db() -> Path:
    for path in DB_PATHS:
        if not path.exists():
            continue
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
            conn.execute("select 1")
            conn.close()
            return path
        except sqlite3.Error:
            continue
    raise FileNotFoundError("No readable Zotero database found. Set ZOTERO_DB_PATH in .env.")


def connect_db(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)


def load_metadata(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    cur = conn.cursor()
    item_rows = cur.execute(
        """
        SELECT
            i.itemID,
            i.key,
            MAX(CASE WHEN f.fieldName = 'publicationTitle' THEN v.value END) AS publication_title,
            MAX(CASE WHEN f.fieldName = 'journalAbbreviation' THEN v.value END) AS journal_abbr,
            MAX(CASE WHEN f.fieldName = 'proceedingsTitle' THEN v.value END) AS proceedings_title,
            MAX(CASE WHEN f.fieldName = 'bookTitle' THEN v.value END) AS book_title,
            MAX(CASE WHEN f.fieldName = 'volume' THEN v.value END) AS volume,
            MAX(CASE WHEN f.fieldName = 'issue' THEN v.value END) AS issue,
            MAX(CASE WHEN f.fieldName = 'pages' THEN v.value END) AS pages,
            MAX(CASE WHEN f.fieldName = 'date' THEN v.value END) AS raw_date,
            MAX(CASE WHEN f.fieldName = 'url' THEN v.value END) AS url,
            MAX(CASE WHEN f.fieldName = 'abstractNote' THEN v.value END) AS abstract_note,
            MAX(CASE WHEN f.fieldName = 'DOI' THEN v.value END) AS doi
        FROM items i
        LEFT JOIN itemData d ON d.itemID = i.itemID
        LEFT JOIN fieldsCombined f ON f.fieldID = d.fieldID
        LEFT JOIN itemDataValues v ON v.valueID = d.valueID
        GROUP BY i.itemID, i.key
        """
    ).fetchall()

    creators = defaultdict(list)
    creator_rows = cur.execute(
        """
        SELECT i.key, c.firstName, c.lastName, ic.orderIndex
        FROM itemCreators ic
        JOIN items i ON i.itemID = ic.itemID
        JOIN creators c ON c.creatorID = ic.creatorID
        ORDER BY i.key, ic.orderIndex
        """
    ).fetchall()
    for item_key, first_name, last_name, order_index in creator_rows:
        full = " ".join(part for part in [first_name or "", last_name or ""] if part).strip()
        creators[item_key].append((order_index, full or last_name or first_name or ""))

    out: dict[str, dict[str, Any]] = {}
    for row in item_rows:
        (
            item_id,
            item_key,
            publication_title,
            journal_abbr,
            proceedings_title,
            book_title,
            volume,
            issue,
            pages,
            raw_date,
            url,
            abstract_note,
            doi,
        ) = row
        author_list = [name for _, name in sorted(creators[item_key], key=lambda x: x[0])]
        source = publication_title or proceedings_title or book_title or journal_abbr or ""
        if volume:
            source += f", {volume}"
            if issue:
                source += f"({issue})"
        if pages:
            source += f", {pages}"
        out[item_key] = {
            "item_id": item_id,
            "authors": author_list,
            "source": source.strip(", "),
            "raw_date": raw_date,
            "url": url,
            "abstract_note": abstract_note,
            "doi": doi,
        }
    return out


def extract_text_from_pdf(pdf_path: Path) -> tuple[str, list[str]]:
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text)
    full = "\n\n".join(pages)
    return full, pages


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00a0", " ")
    text = text.replace("a b s t r a c t", "abstract")
    text = text.replace("A B S T R A C T", "ABSTRACT")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def safe_excerpt(text: str, limit: int = 350) -> str:
    text = " ".join(text.split())
    return text[:limit].strip()


def sentence_split(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[\.\?\!])\s+(?=[A-Z0-9])", text)
    return [part.strip() for part in parts if len(part.strip()) > 20]


def is_bad_sentence(sent: str) -> bool:
    lower = sent.lower().strip()
    bad_markers = [
        "downloaded from",
        "all rights reserved",
        "article history",
        "keywords",
        "jel classification",
        "published by",
        "working paper",
        "http://",
        "https://",
        "copyright",
        "oxford bulletin",
        "contents lists available",
        "journal homepage",
        "we would like to thank",
        "we use information technology and tools",
        "earlier version of this paper was presented",
    ]
    if any(marker in lower for marker in bad_markers):
        return True
    if len(sent) < 40:
        return True
    if re.match(r"^[a-z\W]", sent):
        return True
    if sent.count(",") > 6 and re.search(r"\(\d{4}\)", sent):
        return True
    if re.search(r"\b[A-Z][a-z]+,\s+[A-Z]\.", sent) and re.search(r"\(\d{4}\)", sent):
        return True
    return False


def clean_sentences(text: str) -> list[str]:
    return [sent for sent in sentence_split(text) if not is_bad_sentence(sent)]


def find_section(text: str, headings: list[str], max_chars: int = 5000) -> str:
    lower = text.lower()
    best_start = -1
    best_heading = None
    for heading in headings:
        pattern = re.compile(rf"(?:^|\n)\s*(?:\d+\.\s*)?{re.escape(heading.lower())}\s*(?:\n|$)")
        match = pattern.search(lower)
        if match:
            best_start = match.end()
            best_heading = heading
            break
    if best_start == -1:
        return ""
    tail = text[best_start : best_start + max_chars]
    next_heading = re.search(r"\n\s*(?:\d+\.\s*)?[A-Z][A-Za-z0-9 ,\-\(\)/]{2,80}\n", tail)
    if next_heading:
        tail = tail[: next_heading.start()]
    return tail.strip()


def find_abstract(text: str) -> str:
    lower = text.lower()
    for pattern in [r"abstract\s*", r"a\s*b\s*s\s*t\s*r\s*a\s*c\s*t\s*"]:
        match = re.search(pattern, lower)
        if match:
            snippet = text[match.end() : match.end() + 2500]
            end_markers = [
                re.search(r"\n\s*(?:1[\.\s]|i[\.\s])\s*introduction", snippet, flags=re.I),
                re.search(r"\n\s*©", snippet),
                re.search(r"\n\s*keywords?\b", snippet, flags=re.I),
            ]
            valid = [m.start() for m in end_markers if m]
            if valid:
                snippet = snippet[: min(valid)]
            cleaned = safe_excerpt(snippet, 1400)
            if len(cleaned) > 120:
                return cleaned
    candidates = [find_section(text, ["abstract"], 4000), find_section(text, ["summary"], 3500)]
    for candidate in candidates:
        cleaned = safe_excerpt(candidate, 1500)
        if len(cleaned) > 120:
            return cleaned
    lower = text.lower()
    idx = lower.find("abstract")
    if idx != -1:
        snippet = text[idx + 8 : idx + 1600]
        return safe_excerpt(snippet, 1200)
    return ""


def find_conclusion(text: str) -> str:
    text_no_refs = re.split(r"\n\s*references\s*\n", text, flags=re.I)[0]
    for heading in ["conclusion", "conclusions", "concluding remarks", "summary and conclusion"]:
        section = find_section(text_no_refs, [heading], 5000)
        if len(section) > 120:
            return safe_excerpt(section, 2000)
    tail = text_no_refs[-5000:]
    return safe_excerpt(tail, 2000)


def find_method_section(text: str) -> str:
    for heading in ["methodology", "methods", "empirical methodology", "model", "data and methodology", "method"]:
        section = find_section(text, [heading], 5000)
        if len(section) > 120:
            return safe_excerpt(section, 2200)
    return ""


def first_matching_sentence(texts: list[str], keywords: list[str]) -> str:
    for text in texts:
        for sent in clean_sentences(text):
            lower = sent.lower()
            if all(keyword in lower for keyword in keywords):
                return sent
    return ""


def best_sentence(texts: list[str], any_keywords: list[str]) -> str:
    for text in texts:
        for sent in clean_sentences(text):
            lower = sent.lower()
            if any(keyword in lower for keyword in any_keywords):
                return sent
    return ""


def prefer_summary_sentence(texts: list[str]) -> str:
    preferred_starts = [
        "this paper",
        "we ",
        "this article",
        "using ",
        "the paper",
        "in this paper",
        "our results",
        "this study",
    ]
    for text in texts:
        for sent in clean_sentences(text):
            lower = sent.lower()
            if any(lower.startswith(prefix) for prefix in preferred_starts):
                return sent
    for text in texts:
        cleaned = clean_sentences(text)
        if cleaned:
            return cleaned[0]
    return ""


def build_summary(record: ItemRecord, meta: dict[str, Any], text: str) -> dict[str, Any]:
    abstract = find_abstract(text)
    conclusion = find_conclusion(text)
    methods = find_method_section(text)
    intro = find_section(text, ["introduction"], 3500) or text[:3500]
    candidates = [abstract, methods, conclusion, intro]

    summary_sentences = clean_sentences(abstract) or clean_sentences(conclusion) or clean_sentences(intro)
    one_sentence = prefer_summary_sentence([abstract, conclusion, intro]) or f"本文围绕《{record.title}》展开分析。"

    problem = (
        best_sentence(candidates, ["this paper"])
        or best_sentence(candidates, ["we examine"])
        or best_sentence(candidates, ["we investigate"])
        or best_sentence(candidates, ["this study"])
    )
    study_area = (
        best_sentence(candidates, ["data"])
        or best_sentence(candidates, ["sample"])
        or best_sentence(candidates, ["period"])
        or best_sentence(candidates, ["countries"])
        or best_sentence(candidates, ["market"])
    )
    methodology = (
        best_sentence(candidates, ["model"])
        or best_sentence(candidates, ["method"])
        or best_sentence(candidates, ["regression"])
        or best_sentence(candidates, ["copula"])
        or best_sentence(candidates, ["var"])
        or best_sentence(candidates, ["garch"])
    )
    findings = clean_sentences(conclusion)[:3] or clean_sentences(abstract)[:3] or summary_sentences[:3]

    source = meta.get("source") or ""
    authors = "; ".join(meta.get("authors") or [])
    year = record.year or extract_year(meta.get("raw_date")) or ""
    link = meta.get("doi") or record.doi or meta.get("url") or ""
    if link and link.startswith("10."):
        link = f"https://doi.org/{link}"

    collection_hint = " / ".join(record.collection_paths[:2])
    relevance = (
        f"可作为“{collection_hint}”相关主题的参考文献。"
        if collection_hint
        else "可作为当前研究主题的补充参考文献。"
    )

    theory = best_sentence(candidates, ["theory"]) or best_sentence(candidates, ["framework"]) or "论文主要基于原文提出的理论或实证分析框架展开。"
    data_sentence = study_area or best_sentence(candidates, ["dataset"]) or "原文对样本与数据来源有说明，但自动提取信息有限。"
    core_variable = best_sentence(candidates, ["variable"]) or best_sentence(candidates, ["dependence"]) or best_sentence(candidates, ["volatility"]) or "核心变量需结合原文方法部分进一步细读。"

    return {
        "authors": authors,
        "year": year,
        "source": source,
        "link": link,
        "one_sentence": one_sentence,
        "theme": safe_excerpt(one_sentence, 70),
        "problem": problem or "论文关注的核心问题需结合原文摘要和引言理解。",
        "study_area": safe_excerpt(data_sentence, 100),
        "methodology": safe_excerpt(methodology or "原文使用实证或理论模型展开分析。", 100),
        "core_variable": safe_excerpt(core_variable, 100),
        "key_finding": safe_excerpt(findings[0] if findings else one_sentence, 100),
        "relevance": relevance,
        "theory": safe_excerpt(theory, 100),
        "data_sentence": data_sentence,
        "method_sentence": methodology or "原文方法部分需进一步细读。",
        "findings": findings[:3],
        "conclusion_excerpt": conclusion,
        "abstract_excerpt": abstract,
    }


def extract_year(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    match = re.search(r"(19|20)\d{2}", raw_date)
    return match.group(0) if match else None


def render_note(record: ItemRecord, meta: dict[str, Any], summary: dict[str, Any]) -> str:
    findings = summary["findings"] or [summary["one_sentence"]]
    link_display = summary["link"] or "未提取到 DOI/URL"
    link_md = f"[链接]({link_display})" if link_display.startswith("http") else link_display

    findings_md = []
    for idx, finding in enumerate(findings, 1):
        quote_source = summary["conclusion_excerpt"] or summary["abstract_excerpt"] or finding
        findings_md.append(
            "\n".join(
                [
                    f"- **主要发现 {idx}**：{finding}",
                    f"- **原文依据 {idx}**：{safe_excerpt(quote_source, 220)}",
                ]
            )
        )

    return f"""---
title: "{record.title}"
aliases: []
tags:
  - literature-note
  - reading-note
created: "{today_str()}"
source: "{summary['source']}"
author: "{summary['authors']}"
year: "{summary['year']}"
theme: "{summary['theme']}"
study_area: "{summary['study_area']}"
data_source: "{safe_excerpt(summary['data_sentence'], 100)}"
methodology: "{summary['methodology']}"
core_variable: "{summary['core_variable']}"
key_finding: "{summary['key_finding']}"
relevance: "{summary['relevance']}"
theory: "{summary['theory']}"
---

# {record.title}

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 作者 | {summary['authors']} |
| 年份 | {summary['year']} |
| 来源 | {summary['source']} |
| 主题 | {summary['theme']} |
| 链接 | {link_md} |

## 一句话摘要

> {summary['one_sentence']}

## 研究对象

- **研究对象**：{summary['study_area']}
- **核心问题**：{summary['problem']}
- **研究情境/范围**：{safe_excerpt(summary['data_sentence'], 180)}

## 研究方法

### 方法概述

- **方法类型**：{"理论/综述" if record.item_type in {"bookSection"} else "实证/理论"}
- **总体思路**：{safe_excerpt(summary['method_sentence'], 180)}
- **为什么用这种方法**：原文通过相应模型或分析框架来识别研究问题中的关键机制。

### 方法分析

- **分析单位**：以原文设定的样本、市场、国家、网络或时间序列为分析对象。
- **关键变量/概念**：{summary['core_variable']}
- **识别/推断逻辑**：{safe_excerpt(summary['method_sentence'], 180)}
- **具体步骤**：建议结合 PDF 中的方法与实证设计部分进一步细读，这里先保留自动提取的核心思路。
- **方法优势**：能够把研究问题中的核心关系转化为可检验的模型或分析框架。
- **方法局限**：当前笔记为批量阅读初稿，复杂识别细节和稳健性检验仍建议回到原文核对。

## 数据来源

- **数据类型**：二手数据 / 文献资料 / 理论模型（以原文为准）
- **样本来源**：{safe_excerpt(summary['data_sentence'], 180)}
- **时间范围**：{summary['year'] or '原文中需进一步核对'}
- **样本量/案例数**：原文中需进一步核对具体样本规模。
- **数据局限**：批量初读阶段仅提取到摘要和结论层面的数据线索。

## 研究结论

{chr(10).join(findings_md)}

## 我的判断

- **最有启发的点**：这篇文章为“{record.collection_paths[0] if record.collection_paths else '当前主题'}”提供了可直接引用的问题意识或分析框架。
- **可借鉴的方法**：可优先借鉴其变量设定、建模思路或文献综述组织方式。
- **可继续追问的问题**：需要回到原文进一步核对具体识别策略、变量构造和稳健性检验。
- **与我的研究关联**：{summary['relevance']}
"""


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def update_status(item_key: str, row: dict[str, Any]) -> None:
    existing_rows = read_jsonl(STATUS_PATH)
    updated = False
    for idx, existing in enumerate(existing_rows):
        if existing.get("item_key") == item_key:
            existing_rows[idx] = row
            updated = True
            break
    if not updated:
        existing_rows.append(row)
    STATUS_PATH.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in existing_rows) + "\n",
        encoding="utf-8",
    )


def main(batch_size: int = DEFAULT_BATCH_SIZE, rerun_done: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    status_map = load_status_map()
    index_items = load_index_items()
    queue = [
        item
        for item in index_items
        if item.pdf_paths and (rerun_done or status_map.get(item.item_key, {}).get("status") != "done")
    ][:batch_size]

    db_path = choose_db()
    conn = connect_db(db_path)
    metadata_map = load_metadata(conn)
    conn.close()

    run_ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_log_path = LOG_DIR / f"read_index_batch_{run_ts}.md"
    log_lines = [
        "# Zotero Index Batch Reading",
        "",
        f"- Run at: `{now_iso()}`",
        f"- Source index: `{INDEX_PATH}`",
        f"- Batch size: `{len(queue)}`",
        f"- Source DB: `{db_path}`",
        "",
        "## Results",
        "",
    ]

    completed = 0
    needs_pdf = 0
    failed = 0

    for idx, record in enumerate(queue, 1):
        pdf_path = Path(record.pdf_paths[0])
        target = " / ".join(record.collection_paths) if record.collection_paths else "Unfiled"
        status_row = {
            "item_key": record.item_key,
            "title": record.title,
            "target": target,
            "status": "",
            "note_path": None,
            "updated_at": now_iso(),
            "reason": "",
        }
        if not pdf_path.exists():
            status_row["status"] = "needs_pdf"
            status_row["reason"] = f"Indexed PDF path missing: {pdf_path}"
            update_status(record.item_key, status_row)
            log_lines.append(f"- [{idx:02d}] `needs_pdf` | {record.item_key} | {record.title}")
            needs_pdf += 1
            continue

        try:
            full_text, pages = extract_text_from_pdf(pdf_path)
            text = normalize_text(full_text)
            meta = metadata_map.get(record.item_key, {})
            summary = build_summary(record, meta, text)
            relative_parts = [sanitize_filename(part) for part in record.collection_paths]
            note_dir = NOTES_DIR.joinpath(*relative_parts) if relative_parts else NOTES_DIR / "Unfiled"
            note_name = f"{sanitize_filename(record.title)}__{record.item_key}.md"
            note_path = note_dir / note_name
            ensure_parent(note_path)
            note_path.write_text(render_note(record, meta, summary), encoding="utf-8")

            status_row["status"] = "done"
            status_row["note_path"] = str(note_path)
            status_row["reason"] = "PDF available and new reading note generated from PDF text."
            update_status(record.item_key, status_row)

            log_lines.extend(
                [
                    f"- [{idx:02d}] `done` | {record.item_key} | {record.title}",
                    f"  - target: `{target}`",
                    f"  - note: `{note_path}`",
                    f"  - summary: {summary['one_sentence']}",
                ]
            )
            completed += 1
        except Exception as exc:
            status_row["status"] = "needs_note"
            status_row["reason"] = f"Batch reading failed: {type(exc).__name__}: {exc}"
            update_status(record.item_key, status_row)
            log_lines.append(f"- [{idx:02d}] `needs_note` | {record.item_key} | {record.title} | {exc}")
            failed += 1

    log_lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Done: `{completed}`",
            f"- Needs PDF: `{needs_pdf}`",
            f"- Needs note: `{failed}`",
        ]
    )
    run_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(json.dumps(
        {
            "completed": completed,
            "needs_pdf": needs_pdf,
            "needs_note": failed,
            "log_path": str(run_log_path),
            "queue_size": len(queue),
        },
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Deprecated PDF-only batch reader. Prefer zotero_ai_reading_pipeline.py; "
            "this script requires --run to avoid accidental execution."
        )
    )
    parser.add_argument("--run", action="store_true", help="Actually run this legacy PDF-only batch reader.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Number of queued papers to process.")
    parser.add_argument("--rerun-done", action="store_true", help="Include items already marked done.")
    args = parser.parse_args()
    if not args.run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "Legacy PDF-only batch reader requires --run. Prefer zotero_ai_reading_pipeline.py.",
                },
                ensure_ascii=False,
            )
        )
    else:
        main(batch_size=args.batch_size, rerun_done=args.rerun_done)
