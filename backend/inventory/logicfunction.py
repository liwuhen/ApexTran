import math
import re
from collections.abc import Callable, Mapping, Sequence
from difflib import SequenceMatcher
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import MetaData, text

from backend.inventory.sqlconstant import _INVENTORY_INTENT_PROTOTYPES
from backend.llm.embedding import Embedding

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class VectorSkuStore(Protocol):
    def similarity_search_with_score(
        self, query: str | Mapping[str, Any], k: int = 5, use_rule: bool = False
    ) -> list[tuple[dict[str, Any], float]]: ...


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _query_text(query: str | Mapping[str, Any]) -> str:
    if isinstance(query, str):
        return query
    return " ".join(str(value).strip() for value in query.values() if str(value).strip())


def _query_columns(query: str | Mapping[str, Any], fallback: Sequence[str]) -> list[str]:
    if isinstance(query, str):
        return [_safe_identifier(column) for column in fallback]

    columns = ["sku_id"]
    for key in query:
        column = _safe_identifier(str(key).removesuffix("_norm"))
        if column not in columns:
            columns.append(column)
    return columns


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    sum_l = 0.0
    sum_r = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        sum_l += a * a
        sum_r += b * b
    denom = math.sqrt(sum_l) * math.sqrt(sum_r)
    if denom <= 0.0:
        return 0.0
    return dot / denom


def _ensure_inventory_prototype_embeddings(
    inventory_proto_embeddings: list[list[float]] | None, intent_embedding_client: Embedding | None
) -> list[list[float]] | None:

    if inventory_proto_embeddings is not None:
        return inventory_proto_embeddings
    if intent_embedding_client is None:
        try:
            intent_embedding_client = Embedding()
        except Exception as exc:
            logger.debug("intent embedding client unavailable: {}", exc)
            return None
    try:
        inventory_proto_embeddings = intent_embedding_client.embed_documents(list(_INVENTORY_INTENT_PROTOTYPES))
    except Exception as exc:
        logger.warning("failed to embed inventory intent prototypes: {}", exc)
        inventory_proto_embeddings = None
        return None
    return inventory_proto_embeddings, intent_embedding_client


def _inventory_embedding_signal(
    intent_embedding_client: Embedding | None, text: str, inventory_proto_embeddings: list[list[float]] | None
) -> tuple[float, bool]:
    """Return (similarity in [0, 1], whether embedding path was usable)."""
    stripped = text.strip()
    if not stripped:
        return (0.0, False)
    protos, intent_embedding_client = _ensure_inventory_prototype_embeddings(
        inventory_proto_embeddings, intent_embedding_client
    )
    if not protos or intent_embedding_client is None:
        return (0.0, False)
    try:
        query_vec = intent_embedding_client.embed_query(stripped[:8000])
    except Exception as exc:
        logger.debug("intent query embedding failed: {}", exc)
        return (0.0, False)
    best = max(_cosine_similarity(query_vec, p) for p in protos)
    return (max(0.0, min(1.0, best)), True)


class Pgvector:
    """Small SQLAlchemy pgvector adapter that replaces LangChain's PGVector store."""

    def __init__(
        self,
        engine: Any,
        embedding_fn: Callable[[str], Sequence[float]],
        *,
        embedding_column: str = "embedding",
        return_columns: Sequence[str] = ("sku_id", "name", "spec", "brand", "material"),
    ) -> None:
        self.engine = engine
        self.embedding_fn = embedding_fn
        self.embedding_column = _safe_identifier(embedding_column)  # 数据库表里存放向量的字段名
        self.return_columns = tuple(_safe_identifier(column) for column in return_columns)

    def similarity_search_with_score(
        self, query: str | Mapping[str, Any], k: int = 5, use_rule: bool = False
    ) -> list[tuple[dict[str, Any], float]]:
        query_embedding = _vector_literal(self.embedding_fn(_query_text(query)))
        query_fields = set(query.keys()) if isinstance(query, Mapping) else set()

        # ── 1. 反射所有表结构 ──────────────────────────────────────────
        metadata = MetaData()
        metadata.reflect(bind=self.engine)

        # ── 2. 找出同时包含 query 所有字段 + embedding 列的表 ──────────
        matched_tables = []
        for table_name, table in metadata.tables.items():
            table_columns = {col.name for col in table.c}
            has_query_fields = query_fields.issubset(table_columns)
            has_embedding_col = self.embedding_column in table_columns
            if has_query_fields and has_embedding_col:
                matched_tables.append(table_name)

        if not matched_tables:
            return []

        # ── 3. 对每张匹配的表做相似度查询 ─────────────────────────────
        all_results: list[tuple[dict[str, Any], float]] = []

        for table_name in matched_tables:
            table = metadata.tables[table_name]
            table_columns = {col.name for col in table.c}

            # 取当前表实际存在的 return_columns（防止字段不一致报错）
            return_columns = [c for c in _query_columns(query, self.return_columns) if c in table_columns]
            if not return_columns:
                continue

            select_columns = ", ".join(return_columns)
            distance_expr = f"{self.embedding_column} <=> CAST(:query_embedding AS vector)"

            statement = text(
                f"""
                SELECT {select_columns}, {distance_expr} AS score
                FROM {table_name}
                ORDER BY {distance_expr}
                LIMIT :limit
                """
            )

            try:
                with self.engine.connect() as conn:
                    rows = conn.execute(statement, {"query_embedding": query_embedding, "limit": k}).mappings()

                    for row in rows:
                        all_results.append((
                            {col: row[col] for col in return_columns},
                            float(row["score"]),
                        ))
            except Exception as e:
                # 单张表查询失败不影响其他表
                logger.warning("inventory.vector_query.table_failed table={} error={}", table_name, e)
                continue

        # ── 4. 全局按 score 升序排序，取 top-k ────────────────────────
        all_results.sort(key=lambda x: x[1])

        if use_rule:
            return all_results[:k], all_results[:20]  # 返回前20条数据用于规则匹配
        return all_results[:k]


class DataFilter:
    def __init__(self, sku_vector_db: VectorSkuStore):
        self.sku_vector_db = sku_vector_db

    def normalize_item(self, item: dict) -> dict:
        return {
            "name": self.normalize_name(str(item.get("name", ""))),
            "spec": self.normalize_spec(str(item.get("spec", ""))),
            "brand": str(item.get("brand", "")).strip(),
            "material": str(item.get("material", "")).strip(),
            "confidence": float(item.get("confidence", 0.0) or 0.0),
        }

    def normalize_name(self, name: str) -> str:
        return (name or "").strip().replace(" ", "")

    def normalize_spec(self, spec: str) -> str:
        return (spec or "").strip().lower().replace(" ", "")

    def exact_and_fuzzy_candidates(self, item_norm: dict, matches: list[tuple[dict[str, Any], float]]) -> list:
        candidates = []
        for meta, score in matches:
            sku_name = self.normalize_name(meta["name"])
            sku_spec = self.normalize_spec(meta["spec"])
            if item_norm["name"] == sku_name and item_norm["spec"] == sku_spec:
                candidates.append({"source": "exact", "sku": meta, "vector_score": score})
                continue

            name_like = SequenceMatcher(None, item_norm["name"], sku_name).ratio()
            spec_like = SequenceMatcher(None, item_norm["spec"], sku_spec).ratio()
            if (name_like >= 0.6 and spec_like >= 0.5) or (name_like >= 0.75):
                candidates.append({"source": "fuzzy", "sku": meta, "vector_score": 0.0})
        return candidates

    def vector_candidates(self, item_norm: dict, sku_vector_db: VectorSkuStore, top_k: int = 5) -> list:
        query = {key: item_norm[key] for key in item_norm if key != "confidence"}
        matches, rule_matches = sku_vector_db.similarity_search_with_score(query, k=top_k, use_rule=True)
        cands = []
        for meta, score in matches:
            # For cosine distance, smaller is better. Convert to similarity-like score.
            vector_score = max(0.0, min(1.0, 1.0 - float(score)))
            cands.append({
                "source": "vector",
                "sku": {
                    "sku_id": meta.get("sku_id", ""),
                    "name": meta.get("name", ""),
                    "spec": meta.get("spec", ""),
                    "brand": meta.get("brand", ""),
                    "material": meta.get("material", ""),
                },
                "vector_score": vector_score,
            })
        return cands, rule_matches

    def merge_candidates(self, rule_cands: list, vec_cands: list) -> list:
        merged = {}

        for cand in rule_cands + vec_cands:
            sku_id = cand["sku"]["sku_id"]
            if sku_id not in merged:
                merged[sku_id] = cand
                continue
            merged[sku_id]["vector_score"] = max(merged[sku_id]["vector_score"], cand["vector_score"])
            if merged[sku_id]["source"] != "exact" and cand["source"] == "exact":
                merged[sku_id]["source"] = "exact"
        return list(merged.values())

    def score_candidate(self, item_norm: dict, candidate: dict) -> dict:
        sku = candidate["sku"]
        name_score = SequenceMatcher(None, item_norm["name"], self.normalize_name(sku["name"])).ratio()
        spec_score = SequenceMatcher(None, item_norm["spec"], self.normalize_spec(sku["spec"])).ratio()
        brand_score = 1.0 if not item_norm["brand"] else SequenceMatcher(None, item_norm["brand"], sku["brand"]).ratio()
        vector_score = candidate.get("vector_score", 0.0)
        final_score = 0.45 * name_score + 0.35 * spec_score + 0.10 * brand_score + 0.10 * vector_score

        return {
            "sku_id": sku["sku_id"],
            "name": sku["name"],
            "spec": sku["spec"],
            "brand": sku["brand"],
            "material": sku["material"],
            "name_score": round(name_score, 4),
            "spec_score": round(spec_score, 4),
            "brand_score": round(brand_score, 4),
            "vector_score": round(vector_score, 4),
            "final_score": round(final_score, 4),
            "source": candidate.get("source", ""),
        }

    def resolve_sku(self, item: dict) -> dict:
        item_norm = self.normalize_item(item)
        vec_cands, rule_matches = self.vector_candidates(item_norm, self.sku_vector_db, top_k=5)
        rule_cands = self.exact_and_fuzzy_candidates(item_norm, rule_matches)
        candidates = self.merge_candidates(rule_cands, vec_cands)

        if not candidates:
            return {
                "input_item": item,
                "normalized_item": item_norm,
                "resolved": False,
                "sku_id": None,
                "name": None,
                "match_score": 0.0,
                "match_reason": "no candidate",
                "needs_human_review": True,
            }

        scored = [self.score_candidate(item_norm, c) for c in candidates]
        best = max(scored, key=lambda x: x["final_score"])

        resolved = best["final_score"] >= 0.50
        needs_human_review = 0.50 <= best["final_score"] < 0.85
        return {
            "input_item": item,
            "normalized_item": item_norm,
            "resolved": resolved,
            "sku_id": best["sku_id"] if resolved else None,
            "name": best["name"],
            "match_score": best["final_score"],
            "match_reason": (
                f"{best['source']} | name={best['name_score']} spec={best['spec_score']} vector={best['vector_score']}"
            ),
            "needs_human_review": needs_human_review,
            "top_candidate": best,
        }
