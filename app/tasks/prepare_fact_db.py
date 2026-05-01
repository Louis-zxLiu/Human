import os
import sqlite3
from pathlib import Path
from typing import Dict

from app.core.docx_utils import extract_docx_tables
from app.core.config import resolve_path
from app.core.runtime import merge_runtime_status


STRUCTURED_HEADER_MAP = {
    "景区名称": "scenic_name",
    "景点id": "attraction_id",
    "景点名称": "attraction_name",
    "具体位置": "location",
    "建筑/景观参数": "architecture_params",
    "核心功能": "core_function",
    "文化内涵": "cultural_meaning",
    "详细介绍": "description",
    "游玩亮点": "highlights",
    "演艺/开放信息": "open_info",
    "备注": "remarks",
}


def normalize_header(value: str) -> str:
    return value.replace(" ", "").replace("\n", "").replace("\t", "").strip().lower()


def header_mapping() -> Dict[str, str]:
    return {normalize_header(key): val for key, val in STRUCTURED_HEADER_MAP.items()}


def find_structured_docx(kb_dir: str) -> Path:
    candidates = sorted(Path(kb_dir).glob("*.docx"))
    if not candidates:
        raise FileNotFoundError(f"No DOCX files were found under: {kb_dir}")

    mapped_headers = header_mapping()
    for candidate in candidates:
        for table in extract_docx_tables(candidate):
            if not table:
                continue
            headers = [normalize_header(cell) for cell in table[0]]
            if sum(1 for header in headers if header in mapped_headers) >= 4:
                return candidate

    raise RuntimeError("No structured scenic DOCX with recognizable headers was found.")


def load_structured_rows(docx_path: Path) -> tuple[list[str], list[dict[str, object]]]:
    mapped_headers = header_mapping()
    for table in extract_docx_tables(docx_path):
        if len(table) < 2:
            continue
        raw_headers = [normalize_header(cell) for cell in table[0]]
        headers = [mapped_headers.get(header, header) for header in raw_headers]
        if sum(1 for header in raw_headers if header in mapped_headers) < 4:
            continue

        rows: list[dict[str, object]] = []
        for row in table[1:]:
            padded = row + [""] * (len(headers) - len(row))
            rows.append(dict(zip(headers, padded[: len(headers)])))
        return headers, rows

    raise RuntimeError(f"No importable structured table was found in: {docx_path}")


def write_rows_to_sqlite(db_path: str, table_name: str, headers: list[str], rows: list[dict[str, object]]) -> None:
    column_defs = ", ".join(f'"{column}" TEXT' for column in headers)
    placeholders = ", ".join("?" for _ in headers)
    quoted_columns = ", ".join(f'"{column}"' for column in headers)
    insert_sql = f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        cursor.execute(f'CREATE TABLE "{table_name}" ({column_defs})')
        cursor.executemany(insert_sql, [[row.get(column) for column in headers] for row in rows])
        conn.commit()


def prepare_fact_db() -> Dict[str, object]:
    kb_dir = resolve_path("data/knowledge_base")
    docx_path = find_structured_docx(kb_dir)
    db_path = resolve_path("data/processed/tourist_behavior.db")

    headers, rows = load_structured_rows(docx_path)

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    write_rows_to_sqlite(db_path, "attractions", headers, rows)

    merge_runtime_status({"behavior_db_ready": os.path.exists(db_path)})
    return {
        "ok": True,
        "table": "attractions",
        "rows": len(rows),
        "db_path": db_path,
        "source_docx": str(docx_path),
    }
