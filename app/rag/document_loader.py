import pandas as pd
from langchain.schema import Document as LangChainDocument

from app.core.docx_utils import iter_docx_blocks


def extract_table_markdown(rows, context_str="", chunk_size=300, overlap=50):
    chunks = []
    if not rows:
        return chunks

    header_cells = [cell.replace("\n", " ").strip() for cell in rows[0]]
    header_md = "| " + " | ".join(header_cells) + " |"
    separator_md = "|" + "|".join(["---"] * len(header_cells)) + "|"

    current_chunk_rows = []
    current_length = len(context_str) + len(header_md) + len(separator_md) + 2
    for row in rows[1:]:
        cells = [cell.replace("\n", " ").strip() for cell in row]
        row_md = "| " + " | ".join(cells) + " |"
        if current_length + len(row_md) > chunk_size and current_chunk_rows:
            table_md = "\n".join([header_md, separator_md] + current_chunk_rows)
            chunks.append(f"{context_str}\n{table_md}".strip())
            overlap_rows = current_chunk_rows[-2:] if len(current_chunk_rows) >= 2 else current_chunk_rows
            current_chunk_rows = overlap_rows + [row_md]
            current_length = len(context_str) + len(header_md) + len(separator_md) + sum(len(item) for item in current_chunk_rows)
        else:
            current_chunk_rows.append(row_md)
            current_length += len(row_md)

    if current_chunk_rows:
        table_md = "\n".join([header_md, separator_md] + current_chunk_rows)
        chunks.append(f"{context_str}\n{table_md}".strip())
    return chunks


def load_docx_with_tables(file_path: str, chunk_size=300, overlap=50) -> list[LangChainDocument]:
    documents = []
    current_text = ""
    last_paragraph = ""

    for block in iter_docx_blocks(file_path):
        if block.kind == "paragraph" and block.text:
            text = block.text.strip()
            last_paragraph = text
            if len(current_text) + len(text) > chunk_size:
                documents.append(LangChainDocument(page_content=current_text, metadata={"source": file_path, "type": "text"}))
                current_text = current_text[-overlap:] + "\n" + text if len(current_text) > overlap else text
            else:
                current_text += "\n" + text if current_text else text
        elif block.kind == "table" and block.rows:
            if current_text:
                documents.append(LangChainDocument(page_content=current_text, metadata={"source": file_path, "type": "text"}))
                current_text = ""
            for table_chunk in extract_table_markdown(block.rows, context_str=last_paragraph, chunk_size=chunk_size, overlap=overlap):
                documents.append(LangChainDocument(page_content=table_chunk, metadata={"source": file_path, "type": "table"}))

    if current_text:
        documents.append(LangChainDocument(page_content=current_text, metadata={"source": file_path, "type": "text"}))
    return documents


def load_excel(file_path: str, chunk_size=300, overlap=50) -> list[LangChainDocument]:
    documents = []
    xls = pd.ExcelFile(file_path)
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet_name).fillna("")

        header_md = "| " + " | ".join([str(col) for col in df.columns]) + " |"
        separator_md = "|" + "|".join(["---"] * len(df.columns)) + "|"
        current_chunk_rows = []
        current_length = len(header_md) + len(separator_md) + len(sheet_name) + 10

        for _, row in df.iterrows():
            cells = [str(value).replace("\n", " ") for value in row.values]
            row_md = "| " + " | ".join(cells) + " |"
            if current_length + len(row_md) > chunk_size and current_chunk_rows:
                table_md = "\n".join([header_md, separator_md] + current_chunk_rows)
                documents.append(LangChainDocument(page_content=f"Sheet: {sheet_name}\n{table_md}", metadata={"source": file_path, "type": "excel"}))
                overlap_rows = current_chunk_rows[-2:] if len(current_chunk_rows) >= 2 else current_chunk_rows
                current_chunk_rows = overlap_rows + [row_md]
                current_length = len(header_md) + len(separator_md) + sum(len(item) for item in current_chunk_rows)
            else:
                current_chunk_rows.append(row_md)
                current_length += len(row_md)

        if current_chunk_rows:
            table_md = "\n".join([header_md, separator_md] + current_chunk_rows)
            documents.append(LangChainDocument(page_content=f"Sheet: {sheet_name}\n{table_md}", metadata={"source": file_path, "type": "excel"}))

    return documents
