from __future__ import annotations

import argparse
import json
import re
import sys
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
INDEX_PATH = CONFIG.index_path
NOTES_DIR = CONFIG.notes_dir
CURRENT_TAXONOMY_PATH = CONFIG.taxonomy_path
PROPOSAL_JSON_PATH = CONFIG.indexes_dir / "audited_tag_taxonomy_proposal.json"
PROPOSAL_MD_PATH = CONFIG.indexes_dir / "audited_tag_taxonomy_proposal.md"

DIMENSION_TITLES = {
    "theory": "理论标签",
    "method": "方法标签",
    "topic": "主题标签",
}

CURRENT_RULES: dict[str, list[dict[str, Any]]] = {}

PROPOSED_RULES: dict[str, list[dict[str, Any]]] = {
    "theory": [
        {
            "label": "资产定价理论",
            "parent": "理论 / 投资与资产定价",
            "description": "资产收益、风险因子、CAPM/ICAPM、便利收益和风险收益权衡等资产定价框架。",
            "keywords": ["asset pricing", "capm", "icapm", "risk-return trade-off", "资产定价", "风险收益"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "投资组合理论",
            "parent": "理论 / 投资与资产定价",
            "description": "投资组合配置、分散化、对冲组合和均值-方差选择。",
            "keywords": ["portfolio theory", "portfolio", "mean-variance", "investment portfolio", "投资组合", "均值-方差"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "系统性风险理论",
            "parent": "理论 / 风险与金融稳定",
            "description": "金融稳定、系统性风险贡献、金融网络冲击传导和系统脆弱性。",
            "keywords": ["systemic risk", "financial stability", "debtRank", "系统性风险", "金融稳定", "系统脆弱"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "极值理论与尾部依赖",
            "parent": "理论 / 风险与金融稳定",
            "description": "极端风险、尾部依赖、极值理论和危机状态下的相依结构。",
            "keywords": ["extreme value", "tail dependence", "tail risk", "极值理论", "尾部依赖", "尾部风险"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "货币国际化理论",
            "parent": "理论 / 国际货币体系",
            "description": "货币国际化、计价货币、结算货币和国际货币地位形成机制。",
            "keywords": ["currency internationalization", "international currency", "vehicle currency", "invoicing currency", "货币国际化", "计价货币"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "汇率决定与 UIP 偏离",
            "parent": "理论 / 国际金融",
            "description": "汇率决定、UIP 偏离、汇率压力与汇率风险传导。",
            "keywords": ["exchange rate determination", "uip", "uncovered interest parity", "汇率决定", "UIP偏离", "货币压力"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "全球价值链理论",
            "parent": "理论 / 国际贸易",
            "description": "全球价值链、区域价值链、贸易网络和生产分工重构。",
            "keywords": ["global value chain", "regional value chain", "trade network", "全球价值链", "区域价值链", "贸易网络"],
            "exclude": [],
            "action": "candidate_add",
        },
    ],
    "method": [
        {
            "label": "SVAR / Proxy SVAR",
            "parent": "方法 / VAR 族",
            "description": "结构向量自回归、代理变量 SVAR、递归识别和脉冲响应。",
            "keywords": ["svar", "proxy svar", "structural vector autoregression", "cholesky", "结构向量自回归", "递归识别"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "ARDL / NARDL",
            "parent": "方法 / 时间序列协整",
            "description": "ARDL 边界协整、NARDL、ECM 和长期/短期动态分解。",
            "keywords": ["ardl", "nardl", "bounds testing", "boundary cointegration", "边界协整", "误差修正模型"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "Copula",
            "parent": "方法 / 依赖结构",
            "description": "Copula、Vine Copula、时变 Copula 和尾部依赖建模。",
            "keywords": ["copula", "vine copula", "c-vine", "d-vine", "r-vine", "sklar", "尾部依赖"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "小波与多尺度分解",
            "parent": "方法 / 频域与时频",
            "description": "Wavelet、MODWT、CEEMDAN、EMD 与多尺度时频分解。",
            "keywords": ["wavelet", "modwt", "ceemdan", "emd", "time-frequency", "小波", "多尺度", "时频"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "分位数方法",
            "parent": "方法 / 分布与尾部",
            "description": "分位数回归、QVAR、quantile connectedness 和分位数因果。",
            "keywords": ["quantile regression", "qvar", "quantile var", "quantile connectedness", "分位数回归", "分位数"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "Diebold-Yilmaz 溢出指数",
            "parent": "方法 / 溢出测度",
            "description": "基于预测误差方差分解的溢出指数、连通性指数和频域扩展。",
            "keywords": ["diebold", "yilmaz", "spillover index", "gfevd", "variance decomposition", "溢出指数", "方差分解"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "机器学习与非参数方法",
            "parent": "方法 / 机器学习",
            "description": "随机森林、GAM、LASSO、非参数估计和机器学习预测。",
            "keywords": ["random forest", "lasso", "machine learning", "nonparametric", "generalized additive model", "随机森林", "机器学习", "非参数"],
            "exclude": [],
            "action": "candidate_add",
        },
    ],
    "topic": [
        {
            "label": "加密资产与数字金融",
            "parent": "主题 / 资产市场",
            "description": "加密货币、Bitcoin、数字资产、稳定币和数字金融市场。",
            "keywords": ["cryptocurrency", "cryptocurrencies", "bitcoin", "stablecoin", "digital asset", "加密货币", "数字资产"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "绿色金融与清洁能源资产",
            "parent": "主题 / 能源与绿色金融",
            "description": "绿色债券、清洁能源、绿色资产、碳市场与可持续金融。",
            "keywords": ["green bond", "clean energy", "renewable energy", "green finance", "carbon market", "绿色金融", "清洁能源", "绿色债券"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "原油与大宗商品",
            "parent": "主题 / 大宗商品与能源",
            "description": "原油、能源商品、黄金、大宗商品价格和商品市场联动。",
            "keywords": ["crude oil", "oil price", "commodity", "gold", "原油", "黄金", "大宗商品"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "股票市场联动",
            "parent": "主题 / 资产市场",
            "description": "股票市场共动、市场互联、股市波动和跨市场风险传导。",
            "keywords": ["stock market", "equity market", "market comovement", "stock returns", "股票市场", "股市", "市场联动"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "货币压力与汇率风险",
            "parent": "主题 / 国际金融与汇率",
            "description": "汇率压力、货币压力指数、外汇风险和汇率波动。",
            "keywords": ["exchange market pressure", "currency pressure", "exchange rate risk", "exchange rate volatility", "货币压力", "汇率风险", "汇率波动"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "跨境资本流动",
            "parent": "主题 / 国际金融",
            "description": "跨境资本流动、国际资本流动、银行跨境敞口和资本外流。",
            "keywords": ["capital flow", "cross-border", "cross border", "capital outflow", "跨境资本", "资本流动", "银行跨境敞口"],
            "exclude": [],
            "action": "candidate_add",
        },
        {
            "label": "RCEP 与区域合作",
            "parent": "主题 / 区域国别",
            "description": "RCEP、中国-东盟、区域合作和区域价值链重构。",
            "keywords": ["rcep", "asean", "中国-东盟", "东盟", "区域合作", "区域价值链"],
            "exclude": [],
            "action": "candidate_add",
        },
    ],
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def extract_item_key(path: Path) -> str | None:
    if "__" not in path.stem:
        return None
    return path.stem.rsplit("__", 1)[-1].strip() or None


def frontmatter_text(text: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def parse_frontmatter(path: Path) -> dict[str, Any]:
    try:
        fm = frontmatter_text(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in fm.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            parsed.setdefault(current_key, []).append(line[4:].strip().strip('"'))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"')
            current_key = key
            parsed[key] = [] if value == "[]" or not value else value
    return parsed


def flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(item)}" for key, item in value.items())
    return str(value)


def note_text(index_row: dict[str, Any], fm: dict[str, Any]) -> str:
    fields = [
        index_row.get("title", ""),
        index_row.get("collection_paths") or [],
        fm.get("title", ""),
        fm.get("theme", ""),
        fm.get("study_area", ""),
        fm.get("methodology", ""),
        fm.get("theory", ""),
        fm.get("key_finding", ""),
        fm.get("relevance", ""),
    ]
    return " ".join(flatten(field) for field in fields if flatten(field))


def keyword_hit(text_lower: str, keyword: str) -> bool:
    needle = keyword.lower().strip()
    if not needle:
        return False
    if needle.startswith("re:"):
        try:
            return re.search(needle[3:], text_lower, flags=re.I) is not None
        except re.error:
            return False
    if re.fullmatch(r"[a-z0-9-]{1,4}", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_lower) is not None
    return needle in text_lower


def load_current_taxonomy() -> dict[str, list[dict[str, Any]]]:
    if not CURRENT_TAXONOMY_PATH.exists():
        return {dimension: [] for dimension in DIMENSION_TITLES}
    data = json.loads(CURRENT_TAXONOMY_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for dimension in DIMENSION_TITLES:
        out[dimension] = []
        for entry in data.get("dimensions", {}).get(dimension, []):
            out[dimension].append(
                {
                    "label": entry.get("label"),
                    "parent": entry.get("target_collection_path") or entry.get("target_collection_base") or "",
                    "description": entry.get("description") or "",
                    "keywords": entry.get("keywords") or [],
                    "exclude": entry.get("negative_keywords") or [],
                    "action": "keep_existing",
                }
            )
    return out


def load_notes() -> list[dict[str, Any]]:
    index_by_key = {row.get("item_key"): row for row in read_jsonl(INDEX_PATH) if row.get("item_key")}
    notes: list[dict[str, Any]] = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        item_key = extract_item_key(path)
        if not item_key:
            continue
        fm = parse_frontmatter(path)
        index_row = index_by_key.get(item_key, {})
        notes.append(
            {
                "item_key": item_key,
                "title": index_row.get("title") or fm.get("title") or path.stem,
                "note_path": str(path),
                "primary_collection": index_row.get("primary_collection_path") or fm.get("primary_collection") or "",
                "text": note_text(index_row, fm),
            }
        )
    return notes


def evaluate_rule(rule: dict[str, Any], notes: list[dict[str, Any]], sample_limit: int) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    keyword_counts: dict[str, int] = {}
    for note in notes:
        text_lower = note["text"].lower()
        if any(keyword_hit(text_lower, kw) for kw in rule.get("exclude") or []):
            continue
        hits = [kw for kw in rule.get("keywords") or [] if keyword_hit(text_lower, kw)]
        if not hits:
            continue
        for hit in hits:
            keyword_counts[hit] = keyword_counts.get(hit, 0) + 1
        if len(matches) < sample_limit:
            matches.append(
                {
                    "item_key": note["item_key"],
                    "title": note["title"],
                    "primary_collection": note["primary_collection"],
                    "matched_keywords": hits,
                    "note_path": note["note_path"],
                }
            )
    return {
        "label": rule["label"],
        "parent": rule.get("parent", ""),
        "description": rule.get("description", ""),
        "keywords": rule.get("keywords") or [],
        "exclude": rule.get("exclude") or [],
        "action": rule.get("action", "candidate_add"),
        "evidence_count": sum(keyword_counts.values()),
        "matched_note_count": len([1 for note in notes if any(keyword_hit(note["text"].lower(), kw) for kw in rule.get("keywords") or [])]),
        "top_keywords": sorted(keyword_counts.items(), key=lambda item: (-item[1], item[0]))[:8],
        "sample_notes": matches,
        "review_status": "pending" if rule.get("action") != "keep_existing" else "existing_review",
    }


def build_proposal(sample_limit: int) -> dict[str, Any]:
    notes = load_notes()
    current = load_current_taxonomy()
    dimensions: dict[str, list[dict[str, Any]]] = {}
    for dimension in DIMENSION_TITLES:
        rules = current.get(dimension, []) + PROPOSED_RULES.get(dimension, [])
        dimensions[dimension] = [evaluate_rule(rule, notes, sample_limit) for rule in rules]
    return {
        "generated_at": now_iso(),
        "source": "current MindCite notes and zotero_library_index.jsonl",
        "notes_scanned": len(notes),
        "status": "proposal_only_not_applied",
        "audit_policy": {
            "note_tags_are_not_backfilled_until_user_approval": True,
            "zotero_writeback_is_dryrun_only": True,
            "new_reading_notes_should_start_with_classification_status": "pending",
            "classification_evidence_required": ["matched_keywords", "sample_notes", "review_status"],
        },
        "dimensions": dimensions,
    }


def write_markdown(path: Path, proposal: dict[str, Any]) -> None:
    lines = [
        "# Audited Tag Taxonomy Proposal",
        "",
        f"- Generated at: `{proposal['generated_at']}`",
        f"- Notes scanned: `{proposal['notes_scanned']}`",
        f"- Status: `{proposal['status']}`",
        "",
        "## 使用方式",
        "",
        "- 这是一份标签体系提案，不会自动改 notes 或 Zotero。",
        "- `keep_existing` 表示当前词表已有标签；`candidate_add` 表示建议新增或拆分。",
        "- 你确认后，再把通过的标签合并进 `classification_taxonomy.json`，再进入旧 notes 属性填补。",
        "- 后续新精读也应先生成带 `matched_keywords / sample_notes / review_status` 的审计队列，再写入标签。",
        "",
    ]
    for dimension, title in DIMENSION_TITLES.items():
        lines.extend([f"## {title}", ""])
        rows = proposal["dimensions"][dimension]
        rows = sorted(rows, key=lambda row: (row["action"] != "candidate_add", -row["matched_note_count"], row["label"]))
        lines.append("| 标签 | 动作 | 父级/位置 | 命中 notes | 主要证据词 | 审核状态 |")
        lines.append("| --- | --- | --- | ---: | --- | --- |")
        for row in rows:
            top_keywords = "；".join(f"{kw}({count})" for kw, count in row["top_keywords"][:4])
            lines.append(
                f"| {row['label']} | {row['action']} | {row['parent']} | "
                f"{row['matched_note_count']} | {top_keywords} | {row['review_status']} |"
            )
        lines.append("")
        lines.append("### 样本文献")
        lines.append("")
        for row in rows[:12]:
            if not row["sample_notes"]:
                continue
            lines.append(f"**{row['label']}**")
            for sample in row["sample_notes"][:3]:
                hits = "、".join(sample["matched_keywords"])
                lines.append(f"- `{sample['item_key']}` {sample['title']} | 证据：{hits}")
            lines.append("")

    lines.extend(
        [
            "## 后续精读审计规则建议",
            "",
            "- 新精读笔记继续写 `classification_status: pending`，不要直接视为已审核。",
            "- 标签候选必须保留 `matched_keywords` 和来源字段，进入审核队列。",
            "- 高置信标签可以进入拟写计划，但真实写入 note frontmatter 前仍需可追溯记录。",
            "- Zotero 分类写回继续只做 dry-run，除非用户单独批准。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an audited tag taxonomy proposal from current notes.")
    parser.add_argument("--json-out", type=Path, default=PROPOSAL_JSON_PATH)
    parser.add_argument("--md-out", type=Path, default=PROPOSAL_MD_PATH)
    parser.add_argument("--sample-limit", type=int, default=5)
    args = parser.parse_args()

    proposal = build_proposal(args.sample_limit)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(args.md_out, proposal)
    print(
        json.dumps(
            {
                "ok": True,
                "json_out": str(args.json_out),
                "md_out": str(args.md_out),
                "notes_scanned": proposal["notes_scanned"],
                "theory_tags": len(proposal["dimensions"]["theory"]),
                "method_tags": len(proposal["dimensions"]["method"]),
                "topic_tags": len(proposal["dimensions"]["topic"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
