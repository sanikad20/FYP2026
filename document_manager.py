"""
document_manager.py — Document Lifecycle, Versioning, and Cache Invalidation (Week 4)

Manages:
- Document approval and rejection workflows.
- Version promotion and active version management (superseding older versions).
- Document archiving and deactivation.
- CacheMind semantic cache invalidation on document updates.
- ChromaDB metadata synchronization (ensures unapproved or archived chunks are never retrieved).
- Comprehensive audit logging and administrative queries.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


class DocumentManager:
    """
    Coordinates document status changes, version lifecycle,
    vector database synchronization, and cache invalidation.
    """

    def __init__(self, db_connection_factory=None, vector_db=None, prefetch_engine=None):
        self.get_db_conn = db_connection_factory
        self.vector_db = vector_db
        self.prefetch_engine = prefetch_engine

    def list_documents(
        self,
        search: Optional[str] = None,
        approval_status: Optional[str] = None,
        upload_source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List documents with optional search and filters."""
        if not self.get_db_conn:
            return {"documents": [], "total": 0}

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            query = """
                SELECT 
                    d.id, d.doc_code, d.title, d.source_url, d.upload_source, 
                    d.uploaded_by, d.visibility, d.approval_status, d.is_active, 
                    d.created_at, d.updated_at,
                    v.id AS version_id, v.version_number, v.file_name, v.file_size, 
                    v.extracted_text_len, v.chunk_count, v.storage_path
                FROM documents d
                LEFT JOIN document_versions v ON v.id = d.current_version_id
                WHERE 1=1
            """
            params: List[Any] = []

            if search:
                query += " AND (d.title ILIKE %s OR d.doc_code ILIKE %s OR v.file_name ILIKE %s)"
                term = f"%{search.strip()}%"
                params.extend([term, term, term])

            if approval_status and approval_status != "all":
                query += " AND d.approval_status = %s"
                params.append(approval_status)

            if upload_source and upload_source != "all":
                query += " AND d.upload_source = %s"
                params.append(upload_source)

            # Count total matching
            count_query = f"SELECT COUNT(*) FROM ({query}) AS total_query;"
            cur.execute(count_query, params)
            total = cur.fetchone()[0]

            query += " ORDER BY d.updated_at DESC LIMIT %s OFFSET %s;"
            params.extend([limit, offset])

            cur.execute(query, params)
            rows = cur.fetchall()

            docs = []
            for r in rows:
                docs.append({
                    "id": r[0],
                    "doc_code": r[1],
                    "title": r[2],
                    "source_url": r[3],
                    "upload_source": r[4],
                    "uploaded_by": r[5],
                    "visibility": r[6],
                    "approval_status": r[7],
                    "is_active": r[8],
                    "created_at": r[9].isoformat() if r[9] else None,
                    "updated_at": r[10].isoformat() if r[10] else None,
                    "current_version": {
                        "id": r[11],
                        "version_number": r[12],
                        "file_name": r[13],
                        "file_size": r[14],
                        "extracted_text_len": r[15],
                        "chunk_count": r[16],
                        "storage_path": r[17],
                    } if r[11] else None,
                })

            return {"documents": docs, "total": total}
        finally:
            cur.close()
            conn.close()

    def get_document_details(self, document_id: int) -> Optional[Dict[str, Any]]:
        """Fetch complete document metadata including all version history and audit logs."""
        if not self.get_db_conn:
            return None

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, doc_code, title, description, source_url, upload_source, 
                       uploaded_by, visibility, approval_status, is_active, 
                       current_version_id, created_at, updated_at
                FROM documents 
                WHERE id = %s;
            """, (document_id,))
            d = cur.fetchone()
            if not d:
                return None

            doc_info = {
                "id": d[0],
                "doc_code": d[1],
                "title": d[2],
                "description": d[3],
                "source_url": d[4],
                "upload_source": d[5],
                "uploaded_by": d[6],
                "visibility": d[7],
                "approval_status": d[8],
                "is_active": d[9],
                "current_version_id": d[10],
                "created_at": d[11].isoformat() if d[11] else None,
                "updated_at": d[12].isoformat() if d[12] else None,
            }

            # Fetch versions
            cur.execute("""
                SELECT id, version_number, file_hash, file_name, file_size, 
                       mime_type, storage_path, approval_status, is_active, 
                       extracted_text_len, chunk_count, uploaded_by, approved_by, 
                       approved_at, rejection_reason, created_at
                FROM document_versions
                WHERE document_id = %s
                ORDER BY version_number DESC;
            """, (document_id,))
            v_rows = cur.fetchall()
            versions = []
            for v in v_rows:
                versions.append({
                    "id": v[0],
                    "version_number": v[1],
                    "file_hash": v[2],
                    "file_name": v[3],
                    "file_size": v[4],
                    "mime_type": v[5],
                    "storage_path": v[6],
                    "approval_status": v[7],
                    "is_active": v[8],
                    "extracted_text_len": v[9],
                    "chunk_count": v[10],
                    "uploaded_by": v[11],
                    "approved_by": v[12],
                    "approved_at": v[13].isoformat() if v[13] else None,
                    "rejection_reason": v[14],
                    "created_at": v[15].isoformat() if v[15] else None,
                })
            doc_info["versions"] = versions

            # Fetch audit logs
            cur.execute("""
                SELECT id, action, performed_by, details, created_at
                FROM document_audit_logs
                WHERE document_id = %s
                ORDER BY created_at DESC
                LIMIT 20;
            """, (document_id,))
            a_rows = cur.fetchall()
            audits = []
            for a in a_rows:
                audits.append({
                    "id": a[0],
                    "action": a[1],
                    "performed_by": a[2],
                    "details": a[3],
                    "created_at": a[4].isoformat() if a[4] else None,
                })
            doc_info["audit_logs"] = audits

            return doc_info
        finally:
            cur.close()
            conn.close()

    def approve_document(
        self,
        document_id: int,
        approved_by: str = "admin",
        version_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Approve document or specific version.
        - Sets approved version to is_active=True, approval_status='approved'.
        - Sets older versions of this document to is_active=False.
        - Synchronizes ChromaDB metadata so newly approved chunks become retrievable.
        - Invalidates CacheMind entries related to this document.
        - Records audit log.
        """
        if not self.get_db_conn:
            return {"status": "ok"}

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            # 1. Fetch document title and target version
            cur.execute("SELECT title, doc_code, current_version_id FROM documents WHERE id = %s;", (document_id,))
            doc_row = cur.fetchone()
            if not doc_row:
                raise ValueError(f"Document with ID {document_id} not found")
            doc_title, doc_code, cur_v_id = doc_row

            target_v_id = version_id or cur_v_id
            if not target_v_id:
                # Find latest version
                cur.execute("SELECT id FROM document_versions WHERE document_id = %s ORDER BY version_number DESC LIMIT 1;", (document_id,))
                target_v_id = cur.fetchone()[0]

            # 2. Deactivate older versions in DB
            cur.execute("""
                UPDATE document_versions 
                SET is_active = FALSE 
                WHERE document_id = %s AND id != %s;
            """, (document_id, target_v_id))

            # 3. Activate target version
            cur.execute("""
                UPDATE document_versions 
                SET approval_status = 'approved',
                    is_active = TRUE,
                    approved_by = %s,
                    approved_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING version_number, file_name;
            """, (approved_by, target_v_id))
            v_num, filename = cur.fetchone()

            # 4. Update documents master row
            cur.execute("""
                UPDATE documents 
                SET approval_status = 'approved',
                    is_active = TRUE,
                    current_version_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """, (target_v_id, document_id))

            # 5. Log audit
            cur.execute("""
                INSERT INTO document_audit_logs (document_id, version_id, action, performed_by, details)
                VALUES (%s, %s, %s, %s, %s);
            """, (document_id, target_v_id, "approved", approved_by, json.dumps({
                "version_number": v_num,
                "filename": filename,
                "timestamp": datetime.now().isoformat(),
            })))

            conn.commit()

            # 6. Synchronize ChromaDB metadata
            self._sync_chroma_approval(document_id, target_v_id)

            # 7. Invalidate CacheMind entries referencing this document
            invalidated = 0
            if self.prefetch_engine:
                invalidated = self.prefetch_engine.invalidate_for_document(
                    document_title=doc_title,
                    keywords=[filename, doc_code],
                )

            print(f"✅ Document {document_id} ('{doc_title}') APPROVED by {approved_by}. "
                  f"Active Version: {v_num}. Invalidated {invalidated} cache entries.")

            return {
                "status": "success",
                "document_id": document_id,
                "version_id": target_v_id,
                "version_number": v_num,
                "title": doc_title,
                "approval_status": "approved",
                "is_active": True,
                "cache_entries_invalidated": invalidated,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def reject_document(
        self,
        document_id: int,
        reason: str = "Rejected by administrator",
        rejected_by: str = "admin",
        version_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Reject document or version."""
        if not self.get_db_conn:
            return {"status": "ok"}

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            target_v_id = version_id
            if not target_v_id:
                cur.execute("SELECT current_version_id FROM documents WHERE id = %s;", (document_id,))
                r = cur.fetchone()
                target_v_id = r[0] if r else None

            # Mark version rejected
            if target_v_id:
                cur.execute("""
                    UPDATE document_versions 
                    SET approval_status = 'rejected',
                        is_active = FALSE,
                        rejection_reason = %s
                    WHERE id = %s;
                """, (reason, target_v_id))

            # Mark document rejected
            cur.execute("""
                UPDATE documents 
                SET approval_status = 'rejected',
                    is_active = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING title;
            """, (document_id,))
            title = cur.fetchone()[0]

            # Audit log
            cur.execute("""
                INSERT INTO document_audit_logs (document_id, version_id, action, performed_by, details)
                VALUES (%s, %s, %s, %s, %s);
            """, (document_id, target_v_id, "rejected", rejected_by, json.dumps({
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
            })))

            conn.commit()

            # Deactivate in ChromaDB
            self._deactivate_document_in_chroma(document_id)

            return {
                "status": "success",
                "document_id": document_id,
                "title": title,
                "approval_status": "rejected",
                "is_active": False,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def archive_document(self, document_id: int, archived_by: str = "admin") -> Dict[str, Any]:
        """Archive a document, preventing its retrieval by the public chatbot."""
        if not self.get_db_conn:
            return {"status": "ok"}

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE documents 
                SET approval_status = 'archived',
                    is_active = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING title;
            """, (document_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Document {document_id} not found")
            title = row[0]

            cur.execute("UPDATE document_versions SET is_active = FALSE WHERE document_id = %s;", (document_id,))

            cur.execute("""
                INSERT INTO document_audit_logs (document_id, action, performed_by, details)
                VALUES (%s, %s, %s, %s);
            """, (document_id, "archived", archived_by, json.dumps({"timestamp": datetime.now().isoformat()})))

            conn.commit()

            # Deactivate in ChromaDB
            self._deactivate_document_in_chroma(document_id)

            # Invalidate Cache
            if self.prefetch_engine:
                self.prefetch_engine.invalidate_for_document(title)

            return {
                "status": "success",
                "document_id": document_id,
                "title": title,
                "approval_status": "archived",
                "is_active": False,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Return system document overview statistics."""
        if not self.get_db_conn:
            return {}

        conn = self.get_db_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT 
                    COUNT(*) AS total_documents,
                    COUNT(*) FILTER (WHERE approval_status = 'approved' AND is_active = TRUE) AS active_approved,
                    COUNT(*) FILTER (WHERE approval_status = 'pending') AS pending_approval,
                    COUNT(*) FILTER (WHERE approval_status = 'rejected') AS rejected,
                    COUNT(*) FILTER (WHERE approval_status = 'archived') AS archived
                FROM documents;
            """)
            r = cur.fetchone()

            cur.execute("SELECT COUNT(*) FROM document_versions;")
            total_versions = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM document_chunks;")
            total_chunks = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM document_sync_sources WHERE is_enabled = TRUE;")
            active_sync_sources = cur.fetchone()[0]

            return {
                "total_documents": r[0],
                "active_approved": r[1],
                "pending_approval": r[2],
                "rejected": r[3],
                "archived": r[4],
                "total_versions": total_versions,
                "total_chunks": total_chunks,
                "active_sync_sources": active_sync_sources,
            }
        finally:
            cur.close()
            conn.close()

    def _sync_chroma_approval(self, document_id: int, active_version_id: int):
        """Update ChromaDB chunk metadata: active version is set to approved=True, is_active=True."""
        if not self.vector_db:
            return

        try:
            # Query all chunks for this document in ChromaDB
            col = self.vector_db._collection
            records = col.get(where={"document_id": document_id})
            if not records or not records.get("ids"):
                return

            ids = records["ids"]
            metas = records["metadatas"]

            updated_ids = []
            updated_metas = []

            for cid, meta in zip(ids, metas):
                is_target_version = (meta.get("version_id") == active_version_id)
                meta["is_active"] = bool(is_target_version)
                meta["approval_status"] = "approved" if is_target_version else "superseded"
                updated_ids.append(cid)
                updated_metas.append(meta)

            if updated_ids:
                col.update(ids=updated_ids, metadatas=updated_metas)
                print(f"🔄 Updated {len(updated_ids)} ChromaDB chunks for Doc ID {document_id}")
        except Exception as e:
            print(f"⚠️ ChromaDB approval sync notice: {e}")

    def _deactivate_document_in_chroma(self, document_id: int):
        """Mark all chunks for this document as is_active=False in ChromaDB."""
        if not self.vector_db:
            return
        try:
            col = self.vector_db._collection
            records = col.get(where={"document_id": document_id})
            if not records or not records.get("ids"):
                return
            ids = records["ids"]
            metas = records["metadatas"]
            for m in metas:
                m["is_active"] = False
                m["approval_status"] = "inactive"
            col.update(ids=ids, metadatas=metas)
        except Exception as e:
            print(f"⚠️ ChromaDB deactivation notice: {e}")
