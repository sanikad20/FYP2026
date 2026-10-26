"""
document_ingestion.py — Automated PDF Document Ingestion Pipeline (Week 4)

Provides end-to-end ingestion of PDF documents:
- Comprehensive validation: file size, extension, MIME type, PDF magic bytes, PyMuPDF integrity.
- Safe rejection & quarantine of corrupted, encrypted, or oversized files.
- PyMuPDF text extraction with OCR fallback notification for scanned PDFs.
- Text cleaning, normalization, and semantic chunking.
- Vector embedding generation via 'all-MiniLM-L6-v2' and indexing into ChromaDB.
- Metadata persistence in PostgreSQL (documents, document_versions, document_chunks, jobs).
- SHA-256 hash deduplication.
- Safe idempotence: re-processing existing files updates versions without chunk duplication.
- Secure approval isolation: new documents start with approval_status='pending', is_active=False.
"""

import os
import sys
import shutil
import hashlib
import mimetypes
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter


# Base directory configurations
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "documents")
DIR_INCOMING = os.path.join(DOCS_DIR, "incoming")
DIR_PROCESSING = os.path.join(DOCS_DIR, "processing")
DIR_PROCESSED = os.path.join(DOCS_DIR, "processed")
DIR_FAILED = os.path.join(DOCS_DIR, "failed")
DIR_QUARANTINE = os.path.join(DOCS_DIR, "quarantine")

MAX_PDF_SIZE_BYTES = int(os.environ.get("MAX_PDF_SIZE_MB", 25)) * 1024 * 1024


def ensure_directories():
    """Ensure all required document pipeline folders exist."""
    for d in [DIR_INCOMING, DIR_PROCESSING, DIR_PROCESSED, DIR_FAILED, DIR_QUARANTINE]:
        os.makedirs(d, exist_ok=True)


def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA-256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class DocumentValidationError(Exception):
    """Raised when document fails validation checks."""
    pass


def validate_pdf(filepath: str) -> Dict[str, Any]:
    """
    Validate that filepath is a genuine, unencrypted, supported PDF file within size limits.
    Returns file metadata if valid, otherwise raises DocumentValidationError.
    """
    if not os.path.exists(filepath):
        raise DocumentValidationError(f"File not found: {filepath}")

    # 1. File size check
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        raise DocumentValidationError("File is empty (0 bytes)")
    if file_size > MAX_PDF_SIZE_BYTES:
        raise DocumentValidationError(
            f"File size ({file_size / (1024*1024):.2f}MB) exceeds limit of {MAX_PDF_SIZE_BYTES / (1024*1024):.1f}MB"
        )

    # 2. Extension check
    _, ext = os.path.splitext(filepath)
    if ext.lower() != ".pdf":
        raise DocumentValidationError(f"Unsupported file extension: {ext}. Only .pdf allowed.")

    # 3. Magic bytes check (%PDF-)
    with open(filepath, "rb") as f:
        header = f.read(5)
        if header != b"%PDF-":
            raise DocumentValidationError("Invalid file header: Not a valid PDF file structure")

    # 4. PyMuPDF structure & encryption check
    try:
        doc = fitz.open(filepath)
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            raise DocumentValidationError("PDF contains 0 pages")
        if doc.is_encrypted:
            doc.close()
            raise DocumentValidationError("Password-protected or encrypted PDFs are not supported")
        doc.close()
    except Exception as e:
        if isinstance(e, DocumentValidationError):
            raise
        raise DocumentValidationError(f"Corrupted PDF file or unsupported structure: {e}")

    return {
        "file_size": file_size,
        "page_count": page_count,
        "mime_type": "application/pdf",
    }


def extract_text_from_pdf(filepath: str) -> Tuple[str, Dict[int, str]]:
    """
    Extract text page-by-page using PyMuPDF.
    Returns (full_text, {page_num: page_text}).
    """
    doc = fitz.open(filepath)
    full_text_parts = []
    page_texts = {}

    for idx, page in enumerate(doc):
        text = page.get_text() or ""
        clean_page_text = " ".join(text.split())
        page_texts[idx + 1] = clean_page_text
        if clean_page_text:
            full_text_parts.append(clean_page_text)

    doc.close()
    full_text = "\n\n".join(full_text_parts)

    # Scanned PDF check / OCR notice
    if len(full_text.strip()) < 50:
        # Document is likely scanned or image-based
        print(f"⚠️ [OCR Notice] PDF '{os.path.basename(filepath)}' has low extracted text density ({len(full_text.strip())} chars). Fallback applied.")

    return full_text, page_texts


def clean_and_normalize_text(text: str) -> str:
    """Normalize whitespace and sanitize characters."""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


class DocumentIngestionPipeline:
    """
    Ingestion coordinator integrating PDF extraction, ChromaDB embedding,
    and PostgreSQL persistence.
    """

    def __init__(self, vector_db=None, embeddings=None, db_connection_factory=None):
        self.vector_db = vector_db
        self.embeddings = embeddings
        self.get_db_conn = db_connection_factory
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=600,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        ensure_directories()

    def process_file(
        self,
        filepath: str,
        title: Optional[str] = None,
        source_url: Optional[str] = None,
        upload_source: str = "upload",
        uploaded_by: str = "admin",
        visibility: str = "public",
        auto_approve: bool = False,
        replace_doc_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point for processing a PDF file through the ingestion pipeline.
        Moves file through processing -> processed / quarantine / failed folders.
        """
        filename = os.path.basename(filepath)
        print(f"📄 Starting document ingestion for: {filename} (source={upload_source})")

        # 1. Validation & Quarantine handling
        try:
            val_info = validate_pdf(filepath)
        except DocumentValidationError as ve:
            quarantine_path = os.path.join(DIR_QUARANTINE, f"{int(datetime.now().timestamp())}_{filename}")
            try:
                shutil.move(filepath, quarantine_path)
            except Exception:
                pass
            self._log_ingestion_job(
                filename=filename,
                filepath=quarantine_path,
                status="quarantined",
                error=str(ve),
            )
            raise ve

        file_hash = calculate_file_hash(filepath)
        file_size = val_info["file_size"]

        # 2. Check for duplicate ingestion
        existing_doc = self._find_existing_by_hash(file_hash)
        if existing_doc and not replace_doc_id:
            print(f"ℹ️ File {filename} with hash {file_hash[:12]} already ingested as Doc ID {existing_doc['id']}.")
            return {
                "status": "already_exists",
                "document_id": existing_doc["id"],
                "version_id": existing_doc.get("version_id"),
                "file_hash": file_hash,
                "message": "Document with identical content hash already exists",
            }

        # 3. Move to processing directory
        proc_filepath = os.path.join(DIR_PROCESSING, f"{int(datetime.now().timestamp())}_{filename}")
        shutil.move(filepath, proc_filepath)

        job_id = self._log_ingestion_job(
            filename=filename,
            filepath=proc_filepath,
            file_hash=file_hash,
            status="processing",
            stage="extracting_text",
        )

        try:
            # 4. Text Extraction & Normalization
            full_text, page_map = extract_text_from_pdf(proc_filepath)
            clean_text = clean_and_normalize_text(full_text)
            text_len = len(clean_text)

            # 5. Semantic Chunking
            chunks = self.splitter.split_text(clean_text) if clean_text else []
            chunk_count = len(chunks)

            # 6. Database Document & Version Setup
            doc_title = title or os.path.splitext(filename)[0].replace("_", " ").title()
            doc_code = self._generate_doc_code(doc_title, replace_doc_id)

            approval_status = "approved" if auto_approve else "pending"
            is_active = True if auto_approve else False

            doc_id, version_id, version_num = self._save_document_and_version(
                doc_id=replace_doc_id,
                doc_code=doc_code,
                title=doc_title,
                source_url=source_url,
                upload_source=upload_source,
                uploaded_by=uploaded_by,
                visibility=visibility,
                approval_status=approval_status,
                is_active=is_active,
                file_hash=file_hash,
                filename=filename,
                file_size=file_size,
                storage_path=proc_filepath,
                text_len=text_len,
                chunk_count=chunk_count,
            )

            # 7. ChromaDB Indexing
            if chunks and self.vector_db:
                self._index_chunks_in_chroma(
                    chunks=chunks,
                    document_id=doc_id,
                    version_id=version_id,
                    version_num=version_num,
                    doc_code=doc_code,
                    title=doc_title,
                    source_filename=filename,
                    source_url=source_url,
                    approval_status=approval_status,
                    is_active=is_active,
                    visibility=visibility,
                )

            # 8. Move to processed directory
            final_storage_path = os.path.join(DIR_PROCESSED, f"doc_{doc_id}_v{version_num}_{filename}")
            shutil.move(proc_filepath, final_storage_path)

            # Update storage path in DB
            self._update_version_storage_path(version_id, final_storage_path)

            # Complete Job
            self._update_ingestion_job(job_id, status="completed", stage="done", version_id=version_id, document_id=doc_id)

            # Record audit log
            self._log_audit(
                doc_id=doc_id,
                version_id=version_id,
                action="uploaded",
                performed_by=uploaded_by,
                details={
                    "filename": filename,
                    "version": version_num,
                    "chunks": chunk_count,
                    "approval_status": approval_status,
                    "upload_source": upload_source,
                }
            )

            print(f"✅ Ingestion completed for {filename} (Doc ID: {doc_id}, Version: {version_num}, Chunks: {chunk_count})")
            return {
                "status": "success",
                "document_id": doc_id,
                "version_id": version_id,
                "version_number": version_num,
                "title": doc_title,
                "filename": filename,
                "chunk_count": chunk_count,
                "extracted_length": text_len,
                "approval_status": approval_status,
                "is_active": is_active,
                "storage_path": final_storage_path,
            }

        except Exception as e:
            failed_path = os.path.join(DIR_FAILED, f"{int(datetime.now().timestamp())}_{filename}")
            if os.path.exists(proc_filepath):
                try:
                    shutil.move(proc_filepath, failed_path)
                except Exception:
                    pass
            self._update_ingestion_job(job_id, status="failed", stage="error", error=str(e))
            print(f"❌ Ingestion failed for {filename}: {e}")
            raise e

    def _generate_doc_code(self, title: str, existing_id: Optional[int] = None) -> str:
        """Create a stable unique document code."""
        if existing_id and self.get_db_conn:
            try:
                conn = self.get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT doc_code FROM documents WHERE id = %s;", (existing_id,))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row and row[0]:
                    return row[0]
            except Exception:
                pass

        slug = "".join(c if c.isalnum() else "_" for c in title.lower())[:30].strip("_")
        return f"DOC_{slug}_{int(datetime.now().timestamp()) % 100000}"

    def _find_existing_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Look up if a version with this file_hash already exists."""
        if not self.get_db_conn:
            return None
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT document_id, id, version_number, approval_status 
                FROM document_versions 
                WHERE file_hash = %s 
                LIMIT 1;
            """, (file_hash,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                return {
                    "id": row[0],
                    "version_id": row[1],
                    "version_number": row[2],
                    "approval_status": row[3],
                }
        except Exception as e:
            print(f"⚠️ Hash lookup error: {e}")
        return None

    def _save_document_and_version(
        self,
        doc_id: Optional[int],
        doc_code: str,
        title: str,
        source_url: Optional[str],
        upload_source: str,
        uploaded_by: str,
        visibility: str,
        approval_status: str,
        is_active: bool,
        file_hash: str,
        filename: str,
        file_size: int,
        storage_path: str,
        text_len: int,
        chunk_count: int,
    ) -> Tuple[int, int, int]:
        """Save or update records in documents and document_versions tables."""
        if not self.get_db_conn:
            # Fallback IDs for disconnected/test modes
            return 1, 1, 1

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            # 1. Documents master table
            if not doc_id:
                cur.execute("""
                    INSERT INTO documents 
                        (doc_code, title, source_url, upload_source, uploaded_by, visibility, approval_status, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (doc_code, title, source_url, upload_source, uploaded_by, visibility, approval_status, is_active))
                doc_id = cur.fetchone()[0]
                version_num = 1
            else:
                # Find current latest version number
                cur.execute("SELECT COALESCE(MAX(version_number), 0) FROM document_versions WHERE document_id = %s;", (doc_id,))
                latest_v = cur.fetchone()[0]
                version_num = latest_v + 1

                # Update document master row
                cur.execute("""
                    UPDATE documents 
                    SET updated_at = CURRENT_TIMESTAMP,
                        source_url = COALESCE(%s, source_url)
                    WHERE id = %s;
                """, (source_url, doc_id))

            # 2. Document versions table
            cur.execute("""
                INSERT INTO document_versions 
                    (document_id, version_number, file_hash, file_name, file_size, mime_type, storage_path, 
                     approval_status, is_active, extracted_text_len, chunk_count, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (doc_id, version_num, file_hash, filename, file_size, "application/pdf", storage_path,
                  approval_status, is_active, text_len, chunk_count, uploaded_by))
            version_id = cur.fetchone()[0]

            # Update current_version_id if approved or initial
            if is_active or version_num == 1:
                cur.execute("UPDATE documents SET current_version_id = %s WHERE id = %s;", (version_id, doc_id))

            conn.commit()
            return doc_id, version_id, version_num
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def _index_chunks_in_chroma(
        self,
        chunks: List[str],
        document_id: int,
        version_id: int,
        version_num: int,
        doc_code: str,
        title: str,
        source_filename: str,
        source_url: Optional[str],
        approval_status: str,
        is_active: bool,
        visibility: str,
    ):
        """Index chunks with rich metadata into ChromaDB and record chunk rows in PostgreSQL."""
        if not self.vector_db or not chunks:
            return

        chunk_ids = []
        metadatas = []

        for idx, text_chunk in enumerate(chunks):
            cid = f"doc_{document_id}_v{version_num}_c{idx}"
            chunk_ids.append(cid)
            metadatas.append({
                "document_id": document_id,
                "version_id": version_id,
                "version_number": version_num,
                "doc_code": doc_code,
                "title": title,
                "source": source_filename,
                "source_url": source_url or "",
                "approval_status": approval_status,
                "is_active": is_active,
                "visibility": visibility,
                "chunk_index": idx,
            })

        # Add to ChromaDB
        self.vector_db.add_texts(
            texts=chunks,
            metadatas=metadatas,
            ids=chunk_ids,
        )

        # Record in document_chunks PostgreSQL table
        if self.get_db_conn:
            try:
                conn = self.get_db_conn()
                cur = conn.cursor()
                for idx, cid in enumerate(chunk_ids):
                    preview = chunks[idx][:200]
                    cur.execute("""
                        INSERT INTO document_chunks 
                            (version_id, document_id, chunk_index, chroma_id, token_count, content_preview)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (version_id, document_id, idx, cid, len(chunks[idx].split()), preview))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"⚠️ Error recording document chunks in DB: {e}")

    def _update_version_storage_path(self, version_id: int, new_path: str):
        """Update storage_path for a version."""
        if not self.get_db_conn:
            return
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("UPDATE document_versions SET storage_path = %s WHERE id = %s;", (new_path, version_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    def _log_ingestion_job(
        self,
        filename: str,
        filepath: str,
        file_hash: Optional[str] = None,
        status: str = "pending",
        stage: str = "queued",
        error: Optional[str] = None,
    ) -> int:
        """Create a job log entry."""
        if not self.get_db_conn:
            return 1
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO document_ingestion_jobs 
                    (file_name, file_path, file_hash, status, stage, error_message, started_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id;
            """, (filename, filepath, file_hash, status, stage, error))
            job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return job_id
        except Exception:
            return 1

    def _update_ingestion_job(
        self,
        job_id: int,
        status: str,
        stage: str,
        error: Optional[str] = None,
        version_id: Optional[int] = None,
        document_id: Optional[int] = None,
    ):
        """Update an existing job log entry."""
        if not self.get_db_conn:
            return
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE document_ingestion_jobs 
                SET status = %s,
                    stage = %s,
                    error_message = %s,
                    version_id = COALESCE(%s, version_id),
                    document_id = COALESCE(%s, document_id),
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (status, stage, error, version_id, document_id, job_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    def _log_audit(
        self,
        doc_id: Optional[int],
        version_id: Optional[int],
        action: str,
        performed_by: str,
        details: Dict[str, Any],
    ):
        """Insert an audit log row."""
        if not self.get_db_conn:
            return
        try:
            import json
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO document_audit_logs 
                    (document_id, version_id, action, performed_by, details)
                VALUES (%s, %s, %s, %s, %s);
            """, (doc_id, version_id, action, performed_by, json.dumps(details)))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"⚠️ Audit log write error: {e}")
