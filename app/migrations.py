"""SQLite 轻量结构迁移。

项目未引入 Alembic；新增受控修订字段后，旧数据库文件需要在启动时补齐列，
否则查询已存在的表会因缺列报错。所有变更均为可重复执行的 ADD COLUMN。
"""

from sqlalchemy import inspect, text

from .database import engine

# 表名 -> [(列名, 列定义 SQL)]
_PENDING_COLUMNS = {
    "monthly_capacity_reports": [
        ("current_version", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "capacity_follow_ups": [
        ("source", "VARCHAR(16) NOT NULL DEFAULT 'AUTO'"),
        ("auto_generated", "INTEGER NOT NULL DEFAULT 1"),
        (
            "last_revision_id",
            "INTEGER REFERENCES capacity_report_revisions(id)",
        ),
    ],
}


def ensure_capacity_revision_schema() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _PENDING_COLUMNS.items():
            if table not in existing_tables:
                continue  # 由 Base.metadata.create_all 负责新建
            present = {col["name"] for col in inspector.get_columns(table)}
            for column_name, column_ddl in columns:
                if column_name not in present:
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD COLUMN {column_name} {column_ddl}"
                        )
                    )
        # 历史跟进事项无法区分手工/自动来源，保守标记为手工（auto_generated=0），
        # 避免修订流程误关闭运营此前手工登记的事项。
        if "capacity_follow_ups" in existing_tables:
            conn.execute(
                text(
                    "UPDATE capacity_follow_ups SET auto_generated = 0 "
                    "WHERE auto_generated IS NULL"
                )
            )
