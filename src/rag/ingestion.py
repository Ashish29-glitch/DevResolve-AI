"""Document ingestion - adapted from RunbookPilot for DevResolve AI"""
from pathlib import Path
from typing import List
from uuid import NAMESPACE_URL, uuid5
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from docx import Document as DocxDocument
from src.rag.vectorstore import get_vector_store

SUPPORTED = {".pdf", ".txt", ".md", ".docx"}


def _load_docx(path: Path) -> List[Document]:
    doc = DocxDocument(path)
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [Document(page_content=text, metadata={"source": str(path), "title": path.name})]


def load_file(path: Path) -> List[Document]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        docs = PyPDFLoader(str(path)).load()
    elif ext in {".txt", ".md"}:
        docs = TextLoader(str(path), encoding="utf-8").load()
    elif ext == ".docx":
        docs = _load_docx(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    for d in docs:
        d.metadata.setdefault("source", str(path))
        d.metadata.setdefault("title", path.name)
        d.metadata["document_name"] = path.name
    return docs


def _stable_chunk_id(path: Path, chunk: Document, position: int) -> str:
    material = f"{path.name}|{position}|{chunk.page_content}"
    return str(uuid5(NAMESPACE_URL, material))


def ingest_file(path: Path, project_id: int = None) -> int:
    docs = load_file(path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=160,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i
        if project_id:
            chunk.metadata["project_id"] = str(project_id)
    ids = [_stable_chunk_id(path, chunk, i) for i, chunk in enumerate(chunks)]
    get_vector_store().add_documents(chunks, ids=ids)
    return len(chunks)
