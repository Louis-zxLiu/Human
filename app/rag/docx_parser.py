import os
import uuid
from typing import Any, Dict, List

from app.core.docx_utils import iter_docx_blocks


class DocxParser:
    """
    Parse DOCX files without python-docx/lxml and keep paragraph/table order.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.file_name))

    @staticmethod
    def _table_to_unrolled_rows(rows: List[List[str]], context: str) -> List[str]:
        if len(rows) < 2:
            return []

        headers = [cell.replace("\n", " ").strip() for cell in rows[0]]
        row_texts: List[str] = []
        for row in rows[1:]:
            values = row + [""] * (len(headers) - len(row))
            parts = [f"{headers[i]}: {values[i].replace(chr(10), ' ').strip()}" for i in range(len(headers)) if values[i].strip()]
            if not parts:
                continue
            body = "；".join(parts)
            row_texts.append(f"上下文: {context}\n表格行: {body}".strip() if context else f"表格行: {body}")
        return row_texts

    def parse(self) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        current_context = ""

        for block in iter_docx_blocks(self.file_path):
            if block.kind == "paragraph" and block.text:
                text = block.text.strip()
                if len(text) < 50:
                    current_context = text
                chunks.append(
                    {
                        "content": text,
                        "metadata": {
                            "file_id": self.file_id,
                            "source": self.file_name,
                            "type": "text",
                        },
                    }
                )
            elif block.kind == "table" and block.rows:
                for row_text in self._table_to_unrolled_rows(block.rows, current_context):
                    chunks.append(
                        {
                            "content": row_text,
                            "metadata": {
                                "file_id": self.file_id,
                                "source": self.file_name,
                                "type": "table_row",
                            },
                        }
                    )
                current_context = ""

        return chunks
