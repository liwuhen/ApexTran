import json
import re

import sqlalchemy
from loguru import logger
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from backend.agent.settings import SQLSettings
from backend.inventory.logicfunction import DataFilter, Pgvector
from backend.inventory.sql import SQL
from backend.llm.embedding import Embedding
from backend.utils.types import State

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LLMPostprocess:
    def __init__(self):
        self._sql_set = SQLSettings()
        self.connection_string = f"postgresql+psycopg://{self._sql_set.user}:{self._sql_set.password}@{self._sql_set.host}:{self._sql_set.port}/{self._sql_set.dbname}"
        self.embedding = Embedding()
        self._sql_set_error = False

        if (
            self._sql_set.user is None
            or self._sql_set.password is None
            or self._sql_set.host is None
            or self._sql_set.port is None
            or self._sql_set.dbname is None
        ):
            self._sql_set_error = True

    def get_engine(self) -> sqlalchemy.engine.Engine:
        if self._sql_set_error:
            logger.error("SQL settings are not configured")
            return None
        return sqlalchemy.create_engine(
            self.connection_string,
            connect_args={"connect_timeout": self._sql_set.connect_timeout},
            pool_timeout=self._sql_set.connect_timeout,
        )

    def get_vector_db(self, table_name: str = "none", pre_delete_collection: bool = False) -> Pgvector | None:
        table_name = self._safe_identifier(table_name)
        if self._sql_set_error:
            logger.error("SQL settings are not configured")
            return None

        timeout = self._sql_set.connect_timeout
        try:
            engine = sqlalchemy.create_engine(
                self.connection_string,
                connect_args={"connect_timeout": timeout},
                pool_timeout=timeout,
            )
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
                if pre_delete_collection:
                    conn.execute(sqlalchemy.text(f"DROP TABLE IF EXISTS {table_name}"))
        except ArgumentError as e:
            logger.error("Invalid database URL or engine args: {}", e)
            return None
        except SQLAlchemyError as e:
            logger.error("Database error while creating engine or connecting: {}", e)
            return None
        return Pgvector(engine, self.embedding.embed_query), engine

    def _safe_identifier(self, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"unsafe SQL identifier: {value!r}")
        return value

    def postprocess(self, model_output: str | dict, state: State) -> str:  # noqa: C901 - inventory query result shaping
        pgvector, engine = self.get_vector_db()
        if pgvector is None:
            return "数据库连接失败，请稍后再试"
        data_filter = DataFilter(pgvector)

        if isinstance(model_output, str):
            model_output = json.loads(model_output)

        resolutions = [data_filter.resolve_sku(item) for item in model_output.get("items", [])]

        sql = SQL()
        final_rendered = "您好！很高兴为您服务！\n"
        final_rendered += f"{model_output.get('summary')}\n"
        if model_output.get("unknowns"):
            final_rendered += f"{model_output.get('unknowns')}\n"

        if not resolutions:
            final_rendered += "帮您查询了数据库，未找到相关物品\n"
        for res in resolutions:
            item_norm = res.get("input_item")
            query = {
                key: item_norm[key] for key in item_norm if key != "confidence" and item_norm[key] not in [None, ""]
            }
            if set(query) == {"name"}:
                inventory_row = sql.query_inventory(query, engine)
                if inventory_row:
                    for row in inventory_row:
                        final_rendered += f"{row['name']}库存数量为: {row['total']} \n"
                else:
                    final_rendered += f"{res['name']} 未找到库存\n"
            else:
                item_norm = res.get("top_candidate")
                query = {
                    key: item_norm[key]
                    for key in res.get("top_candidate")
                    if key in ["name", "spec", "brand", "material"] and item_norm[key] not in [None, ""]
                }
                if res.get("resolved"):
                    inventory_row = sql.query_inventory(query, engine)
                    if inventory_row:
                        for row in inventory_row:
                            final_rendered += f"{row['name']} {row['spec']} {row['brand']} {row['material']} 库存数量为: {row['total']} \n"
                else:
                    final_rendered += "帮您查询了数据库，未找到相关物品\n"
        return final_rendered

    def clarify(self, model_output: str, state: State) -> str:
        question = model_output.get("question")
        if question is None:
            return "无法确定用户意图，请重新输入"

        return question
