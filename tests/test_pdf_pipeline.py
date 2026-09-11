from pathlib import Path

import pymupdf

from src.chunker import Chunk, chunk_document
from src.pdf_parser import parse_pdf
from src.vector_store import VectorStore


def _make_pdf(path: Path) -> None:
    document = pymupdf.open()
    for text in (
        "# Revenue\nTSMC revenue was 100 billion.",
        "# Margin\nGross margin was 60 percent.",
    ):
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_parser_preserves_original_filename_and_exact_pages(tmp_path):
    path = tmp_path / "stored-hash.pdf"
    _make_pdf(path)
    parsed = parse_pdf(path, original_filename="TSMC 2025 Annual Report.pdf")
    assert parsed.filename == "TSMC 2025 Annual Report.pdf"
    assert parsed.total_pages == 2
    assert {section["page"] for section in parsed.text_sections} == {1, 2}


def test_chunks_keep_exact_page_provenance(tmp_path):
    path = tmp_path / "report.pdf"
    _make_pdf(path)
    chunks = chunk_document(parse_pdf(path, original_filename="original.pdf"))
    assert {chunk.page for chunk in chunks} == {1, 2}
    assert all(chunk.source == "original.pdf" for chunk in chunks)


def test_chunk_ids_are_deterministic(tmp_path):
    path = tmp_path / "report.pdf"
    _make_pdf(path)
    parsed = parse_pdf(path, original_filename="original.pdf")
    first = [chunk.chunk_id for chunk in chunk_document(parsed)]
    second = [chunk.chunk_id for chunk in chunk_document(parsed)]
    assert first == second


class _FakeEmbeddings:
    @staticmethod
    def get_embeddings(texts):
        return [[float(index + 1), 0.0, 0.0] for index, _ in enumerate(texts)]

    @staticmethod
    def get_embedding(_text):
        return [1.0, 0.0, 0.0]


def test_vector_upsert_is_idempotent(tmp_path):
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf)
    chunks = chunk_document(parse_pdf(pdf, original_filename="original.pdf"))
    store = VectorStore(persist_dir=tmp_path / "chroma")
    store._embed_model = _FakeEmbeddings()
    store.add_chunks(chunks)
    store.add_chunks(chunks)
    stats = store.get_stats()
    assert stats["text_chunks"] == len([c for c in chunks if c.chunk_type == "text"])


def test_vector_upsert_deduplicates_ids_within_one_batch(tmp_path):
    pdf = tmp_path / "report.pdf"
    _make_pdf(pdf)
    chunks = chunk_document(parse_pdf(pdf, original_filename="original.pdf"))
    duplicate_batch = [chunks[0], chunks[0], *chunks[1:]]
    store = VectorStore(persist_dir=tmp_path / "duplicate-chroma")
    store._embed_model = _FakeEmbeddings()
    added = store.add_chunks(duplicate_batch)
    assert added == len({chunk.chunk_id for chunk in chunks})
    assert store.get_stats()["text_chunks"] == len({chunk.chunk_id for chunk in chunks})


def test_vector_upsert_normalizes_tuple_metadata(tmp_path):
    store = VectorStore(persist_dir=tmp_path / "metadata-chroma")
    store._embed_model = _FakeEmbeddings()
    table = Chunk(
        chunk_id="table-1",
        text="| Metric | Value |",
        chunk_type="table",
        source="report.pdf",
        page=1,
        metadata={"bbox": (0, 0, 100, 100)},
    )
    assert store.add_chunks([table]) == 1
    metadata = store.table_collection.get(ids=["table-1"], include=["metadatas"])["metadatas"][0]
    assert metadata["bbox"] == [0, 0, 100, 100]


def test_empty_vector_collection_does_not_load_embedding(tmp_path):
    store = VectorStore(persist_dir=tmp_path / "empty-chroma")

    class FailIfCalled:
        @staticmethod
        def get_embedding(_text):
            raise AssertionError("embedding should not be loaded for an empty collection")

    store._embed_model = FailIfCalled()
    assert store.search_texts("anything") == []
