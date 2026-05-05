from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore
except ImportError:
    winreg = None

from pypdf import PdfReader

SKILLS_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = SKILLS_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from mindcite_config import configured_existing_paths, expand_env_data, load_config


CONFIG = load_config(Path(__file__))
ROOT = CONFIG.root
INDEX_PATH = CONFIG.index_path
TAXONOMY_PATH = CONFIG.taxonomy_path
STATUS_PATH = CONFIG.status_path
LOG_DIR = CONFIG.logs_dir
NOTES_DIR = CONFIG.notes_dir
NOTES_PAPERS_DIR = CONFIG.notes_papers_dir
CONFIG_PATH = CONFIG.reader_config_path
DB_PATHS = configured_existing_paths(CONFIG.zotero_db_path, CONFIG.zotero_snapshot_path)
DEFAULT_BATCH_SIZE = 2
INVALID_FILE_CHARS = '<>:"/\\|?*'
CLASSIFICATION_LIST_FIELDS = [
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
]


@dataclass
class Chunk:
    chunk_id: str
    text: str
    start: int
    end: int
    source: str


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def sanitize_filename(text: str) -> str:
    out = "".join("_" if ch in INVALID_FILE_CHARS else ch for ch in text.strip())
    out = out.rstrip(" .")
    return out or "_"


def yaml_scalar(value: Any) -> str:
    if value is None:
        value = ""
    return json.dumps(str(value), ensure_ascii=False)


def yaml_number_or_empty(value: Any) -> str:
    if value is None or value == "":
        return '""'
    try:
        return str(float(value)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return yaml_scalar(value)


def yaml_list_lines(values: list[Any]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "  []"
    return "\n".join(f"  - {yaml_scalar(value)}" for value in cleaned)


def clean_list_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def normalize_classification_fields(summary: dict[str, Any]) -> dict[str, Any]:
    for field in CLASSIFICATION_LIST_FIELDS:
        summary[field] = clean_list_field(summary.get(field))
    if not summary["method_tags"]:
        summary["method_tags"] = clean_list_field(
            summary["method_family_tags"] + summary["method_model_tags"] + summary["method_combo_tags"]
        )
    summary["classification_status"] = str(summary.get("classification_status") or "pending").strip() or "pending"
    if not summary["classification_audit"]:
        summary["classification_audit"] = ["needs_human_review"]
    return summary


def taxonomy_prompt_summary(max_entries: int = 80) -> dict[str, list[dict[str, Any]]]:
    if not TAXONOMY_PATH.exists():
        return {}
    try:
        data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    dimensions = data.get("dimensions") or {}
    for dimension in ["theory", "method", "topic"]:
        entries: list[dict[str, Any]] = []
        for raw in (dimensions.get(dimension) or [])[:max_entries]:
            entries.append(
                {
                    "label": raw.get("label"),
                    "level": raw.get("level"),
                    "tag_field": raw.get("tag_field"),
                    "parent": raw.get("parent"),
                    "parents": raw.get("parents"),
                    "combines": raw.get("combines"),
                    "keywords": (raw.get("keywords") or [])[:6],
                }
            )
        out[dimension] = entries
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    return expand_env_data(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))


def provider_from_config(config: dict[str, Any], section: str, legacy_key: str | None = None) -> tuple[str, dict[str, Any]]:
    section_config = config.get(section) or {}
    providers = section_config.get("providers") if isinstance(section_config, dict) else None
    if isinstance(providers, dict):
        env_name = f"MINDCITE_{section.upper()}_PROVIDER"
        provider_name = (os.environ.get(env_name) or section_config.get("provider") or "").strip()
        if not provider_name:
            provider_name = next(iter(providers))
        if provider_name not in providers:
            available = ", ".join(sorted(providers))
            raise ValueError(f"Unknown {section} provider `{provider_name}`. Available providers: {available}")
        block = dict(providers[provider_name])
        block["provider"] = provider_name
        return provider_name, block

    if legacy_key and legacy_key in config:
        block = dict(config[legacy_key])
        block["provider"] = legacy_key
        return legacy_key, block

    block = dict(section_config)
    return str(block.get("provider") or section), block


def llm_provider(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return provider_from_config(config, "llm", "deepseek")


def embedding_provider(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return provider_from_config(config, "embedding", "embedding")


def read_user_env_var(name: str) -> str | None:
    if not winreg:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        value, _ = winreg.QueryValueEx(key, name)
        return str(value).strip() if value else None
    except OSError:
        return None


def configured_key(block: dict[str, Any]) -> str | None:
    direct = (block.get("api_key") or "").strip()
    if direct:
        return direct
    env_name = (block.get("api_key_env") or "").strip()
    if env_name:
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
        reg_value = read_user_env_var(env_name)
        if reg_value:
            return reg_value
    return None


def choose_db() -> Path:
    for path in DB_PATHS:
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


def load_metadata(conn: sqlite3.Connection, item_keys: list[str]) -> dict[str, dict[str, Any]]:
    if not item_keys:
        return {}
    placeholders = ",".join("?" for _ in item_keys)
    cur = conn.cursor()
    item_rows = cur.execute(
        f"""
        SELECT
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
            MAX(CASE WHEN f.fieldName = 'DOI' THEN v.value END) AS doi
        FROM items i
        LEFT JOIN itemData d ON d.itemID = i.itemID
        LEFT JOIN fieldsCombined f ON f.fieldID = d.fieldID
        LEFT JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE i.key IN ({placeholders})
        GROUP BY i.key
        """,
        item_keys,
    ).fetchall()

    creator_rows = cur.execute(
        f"""
        SELECT i.key, c.firstName, c.lastName, ic.orderIndex
        FROM itemCreators ic
        JOIN items i ON i.itemID = ic.itemID
        JOIN creators c ON c.creatorID = ic.creatorID
        WHERE i.key IN ({placeholders})
        ORDER BY i.key, ic.orderIndex
        """,
        item_keys,
    ).fetchall()

    authors: dict[str, list[str]] = defaultdict(list)
    for item_key, first_name, last_name, _ in creator_rows:
        full = " ".join(part for part in [first_name or "", last_name or ""] if part).strip()
        if full:
            authors[item_key].append(full)

    out: dict[str, dict[str, Any]] = {}
    for row in item_rows:
        (
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
            doi,
        ) = row
        source = publication_title or proceedings_title or book_title or journal_abbr or ""
        if volume:
            source += f", {volume}"
            if issue:
                source += f"({issue})"
        if pages:
            source += f", {pages}"
        out[item_key] = {
            "authors": authors.get(item_key, []),
            "source": source.strip(", "),
            "raw_date": raw_date,
            "url": url,
            "doi": doi,
        }
    return out


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = text.replace("\u00a0", " ")
    text = text.replace("a b s t r a c t", "abstract")
    text = text.replace("A B S T R A C T", "ABSTRACT")
    text = text.replace("article info", "\narticle info\n")
    text = text.replace("©", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_low_information_text(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered) < 500:
        return True
    noise_markers = [
        "all rights reserved",
        "downloaded from",
        "sage social science collections",
        "copyright",
        "from the sage",
    ]
    marker_hits = sum(1 for marker in noise_markers if marker in lowered)
    token_count = len(re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", lowered))
    if marker_hits >= 2 and token_count < 200:
        return True
    return False


def load_text_source(index_row: dict[str, Any]) -> tuple[str, str, str]:
    candidates: list[tuple[str, str, bool]] = []
    cache_path = index_row.get("primary_fulltext_cache_path")
    if cache_path and Path(cache_path).exists():
        text = normalize_text(Path(cache_path).read_text(encoding="utf-8", errors="ignore"))
        low_info = is_low_information_text(text)
        if not low_info:
            return text, "zotero-ft-cache", ""
        candidates.append((text, "zotero-ft-cache", True))

    pdf_path = index_row.get("primary_pdf_path")
    if pdf_path and Path(pdf_path).exists():
        reader = PdfReader(pdf_path)
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = normalize_text("\n\n".join(pages))
        low_info = is_low_information_text(text)
        if not low_info:
            warning = "zotero-ft-cache was low-information; used PDF fallback" if candidates else ""
            return text, "pdf-fallback", warning
        candidates.append((text, "pdf-fallback", True))

    if candidates:
        best_text, best_source, _ = max(candidates, key=lambda row: len(row[0]))
        return best_text, best_source, f"{best_source} appears low-information; source text may be incomplete"

    raise FileNotFoundError(f"No readable text source for {index_row['item_key']}")


def split_into_chunks(text: str, chunk_chars: int, overlap_chars: int, source: str) -> list[Chunk]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[Chunk] = []
    buffer = ""
    chunk_start = 0
    cursor = 0
    for para in paragraphs:
        para_text = para if para.endswith(".") else para + "."
        if not buffer:
            buffer = para_text
            chunk_start = cursor
        elif len(buffer) + 2 + len(para_text) <= chunk_chars:
            buffer += "\n\n" + para_text
        else:
            chunk_id = f"chunk_{len(chunks)+1:03d}"
            chunks.append(Chunk(chunk_id=chunk_id, text=buffer, start=chunk_start, end=chunk_start + len(buffer), source=source))
            carry = buffer[-overlap_chars:] if overlap_chars > 0 else ""
            buffer = (carry + "\n\n" + para_text).strip()
            chunk_start = max(0, cursor - len(carry))
        cursor += len(para_text) + 2
    if buffer:
        chunk_id = f"chunk_{len(chunks)+1:03d}"
        chunks.append(Chunk(chunk_id=chunk_id, text=buffer, start=chunk_start, end=chunk_start + len(buffer), source=source))
    return chunks


def section_text(text: str, headings: list[str], max_chars: int = 6000) -> str:
    lower = text.lower()
    found = -1
    matched = ""
    for heading in headings:
        for variant in [heading, heading.lower()]:
            idx = lower.find(variant.lower())
            if idx != -1 and (found == -1 or idx < found):
                found = idx
                matched = variant
    if found == -1:
        return ""
    start = found + len(matched)
    snippet = text[start : start + max_chars]
    next_heading = re.search(r"\n\s*(?:\d+[\.\)]\s*)?[A-Z][A-Za-z0-9 ,/&\-\(\)]{3,80}\n", snippet)
    if next_heading:
        snippet = snippet[: next_heading.start()]
    ref_split = re.split(r"\n\s*references\s*\n", snippet, flags=re.I)
    return ref_split[0].strip()


def build_section_chunks(text: str, source: str) -> dict[str, list[Chunk]]:
    section_map = {
        "summary": section_text(text, ["\nabstract\n", "\nabstract ", "abstract\n"], 3000),
        "research_object": section_text(text, ["\nabstract\n", "\n1. introduction\n", "\nintroduction\n", "\ndata\n"], 3500),
        "problem": section_text(text, ["\nabstract\n", "\n1. introduction\n", "\nintroduction\n"], 3500),
        "methodology": section_text(text, ["\n3. methodology\n", "\nmethodology\n", "\nmethods\n", "\nmodel\n"], 5000),
        "variables": section_text(text, ["\n3. methodology\n", "\nmethodology\n", "\nmodel\n"], 5000),
        "findings": section_text(text, ["\n7. conclusion\n", "\n6. conclusion\n", "\n5. conclusion\n", "\nconclusion\n", "\nconclusions\n"], 5000),
        "limitations": section_text(text, ["\n7. conclusion\n", "\n6. conclusion\n", "\n5. conclusion\n", "\nconclusion\n", "\nconclusions\n"], 5000),
    }
    out: dict[str, list[Chunk]] = {}
    for name, section in section_map.items():
        section = normalize_text(section)
        if section:
            out[name] = [Chunk(chunk_id=f"{name}_section", text=section, start=0, end=len(section), source=source)]
    return out


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def embed_texts(texts: list[str], config: dict[str, Any]) -> list[list[float]]:
    provider_name, provider = embedding_provider(config)
    key = configured_key(provider)
    if not key:
        raise RuntimeError(f"Missing {provider_name} embedding API key.")
    url = (provider.get("url") or provider.get("base_url") or "").strip()
    if not url:
        raise RuntimeError(f"Missing {provider_name} embedding URL.")
    payload = {
        "model": provider["model"],
        "input": texts,
        "encoding_format": "float",
    }
    response = post_json(
        url,
        payload,
        {"Authorization": f"Bearer {key}"},
        int(provider.get("timeout_seconds", 120)),
    )
    data = response.get("data") or []
    data = sorted(data, key=lambda row: row.get("index", 0))
    return [row["embedding"] for row in data]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", text.lower())
    return [part for part in cleaned.split() if len(part) >= 2]


def fallback_rank_chunks(chunks: list[Chunk], query: str, top_k: int) -> list[Chunk]:
    query_terms = set(tokenize(query))
    scored: list[tuple[float, Chunk]] = []
    for chunk in chunks:
        terms = tokenize(chunk.text)
        if not terms:
            continue
        overlap = sum(1 for term in terms if term in query_terms)
        density = overlap / max(1, len(terms))
        score = overlap + density
        scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
    return [chunk for score, chunk in scored[:top_k] if score > 0] or chunks[:top_k]


def compact_cn(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def retrieve_evidence(chunks: list[Chunk], text: str, source: str, config: dict[str, Any]) -> tuple[dict[str, list[Chunk]], str]:
    queries = {
        "summary": "摘要 一句话总结 研究问题 方法 数据 主要发现",
        "research_object": "研究对象 样本 国家 地区 市场 时间范围 数据来源",
        "problem": "研究问题 本文关注什么 为什么重要",
        "methodology": "方法 模型 估计 识别 strategy regression model copula var garch panel",
        "variables": "变量 指标 解释变量 被解释变量 measure index dependence return volatility",
        "findings": "结论 主要发现 result find evidence show conclude",
        "limitations": "局限 robust limitation future research",
    }
    top_k = int(config["retrieval"].get("top_k_per_query", 5))
    section_evidence = build_section_chunks(text, source)
    if section_evidence:
        enriched = {}
        for name, query in queries.items():
            if section_evidence.get(name):
                enriched[name] = section_evidence[name]
            else:
                enriched[name] = fallback_rank_chunks(chunks, query, top_k)
        _, provider = embedding_provider(config)
        if not configured_key(provider):
            return enriched, "section-aware-fallback"

    provider_name, provider = embedding_provider(config)
    embedding_key = configured_key(provider)
    if embedding_key:
        try:
            query_vecs = embed_texts(list(queries.values()), config)
            chunk_vecs = embed_texts([chunk.text for chunk in chunks], config)
            by_query: dict[str, list[Chunk]] = {}
            for (name, _), qvec in zip(queries.items(), query_vecs):
                scored = [(cosine(qvec, cvec), chunk) for chunk, cvec in zip(chunks, chunk_vecs)]
                scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
                by_query[name] = [chunk for _, chunk in scored[:top_k]]
            return by_query, "embedding"
        except Exception:
            pass

    fallback = {name: section_evidence.get(name) or fallback_rank_chunks(chunks, query, top_k) for name, query in queries.items()}
    return fallback, "fallback-keyword"


def llm_complete(messages: list[dict[str, str]], config: dict[str, Any]) -> dict[str, Any]:
    provider_name, provider = llm_provider(config)
    key = configured_key(provider)
    if not key:
        raise RuntimeError(f"Missing {provider_name} LLM API key.")
    base_url = (provider.get("base_url") or "").strip()
    if not base_url:
        raise RuntimeError(f"Missing {provider_name} LLM base_url.")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": provider["model"],
        "temperature": config["generation"].get("temperature", 0.2),
        "messages": messages,
    }
    response_format = provider.get("response_format", {"type": "json_object"})
    if response_format:
        payload["response_format"] = response_format
    return post_json(url, payload, {"Authorization": f"Bearer {key}"}, int(provider.get("timeout_seconds", 120)))


def clip(text: str, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def extract_year(raw_date: str | None, fallback: str | None) -> str:
    if fallback:
        return fallback
    if not raw_date:
        return ""
    match = re.search(r"(19|20)\d{2}", raw_date)
    return match.group(0) if match else ""


def heuristic_summary(index_row: dict[str, Any], meta: dict[str, Any], evidence: dict[str, list[Chunk]]) -> dict[str, Any]:
    def first_text(name: str) -> str:
        chunks = evidence.get(name) or []
        return chunks[0].text if chunks else ""

    def first_sentence(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        parts = re.split(r"(?<=[\.\!\?])\s+", text)
        for part in parts:
            part = part.strip()
            if len(part) > 30:
                return part
        return clip(text, 220) or f"本文围绕《{index_row['title']}》展开分析。"

    summary_text = first_text("summary")
    methodology_text = first_text("methodology")
    findings_text = first_text("findings")
    research_text = first_text("research_object")
    limitation_text = first_text("limitations")

    authors = "; ".join(meta.get("authors") or [])
    year = extract_year(meta.get("raw_date"), index_row.get("year"))
    link = meta.get("doi") or index_row.get("doi") or meta.get("url") or ""
    if link.startswith("10."):
        link = "https://doi.org/" + link

    findings = []
    for source in [findings_text, summary_text]:
        for sent in re.split(r"(?<=[\.\!\?])\s+", re.sub(r"\s+", " ", source)):
            sent = sent.strip()
            if len(sent) > 40:
                findings.append({"claim": sent[:220], "evidence": sent[:260]})
            if len(findings) >= 3:
                break
        if len(findings) >= 3:
            break
    if not findings:
        sentence = first_sentence(summary_text or findings_text)
        findings = [{"claim": sentence, "evidence": sentence}]

    theme = compact_cn(first_sentence(summary_text), 80)
    research_obj = compact_cn(first_sentence(research_text), 180)
    method_sentence = compact_cn(first_sentence(methodology_text), 180)
    core_var = compact_cn(first_sentence(first_text("variables")), 180) or "需结合原文进一步核对核心变量设定。"

    return {
        "title": index_row["title"],
        "authors": authors,
        "year": year,
        "source": meta.get("source") or "",
        "theory_family_tags": [],
        "theory_tags": [],
        "theory_sub_tags": [],
        "method_family_tags": [],
        "method_model_tags": [],
        "method_combo_tags": [],
        "method_tags": [],
        "topic_family_tags": [],
        "topic_tags": [],
        "classification_status": "pending",
        "classification_audit": ["heuristic_fallback_needs_human_review"],
        "theme": f"围绕《{index_row['title']}》讨论的核心问题与主要发现。",
        "study_area": research_obj,
        "data_source": research_obj,
        "methodology": method_sentence,
        "core_variable": core_var,
        "key_finding": clip(findings[0]["claim"], 100),
        "relevance": f"可作为“{index_row.get('primary_collection_path') or '当前主题'}”相关主题的参考文献。",
        "theory": "与金融市场联动、资产定价、风险传导或政策机制相关的理论框架。",
        "one_sentence_summary": first_sentence(summary_text),
        "research_object": research_obj,
        "core_problem": compact_cn(first_sentence(summary_text), 220),
        "research_context": compact_cn(first_sentence(research_text), 220),
        "method_type": "实证/理论",
        "overall_idea": method_sentence,
        "why_method": "作者借助相应模型识别金融变量之间的动态关系、风险传导或政策效应。",
        "analysis_unit": "以论文设定的国家、市场、资产、网络或时间序列样本为分析单位。",
        "key_concepts": core_var,
        "identification_logic": method_sentence,
        "steps": "先界定样本与变量，再建立模型并估计主要关系，最后通过结论部分总结经济含义。",
        "advantages": "适合快速提炼金融学论文中的研究问题、识别策略与主要结论。",
        "limitations": compact_cn(first_sentence(limitation_text), 220) or "当前为 Python 流水线生成的初稿，复杂识别细节与稳健性部分仍建议回看原文。",
        "data_type": "二手数据 / 理论模型（以原文为准）",
        "sample_source": research_obj,
        "time_range": year or "原文中需进一步核对",
        "sample_size": "原文中需进一步核对具体样本规模。",
        "data_limitations": "需要回到原文核对样本构造、变量口径与可得性限制。",
        "findings": findings,
        "most_inspiring": "这篇文章有助于把研究问题、方法设计和经济含义放进同一金融学叙事框架中理解。",
        "borrowable_method": "可借鉴其变量设定、模型结构、识别思路或结果解释方式。",
        "followup_questions": "建议继续核对识别策略、稳健性检验、机制通道与政策含义。",
        "relation_to_my_research": f"与“{index_row.get('primary_collection_path') or '当前主题'}”的主题归类直接相关，可作为后续金融学文献综述或方法借鉴的素材。",
        "link": link,
    }


def build_llm_prompt(index_row: dict[str, Any], meta: dict[str, Any], evidence: dict[str, list[Chunk]], config: dict[str, Any]) -> list[dict[str, str]]:
    max_chunks = int(config["retrieval"].get("max_chunks_for_llm", 16))
    max_chars = int(config["retrieval"].get("max_chars_per_chunk_for_llm", 1000))
    ordered_unique: list[Chunk] = []
    seen: set[str] = set()
    for name in ["summary", "research_object", "problem", "methodology", "variables", "findings", "limitations"]:
        for chunk in evidence.get(name, []):
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            ordered_unique.append(chunk)
            if len(ordered_unique) >= max_chunks:
                break
        if len(ordered_unique) >= max_chunks:
            break

    evidence_text = "\n\n".join(
        f"[{chunk.chunk_id}]\n{clip(chunk.text, max_chars)}" for chunk in ordered_unique
    )
    named_evidence = {
        name: [clip(chunk.text, max_chars) for chunk in evidence.get(name, [])[:2]]
        for name in ["summary", "research_object", "problem", "methodology", "variables", "findings", "limitations"]
    }
    system = (
        "你是一个严谨的金融学论文精读助手。"
        "你熟悉国际金融、资产定价、金融计量、风险传染、宏观金融与政策评估。"
        "你只允许依据用户提供的 Zotero 元数据与原文证据片段作答，不能编造。"
        "请输出严格 JSON，并全部用简体中文填写。"
        "输出风格要接近金融学研究者写给自己看的精读卡片："
        "强调研究问题、样本、识别策略、变量、核心发现、经济含义与可借鉴之处。"
        "如果证据不足，要明确写“需回到原文进一步核对”，不要用空泛套话。"
    )
    user = {
        "paper_title": index_row["title"],
        "item_key": index_row["item_key"],
        "collection_path": index_row.get("primary_collection_path"),
        "year": index_row.get("year"),
        "authors": meta.get("authors", []),
        "source": meta.get("source"),
        "doi": meta.get("doi") or index_row.get("doi"),
        "url": meta.get("url"),
        "zotero_select_uri": index_row.get("zotero_select_uri"),
        "zotero_open_pdf_uri": index_row.get("zotero_open_pdf_uri"),
        "classification_taxonomy": taxonomy_prompt_summary(),
        "required_schema": {
            "theory_family_tags": [],
            "theory_tags": [],
            "theory_sub_tags": [],
            "method_family_tags": [],
            "method_model_tags": [],
            "method_combo_tags": [],
            "method_tags": [],
            "topic_family_tags": [],
            "topic_tags": [],
            "classification_status": "pending",
            "classification_audit": [],
            "theme": "",
            "study_area": "",
            "data_source": "",
            "methodology": "",
            "core_variable": "",
            "key_finding": "",
            "relevance": "",
            "theory": "",
            "one_sentence_summary": "",
            "research_object": "",
            "core_problem": "",
            "research_context": "",
            "method_type": "",
            "overall_idea": "",
            "why_method": "",
            "analysis_unit": "",
            "key_concepts": "",
            "identification_logic": "",
            "steps": "",
            "advantages": "",
            "limitations": "",
            "data_type": "",
            "sample_source": "",
            "time_range": "",
            "sample_size": "",
            "data_limitations": "",
            "findings": [
                {"claim": "", "evidence": ""}
            ],
            "most_inspiring": "",
            "borrowable_method": "",
            "followup_questions": "",
            "relation_to_my_research": ""
        },
        "extra_requirements": [
            "分类标签只能使用 classification_taxonomy 中已有的 label；如果证据不足，标签字段留空，不要编造新标签。",
            "一篇论文允许多个理论标签、多个方法标签和多个主题标签；这不是异常。",
            "方法标签要分层填写：method_family_tags 写方法族，method_model_tags 写具体模型，method_combo_tags 写组合模型。",
            "如果识别出组合模型，例如 GARCH-MIDAS 或 DCC-MIDAS，要同时填写其父级方法族和组成模型。",
            "method_tags 是兼容字段，写入 method_family_tags、method_model_tags、method_combo_tags 的去重并集。",
            "classification_audit 用简短条目说明标签证据；classification_status 默认写 pending。",
            "所有字段必须是中文表达，除非必须保留英文模型名或变量名。",
            "研究对象、样本来源、时间范围尽量写清楚国家、市场、频率和时间窗。",
            "方法部分优先提炼金融计量模型、识别策略、回归设计、网络方法或资产定价框架。",
            "结论部分优先概括与金融学研究最相关的经济含义，不要复述目录页、版权页、致谢、附录标题或参考文献。",
            "如果 abstract、methodology、findings 证据块存在，应优先使用这些命名证据块，而不是使用噪声更高的其他片段。"
        ],
        "named_evidence": named_evidence,
        "evidence_chunks": evidence_text,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def parse_llm_json(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```json\s*|```$", "", content, flags=re.I | re.M).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def llm_summary(index_row: dict[str, Any], meta: dict[str, Any], evidence: dict[str, list[Chunk]], config: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = llm_complete(build_llm_prompt(index_row, meta, evidence, config), config)
            content = response["choices"][0]["message"]["content"]
            data = parse_llm_json(content)
            break
        except Exception as exc:
            last_error = exc
            data = None
    if data is None:
        provider_name, _ = llm_provider(config)
        raise RuntimeError(f"{provider_name} generation failed after retries: {last_error}")
    data["title"] = index_row["title"]
    data["authors"] = "; ".join(meta.get("authors") or [])
    data["year"] = extract_year(meta.get("raw_date"), index_row.get("year"))
    data["source"] = meta.get("source") or ""
    link = meta.get("doi") or index_row.get("doi") or meta.get("url") or ""
    if link.startswith("10."):
        link = "https://doi.org/" + link
    data["link"] = link
    return normalize_classification_fields(data)


def render_note(index_row: dict[str, Any], summary: dict[str, Any]) -> str:
    summary = normalize_classification_fields(summary)
    findings = summary.get("findings") or [{"claim": summary.get("key_finding", ""), "evidence": summary.get("key_finding", "")}]
    link = summary.get("link") or index_row.get("zotero_select_uri") or "未提取到链接"
    link_md = f"[链接]({link})" if str(link).startswith(("http", "zotero://")) else str(link)
    collection_paths = index_row.get("collection_paths") or []
    primary_collection = index_row.get("primary_collection_path") or ""
    classification_audit = "；".join(summary.get("classification_audit") or ["needs_human_review"])
    theory_family_tags = "；".join(summary.get("theory_family_tags") or [])
    theory_tags = "；".join(summary.get("theory_tags") or [])
    theory_sub_tags = "；".join(summary.get("theory_sub_tags") or [])
    method_family_tags = "；".join(summary.get("method_family_tags") or [])
    method_model_tags = "；".join(summary.get("method_model_tags") or [])
    method_combo_tags = "；".join(summary.get("method_combo_tags") or [])
    topic_family_tags = "；".join(summary.get("topic_family_tags") or [])
    topic_tags = "；".join(summary.get("topic_tags") or [])
    findings_md = []
    for idx, row in enumerate(findings, 1):
        findings_md.append(
            "\n".join(
                [
                    f"- **主要发现 {idx}**：{row.get('claim', '需回到原文进一步核对')}",
                    f"- **原文依据 {idx}**：{row.get('evidence', '需回到原文进一步核对')}",
                ]
            )
        )
    return f"""---
title: {yaml_scalar(summary.get('title', index_row['title']))}
aliases: []
tags:
  - literature-note
  - reading-note
created: {yaml_scalar(today_str())}
source: {yaml_scalar(summary.get('source', ''))}
author: {yaml_scalar(summary.get('authors', ''))}
year: {yaml_scalar(summary.get('year', ''))}
publication_title: {yaml_scalar(index_row.get('publication_title') or '')}
journal_abbreviation: {yaml_scalar(index_row.get('journal_abbreviation') or '')}
publication_tags:
{yaml_list_lines(index_row.get('publication_tags') or [])}
journal_rank_tags:
{yaml_list_lines(index_row.get('journal_rank_tags') or [])}
jcr_quartile: {yaml_scalar(index_row.get('jcr_quartile') or '')}
cas_partition: {yaml_scalar(index_row.get('cas_partition') or '')}
cas_partition_basic: {yaml_scalar(index_row.get('cas_partition_basic') or '')}
impact_factor: {yaml_number_or_empty(index_row.get('impact_factor'))}
impact_factor_5y: {yaml_number_or_empty(index_row.get('impact_factor_5y'))}
elite_journal_tags:
{yaml_list_lines(index_row.get('elite_journal_tags') or [])}
zotero_key: {yaml_scalar(index_row.get('item_key', ''))}
zotero_select_uri: {yaml_scalar(index_row.get('zotero_select_uri', ''))}
zotero_open_pdf_uri: {yaml_scalar(index_row.get('zotero_open_pdf_uri', ''))}
zotero_collections:
{yaml_list_lines(collection_paths)}
primary_collection: {yaml_scalar(primary_collection)}
theory_family_tags:
{yaml_list_lines(summary.get('theory_family_tags') or [])}
theory_tags:
{yaml_list_lines(summary.get('theory_tags') or [])}
theory_sub_tags:
{yaml_list_lines(summary.get('theory_sub_tags') or [])}
method_family_tags:
{yaml_list_lines(summary.get('method_family_tags') or [])}
method_model_tags:
{yaml_list_lines(summary.get('method_model_tags') or [])}
method_combo_tags:
{yaml_list_lines(summary.get('method_combo_tags') or [])}
method_tags:
{yaml_list_lines(summary.get('method_tags') or [])}
topic_family_tags:
{yaml_list_lines(summary.get('topic_family_tags') or [])}
topic_tags:
{yaml_list_lines(summary.get('topic_tags') or [])}
classification_status: {yaml_scalar(summary.get('classification_status') or 'pending')}
classification_audit:
{yaml_list_lines(summary.get('classification_audit') or ['needs_human_review'])}
theme: {yaml_scalar(summary.get('theme', ''))}
study_area: {yaml_scalar(summary.get('study_area', ''))}
data_source: {yaml_scalar(summary.get('data_source', ''))}
methodology: {yaml_scalar(summary.get('methodology', ''))}
core_variable: {yaml_scalar(summary.get('core_variable', ''))}
key_finding: {yaml_scalar(summary.get('key_finding', ''))}
relevance: {yaml_scalar(summary.get('relevance', ''))}
theory: {yaml_scalar(summary.get('theory', ''))}
---

# {summary.get('title', index_row['title'])}

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 作者 | {summary.get('authors', '')} |
| 年份 | {summary.get('year', '')} |
| 来源 | {summary.get('source', '')} |
| 主题 | {summary.get('theme', '')} |
| 链接 | {link_md} |

## 分类审计

| 维度 | 候选标签 | 审计说明 |
| --- | --- | --- |
| 理论父级 | {theory_family_tags} | {classification_audit} |
| 理论标签 | {theory_tags} | pending |
| 理论子标签 | {theory_sub_tags} | pending |
| 方法族 | {method_family_tags} | pending |
| 方法模型 | {method_model_tags} | pending |
| 组合模型 | {method_combo_tags} | pending |
| 主题父级 | {topic_family_tags} | pending |
| 主题标签 | {topic_tags} | pending |

## 一句话摘要

> {summary.get('one_sentence_summary', '需回到原文进一步核对')}

## 研究对象

- **研究对象**：{summary.get('research_object', '需回到原文进一步核对')}
- **核心问题**：{summary.get('core_problem', '需回到原文进一步核对')}
- **研究情境/范围**：{summary.get('research_context', '需回到原文进一步核对')}

## 研究方法

### 方法概述

- **方法类型**：{summary.get('method_type', '需回到原文进一步核对')}
- **总体思路**：{summary.get('overall_idea', '需回到原文进一步核对')}
- **为什么用这种方法**：{summary.get('why_method', '需回到原文进一步核对')}

### 方法分析

- **分析单位**：{summary.get('analysis_unit', '需回到原文进一步核对')}
- **关键变量/概念**：{summary.get('key_concepts', '需回到原文进一步核对')}
- **识别/推断逻辑**：{summary.get('identification_logic', '需回到原文进一步核对')}
- **具体步骤**：{summary.get('steps', '需回到原文进一步核对')}
- **方法优势**：{summary.get('advantages', '需回到原文进一步核对')}
- **方法局限**：{summary.get('limitations', '需回到原文进一步核对')}

## 数据来源

- **数据类型**：{summary.get('data_type', '需回到原文进一步核对')}
- **样本来源**：{summary.get('sample_source', '需回到原文进一步核对')}
- **时间范围**：{summary.get('time_range', '需回到原文进一步核对')}
- **样本量/案例数**：{summary.get('sample_size', '需回到原文进一步核对')}
- **数据局限**：{summary.get('data_limitations', '需回到原文进一步核对')}

## 研究结论

{chr(10).join(findings_md)}

## 我的判断

- **最有启发的点**：{summary.get('most_inspiring', '需回到原文进一步核对')}
- **可借鉴的方法**：{summary.get('borrowable_method', '需回到原文进一步核对')}
- **可继续追问的问题**：{summary.get('followup_questions', '需回到原文进一步核对')}
- **与我的研究关联**：{summary.get('relation_to_my_research', '需回到原文进一步核对')}
"""


def note_output_path(index_row: dict[str, Any]) -> Path:
    return NOTES_PAPERS_DIR / f"{sanitize_filename(index_row['title'])}__{index_row['item_key']}.md"


def remove_duplicate_notes(item_key: str, keep_path: Path) -> list[str]:
    removed: list[str] = []
    pattern = f"*__{item_key}.md"
    for candidate in NOTES_DIR.rglob(pattern):
        try:
            same_file = candidate.resolve() == keep_path.resolve()
        except OSError:
            same_file = candidate == keep_path
        if same_file:
            continue
        candidate.unlink(missing_ok=True)
        removed.append(str(candidate))
    return removed


def update_status(item_key: str, row: dict[str, Any]) -> None:
    rows = read_jsonl(STATUS_PATH)
    found = False
    for idx, existing in enumerate(rows):
        if existing.get("item_key") == item_key:
            rows[idx] = row
            found = True
            break
    if not found:
        rows.append(row)
    write_jsonl(STATUS_PATH, rows)


def select_rows(index_rows: list[dict[str, Any]], item_keys: list[str], next_count: int, rerun_done: bool) -> list[dict[str, Any]]:
    if item_keys:
        wanted = set(item_keys)
        rows = [row for row in index_rows if row["item_key"] in wanted]
    else:
        rows = index_rows
    out = []
    for row in rows:
        status = row.get("reading_status")
        if not rerun_done and status in {"done", "needs_pdf", "needs_note", "skipped"}:
            continue
        if row.get("has_fulltext_cache") or row.get("has_pdf"):
            out.append(row)
        if not item_keys and len(out) >= next_count:
            break
    return out


def load_index_rows() -> list[dict[str, Any]]:
    rows = read_jsonl(INDEX_PATH)
    status_map = {row["item_key"]: row for row in read_jsonl(STATUS_PATH) if row.get("item_key")}
    for row in rows:
        status = status_map.get(row["item_key"], {})
        row["reading_status"] = status.get("status")
    return rows


def process_row(index_row: dict[str, Any], meta: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    text, text_source, source_warning = load_text_source(index_row)
    chunks = split_into_chunks(
        text,
        int(config["retrieval"].get("chunk_chars", 1400)),
        int(config["retrieval"].get("chunk_overlap_chars", 150)),
        text_source,
    )
    evidence, retrieval_mode = retrieve_evidence(chunks, text, text_source, config)
    llm_mode = "heuristic-fallback"
    generation_error = ""
    summary = heuristic_summary(index_row, meta, evidence)
    llm_name, llm_config = llm_provider(config)
    if configured_key(llm_config):
        try:
            summary = llm_summary(index_row, meta, evidence, config)
            llm_mode = llm_name
        except Exception as exc:
            llm_mode = "heuristic-fallback"
            generation_error = f"{type(exc).__name__}: {exc}"
    note_path = note_output_path(index_row)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(render_note(index_row, summary), encoding="utf-8")
    removed_duplicates = remove_duplicate_notes(index_row["item_key"], note_path)
    return {
        "note_path": str(note_path),
        "text_source": text_source,
        "source_warning": source_warning,
        "retrieval_mode": retrieval_mode,
        "generation_mode": llm_mode,
        "generation_error": generation_error,
        "summary": summary,
        "chunk_count": len(chunks),
        "removed_duplicates": removed_duplicates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Zotero AI reading pipeline")
    parser.add_argument("--item-keys", default="", help="Comma-separated item keys to process.")
    parser.add_argument("--next-count", type=int, default=DEFAULT_BATCH_SIZE, help="Process next N pending indexed papers.")
    parser.add_argument("--rerun-done", action="store_true", help="Include items already marked done.")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_PAPERS_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()
    llm_name, llm_config = llm_provider(config)
    embedding_name, embedding_config = embedding_provider(config)
    index_rows = load_index_rows()
    if not index_rows:
        print(
            json.dumps(
                {
                    "ok": True,
                    "processed": 0,
                    "message": (
                        "No indexed papers found. Configure ZOTERO_DB_PATH and run "
                        "update_zotero_index.py first, or try the demo with "
                        "MINDCITE_ROOT=examples/demo-vault."
                    ),
                },
                ensure_ascii=False,
            )
        )
        return

    item_keys = [part.strip() for part in args.item_keys.split(",") if part.strip()]
    queue = select_rows(index_rows, item_keys, args.next_count, args.rerun_done)
    if not queue:
        print(
            json.dumps(
                {
                    "ok": True,
                    "processed": 0,
                    "message": (
                        "No matching papers found for the requested item keys or status filters. "
                        "Check indexes/zotero_library_index.jsonl or run update_zotero_index.py."
                    ),
                },
                ensure_ascii=False,
            )
        )
        return

    db_path = choose_db()
    conn = connect_db(db_path)
    metadata = load_metadata(conn, [row["item_key"] for row in queue])
    conn.close()

    run_stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"ai_reading_run_{run_stamp}.md"
    log_lines = [
        "# AI Reading Run",
        "",
        f"- Time: `{now_iso()}`",
        f"- Count: `{len(queue)}`",
        f"- LLM provider: `{llm_name}`",
        f"- LLM configured: `{bool(configured_key(llm_config))}`",
        f"- Embedding provider: `{embedding_name}`",
        f"- Embedding configured: `{bool(configured_key(embedding_config))}`",
        "",
        "## Results",
        "",
    ]

    processed = 0
    for row in queue:
        target = row.get("primary_collection_path") or "Uncategorized"
        status_row = {
            "item_key": row["item_key"],
            "title": row["title"],
            "target": target,
            "status": "",
            "note_path": None,
            "updated_at": now_iso(),
            "reason": "",
            "source_warning": "",
            "low_information_source": False,
        }
        try:
            result = process_row(row, metadata.get(row["item_key"], {}), config)
            status_row["status"] = "done"
            status_row["note_path"] = result["note_path"]
            status_row["source_warning"] = result.get("source_warning") or ""
            status_row["low_information_source"] = bool(result.get("source_warning"))
            status_row["reason"] = f"Generated via {result['text_source']} + {result['retrieval_mode']} retrieval + {result['generation_mode']} generation."
            if result.get("source_warning"):
                status_row["reason"] += f" Warning: {result['source_warning']}."
            update_status(row["item_key"], status_row)
            processed += 1
            log_lines.extend(
                [
                    f"- `done` | {row['item_key']} | {row['title']}",
                    f"  - target: `{target}`",
                    f"  - note: `{result['note_path']}`",
                    f"  - text_source: `{result['text_source']}`",
                    *([f"  - source_warning: `{result['source_warning']}`"] if result.get("source_warning") else []),
                    f"  - retrieval: `{result['retrieval_mode']}`",
                    f"  - generation: `{result['generation_mode']}`",
                    *([f"  - generation_error: `{result['generation_error']}`"] if result.get("generation_error") else []),
                    *(
                        [f"  - removed_duplicates: `{', '.join(result['removed_duplicates'])}`"]
                        if result.get("removed_duplicates")
                        else []
                    ),
                    f"  - summary: {result['summary'].get('one_sentence_summary', '')}",
                ]
            )
        except FileNotFoundError as exc:
            status_row["status"] = "needs_pdf"
            status_row["reason"] = str(exc)
            update_status(row["item_key"], status_row)
            log_lines.append(f"- `needs_pdf` | {row['item_key']} | {row['title']} | {exc}")
        except Exception as exc:
            status_row["status"] = "needs_note"
            status_row["reason"] = f"{type(exc).__name__}: {exc}"
            update_status(row["item_key"], status_row)
            log_lines.append(f"- `needs_note` | {row['item_key']} | {row['title']} | {type(exc).__name__}: {exc}")

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "processed": processed,
                "log_path": str(log_path),
                "llm_provider": llm_name,
                "llm_configured": bool(configured_key(llm_config)),
                "embedding_provider": embedding_name,
                "embedding_configured": bool(configured_key(embedding_config)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
