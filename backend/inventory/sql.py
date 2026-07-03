from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, MetaData, and_, func, select


class SQL:
    def __init__(self):
        pass

    def query_inventory(self, filters: Mapping[str, Any] | None, engine: Engine | None = None) -> list[dict]:

        query_fields = set(filters.keys()) if isinstance(filters, Mapping) else set()
        try:
            metadata = MetaData()
            metadata.reflect(bind=engine)  # 自动反射所有表

            # key: (field_val_tuple) -> total 累加
            merged: dict[tuple, int] = {}
            with engine.connect() as conn:
                for _tname, table in metadata.tables.items():
                    table_columns = {col.name for col in table.c}
                    if not query_fields.issubset(table_columns):
                        continue
                    conditions = [table.c[key] == value for key, value in filters.items()]
                    group_by_cols = [table.c[key] for key in filters]

                    # 所有 filter 字段 + 总数
                    stmt = (
                        select(*group_by_cols, func.count().label("total"))
                        .where(and_(*conditions))
                        .group_by(*group_by_cols)
                    )

                    for row in conn.execute(stmt).mappings():
                        # 用所有 filter 字段的值组成 key
                        key = tuple(row[k] for k in query_fields)
                        merged[key] = merged.get(key, 0) + row["total"]

            # 还原成 list[dict]
            return [{**dict(zip(query_fields, key, strict=False)), "total": total} for key, total in merged.items()]

        except Exception:
            return []
