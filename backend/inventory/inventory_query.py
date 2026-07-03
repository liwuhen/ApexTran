from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.agent.settings import SQLSettings

# ── 配置 ──────────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = {"name", "spec", "brand", "material"}

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        s = SQLSettings()
        _engine = create_engine(f"postgresql+psycopg://{s.user}:{s.password}@{s.host}:{s.port}/{s.dbname}")
    return _engine


class InventoryQuery:
    """
    Cross-table query module for inventory combination statistics(SQLAlchemy + PostgreSQL)

    Example:
        iq = InventoryQuery()
        results = iq.query()
    """

    def __init__(self):
        self.engine = _get_engine()

    # ── 内部方法 ───────────────────────────────────────────────────────────────

    def _get_matching_tables(self) -> list[str]:
        """Use SQLAlchemy inspect to find tables that contain all required fields"""
        inspector = inspect(self.engine)
        matching = []
        for table_name in inspector.get_table_names(schema="public"):
            columns = {col["name"] for col in inspector.get_columns(table_name, schema="public")}
            if REQUIRED_FIELDS.issubset(columns):
                matching.append(table_name)
        return matching

    def _build_sql(self, tables: list[str]) -> str:
        """Build UNION ALL + GROUP BY SQL"""
        union_parts = [f'SELECT name, spec, brand, material FROM "{t}"' for t in tables]
        union_sql = " UNION ALL ".join(union_parts)
        return f"""
            SELECT name, spec, brand, material, COUNT(*) AS total
            FROM ({union_sql}) AS combined
            GROUP BY name, spec, brand, material
            ORDER BY name, spec, brand, material
        """

    # ── 公开方法 ───────────────────────────────────────────────────────────────

    def get_matching_tables(self) -> list[str]:
        """Return a list of all table names that match the criteria"""
        return self._get_matching_tables()

    def query(self) -> list[dict]:
        """
        Main query: Cross all matching tables and count totals by combination.
        Returns: [{"name":..., "spec":..., "brand":..., "material":..., "total":...}, ...]
        """
        tables = self._get_matching_tables()
        if not tables:
            return []

        sql = text(self._build_sql(tables))
        with Session(self.engine) as session:
            rows = session.execute(sql).mappings().all()
            return [dict(row) for row in rows]

    def print_results(self):
        """Query and print results to the terminal (for debugging)"""
        tables = self._get_matching_tables()
        if not tables:
            print("No tables found containing all required fields:", REQUIRED_FIELDS)
            return

        print(f"Matching tables ({len(tables)}): {tables}\n")

        results = self.query()
        if not results:
            print("The query result is empty.")
            return

        print(f"{'name':<15} {'spec':<10} {'brand':<12} {'material':<10} {'Total number':>6}")
        print("─" * 58)
        for row in results:
            print(f"{row['name']:<15} {row['spec']:<10} {row['brand']:<12} {row['material']:<10} {row['total']:>6}")
        print("─" * 58)
        print(f"{len(results)} combinations, {sum(r['total'] for r in results)} records total\n")
