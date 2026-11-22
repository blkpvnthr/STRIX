"""Optional Snowflake warehouse adapter.

Fully implemented and offline-tested at the SQL-generation level (DDL, COPY INTO,
MERGE, least-privilege roles, auto-suspend/resume). Live validation requires
credentials (via environment variables / approved secret management) and the
``snowflake`` extra; without them the adapter still produces its SQL and reports
itself unavailable rather than failing the rest of STRIX.

Credentials and private account identifiers are read from the environment and are
never committed or logged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from strix.errors import LakehouseError
from strix.lakehouse.warehouse.model import (
    SILVER_TO_FACT,
    TABLES_BY_NAME,
    WAREHOUSE_TABLES,
    create_table_sql,
)

_ENV_KEYS = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")


@dataclass(frozen=True)
class SnowflakeProfile:
    account: str | None = None
    user: str | None = None
    password: str | None = None
    role: str = "STRIX_INGEST"
    warehouse: str = "STRIX_WH"
    database: str = "STRIX"
    schema: str = "ANALYTICS"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> SnowflakeProfile:
        return cls(
            account=env.get("SNOWFLAKE_ACCOUNT"),
            user=env.get("SNOWFLAKE_USER"),
            password=env.get("SNOWFLAKE_PASSWORD"),
            role=env.get("SNOWFLAKE_ROLE", "STRIX_INGEST"),
            warehouse=env.get("SNOWFLAKE_WAREHOUSE", "STRIX_WH"),
            database=env.get("SNOWFLAKE_DATABASE", "STRIX"),
            schema=env.get("SNOWFLAKE_SCHEMA", "ANALYTICS"),
        )


class SnowflakeWarehouse:
    def __init__(self, profile: SnowflakeProfile) -> None:
        self._p = profile

    def available(self) -> bool:
        if not (self._p.account and self._p.user and self._p.password):
            return False
        try:
            import snowflake.connector  # noqa: F401
        except ImportError:
            return False
        return True

    def unavailable_reason(self) -> str:
        if not (self._p.account and self._p.user and self._p.password):
            return f"missing credentials ({', '.join(_ENV_KEYS)})"
        return "snowflake-connector-python not installed (pip install '.[snowflake]')"

    # -- SQL generation (works offline) -----------------------------------

    def ddl_statements(self) -> list[str]:
        p = self._p
        stmts = [
            f"CREATE DATABASE IF NOT EXISTS {p.database}",
            f"CREATE SCHEMA IF NOT EXISTS {p.database}.{p.schema}",
            f"USE SCHEMA {p.database}.{p.schema}",
        ]
        stmts += [create_table_sql(t, "snowflake") for t in WAREHOUSE_TABLES]
        return stmts

    def warehouse_setup_sql(self) -> list[str]:
        p = self._p
        return [
            f"CREATE WAREHOUSE IF NOT EXISTS {p.warehouse} WAREHOUSE_SIZE = XSMALL "
            "AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE",
            f"CREATE ROLE IF NOT EXISTS {p.role}",
            "CREATE ROLE IF NOT EXISTS STRIX_RESEARCH",
            f"GRANT USAGE ON WAREHOUSE {p.warehouse} TO ROLE {p.role}",
            f"GRANT USAGE ON WAREHOUSE {p.warehouse} TO ROLE STRIX_RESEARCH",
            f"GRANT USAGE ON DATABASE {p.database} TO ROLE STRIX_RESEARCH",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {p.database}.{p.schema} TO ROLE STRIX_RESEARCH",
            f"GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {p.database}.{p.schema} "
            f"TO ROLE {p.role}",
        ]

    def copy_into_sql(self, fact_table: str, stage_path: str) -> str:
        return (
            f"COPY INTO {fact_table}_stage FROM '{stage_path}' "
            "FILE_FORMAT = (TYPE = PARQUET) MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE"
        )

    def merge_sql(self, dataset: str) -> str:
        fact = SILVER_TO_FACT[dataset]
        table = TABLES_BY_NAME[fact]
        cols = [c.name for c in table.columns]
        pk = table.primary_key[0]
        set_clause = ", ".join(f"t.{c} = s.{c}" for c in cols if c != pk)
        insert_cols = ", ".join(cols)
        insert_vals = ", ".join(f"s.{c}" for c in cols)
        return (
            f"MERGE INTO {fact} t USING {fact}_stage s ON t.{pk} = s.{pk} "
            f"WHEN MATCHED AND t.row_signature <> s.row_signature THEN UPDATE SET {set_clause} "
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
        )

    def connect(self) -> object:  # pragma: no cover - requires live credentials
        if not self.available():
            raise LakehouseError(f"Snowflake unavailable: {self.unavailable_reason()}")
        import snowflake.connector

        return snowflake.connector.connect(
            account=self._p.account, user=self._p.user, password=self._p.password,
            role=self._p.role, warehouse=self._p.warehouse,
            database=self._p.database, schema=self._p.schema,
        )
