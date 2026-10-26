"""
sync_service.py — Automatic VJTI Website Synchronization Service (Week 4)

Monitors approved VJTI college website pages (academic notices, circulars, admissions, calendars)
for newly published or updated PDF documents:
- Respects strict security: Only allowlisted HTTPS domain (vjti.ac.in), SSRF prevention,
  rate limits, size limits, and timeout protection.
- Resolves relative URLs safely.
- Detects new and modified documents using SHA-256 hashes against PostgreSQL document_versions.
- Downloads new/modified PDFs and dispatches them through DocumentIngestionPipeline.
- Records synchronization status in document_sync_sources and document_sync_history.
- Scheduler using APScheduler (configurable via SYNC_INTERVAL_HOURS, default 6 hours).
- Can run embedded in Flask or standalone via: python sync_service.py
"""

import os
import sys
import time
import socket
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List, Optional, Set, Tuple
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler


ALLOWED_DOMAINS = ["vjti.ac.in", "www.vjti.ac.in"]
MAX_DOWNLOAD_SIZE_BYTES = int(os.environ.get("MAX_PDF_SIZE_MB", 25)) * 1024 * 1024
DEFAULT_SYNC_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", 6))
REQUEST_TIMEOUT_SEC = 10
RATE_LIMIT_DELAY_SEC = 1.0


def is_safe_url(url: str) -> bool:
    """
    Validate that the URL belongs strictly to approved VJTI HTTPS domains
    and does NOT target internal or private network IP addresses (SSRF defense).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https":
            return False

        hostname = (parsed.hostname or "").lower()
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in ALLOWED_DOMAINS):
            return False

        # Resolve IP to verify it's not a private or loopback address
        ip_addr = socket.gethostbyname(hostname)
        octets = [int(o) for o in ip_addr.split(".")]
        # 127.x.x.x, 10.x.x.x, 192.168.x.x, 172.16-31.x.x, 169.254.x.x
        if octets[0] == 127 or octets[0] == 10:
            return False
        if octets[0] == 192 and octets[1] == 168:
            return False
        if octets[0] == 172 and (16 <= octets[1] <= 31):
            return False
        if octets[0] == 169 and octets[1] == 254:
            return False
        return True
    except Exception:
        return False


class VJTIWebsiteSyncService:
    """
    Automated discovery and ingestion of public VJTI college PDFs.
    """

    def __init__(self, db_connection_factory=None, ingestion_pipeline=None):
        self.get_db_conn = db_connection_factory
        self.ingestion_pipeline = ingestion_pipeline
        self.scheduler = BackgroundScheduler(daemon=True)
        self.is_running = False
        self._sync_in_progress = False

    def start_scheduler(self, interval_hours: Optional[int] = None):
        """Start the background scheduler."""
        hours = interval_hours or DEFAULT_SYNC_HOURS
        if not self.is_running:
            self.scheduler.add_job(
                self.sync_all_sources,
                "interval",
                hours=hours,
                id="vjti_website_sync_job",
                replace_existing=True,
            )
            self.scheduler.start()
            self.is_running = True
            print(f"🌐 VJTI Website Synchronization Scheduler started (interval={hours}h).")

    def stop_scheduler(self):
        """Stop background scheduler."""
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            print("🌐 VJTI Website Synchronization Scheduler stopped.")

    def get_status(self) -> Dict[str, Any]:
        """Return synchronization service health and job status."""
        last_history = self._get_latest_history()
        return {
            "scheduler_running": self.is_running,
            "sync_in_progress": self._sync_in_progress,
            "interval_hours": DEFAULT_SYNC_HOURS,
            "allowed_domains": ALLOWED_DOMAINS,
            "last_sync": last_history,
        }

    def _get_latest_history(self) -> Optional[Dict[str, Any]]:
        """Fetch the most recent sync history record."""
        if not self.get_db_conn:
            return None
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, source_url, docs_found, docs_downloaded, docs_updated, status, started_at, completed_at
                FROM document_sync_history 
                ORDER BY started_at DESC LIMIT 1;
            """)
            r = cur.fetchone()
            cur.close()
            conn.close()
            if r:
                return {
                    "id": r[0],
                    "source_url": r[1],
                    "docs_found": r[2],
                    "docs_downloaded": r[3],
                    "docs_updated": r[4],
                    "status": r[5],
                    "started_at": r[6].isoformat() if r[6] else None,
                    "completed_at": r[7].isoformat() if r[7] else None,
                }
        except Exception:
            pass
        return None

    def get_sources(self) -> List[Dict[str, Any]]:
        """List configured sync sources from database."""
        if not self.get_db_conn:
            return []
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, category, source_url, is_enabled, check_interval_minutes, last_checked_at, last_status, error_count
                FROM document_sync_sources
                ORDER BY id ASC;
            """)
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [{
                "id": r[0],
                "name": r[1],
                "category": r[2],
                "source_url": r[3],
                "is_enabled": r[4],
                "check_interval_minutes": r[5],
                "last_checked_at": r[6].isoformat() if r[6] else None,
                "last_status": r[7],
                "error_count": r[8],
            } for r in rows]
        except Exception as e:
            print(f"⚠️ Error loading sync sources: {e}")
            return []

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return historical sync cycles."""
        if not self.get_db_conn:
            return []
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT h.id, h.source_id, s.name, h.source_url, h.docs_found, 
                       h.docs_downloaded, h.docs_updated, h.status, h.error_message, h.started_at, h.completed_at
                FROM document_sync_history h
                LEFT JOIN document_sync_sources s ON s.id = h.source_id
                ORDER BY h.started_at DESC LIMIT %s;
            """, (limit,))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [{
                "id": r[0],
                "source_id": r[1],
                "source_name": r[2] or "All Sources",
                "source_url": r[3],
                "docs_found": r[4],
                "docs_downloaded": r[5],
                "docs_updated": r[6],
                "status": r[7],
                "error_message": r[8],
                "started_at": r[9].isoformat() if r[9] else None,
                "completed_at": r[10].isoformat() if r[10] else None,
            } for r in rows]
        except Exception as e:
            print(f"⚠️ Error fetching sync history: {e}")
            return []

    def sync_all_sources(self) -> Dict[str, Any]:
        """Execute a full synchronization cycle across all enabled sources."""
        if self._sync_in_progress:
            return {"status": "in_progress", "message": "A sync cycle is already actively executing"}

        self._sync_in_progress = True
        total_found = 0
        total_downloaded = 0
        total_updated = 0
        results = []

        sources = [s for s in self.get_sources() if s["is_enabled"]]
        print(f"🌐 Starting VJTI sync cycle across {len(sources)} active sources...")

        try:
            for src in sources:
                res = self.sync_source(src["id"], src["source_url"], src["name"])
                results.append(res)
                total_found += res.get("docs_found", 0)
                total_downloaded += res.get("docs_downloaded", 0)
                total_updated += res.get("docs_updated", 0)
                time.sleep(RATE_LIMIT_DELAY_SEC)

            # Record overall history
            self._record_history(
                source_id=None,
                source_url="All Enabled Sources",
                docs_found=total_found,
                docs_downloaded=total_downloaded,
                docs_updated=total_updated,
                status="completed",
            )
            return {
                "status": "success",
                "sources_checked": len(sources),
                "total_found": total_found,
                "total_downloaded": total_downloaded,
                "total_updated": total_updated,
                "details": results,
            }
        except Exception as e:
            self._record_history(
                source_id=None,
                source_url="All Enabled Sources",
                docs_found=total_found,
                docs_downloaded=total_downloaded,
                docs_updated=total_updated,
                status="failed",
                error_message=str(e),
            )
            return {"status": "error", "error": str(e)}
        finally:
            self._sync_in_progress = False

    def sync_source(self, source_id: int, source_url: str, source_name: str) -> Dict[str, Any]:
        """
        Check a single approved VJTI URL, discover PDF links, download new/modified files,
        and ingest them.
        """
        print(f"🔍 Syncing source [{source_id}]: {source_name} ({source_url})")

        if not is_safe_url(source_url):
            self._update_source_status(source_id, status="invalid_url", error=True)
            return {"source_id": source_id, "status": "rejected_unsafe_url", "docs_found": 0}

        headers = {
            "User-Agent": "VJTI-CampusChat-SyncBot/1.0 (Official Academic Portal Ingestion; +https://vjti.ac.in)",
        }

        docs_found = 0
        docs_downloaded = 0
        docs_updated = 0
        error_msg = None

        try:
            resp = requests.get(source_url, headers=headers, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code} from source page")

            soup = BeautifulSoup(resp.text, "html.parser")
            pdf_links = self._extract_pdf_links(soup, source_url)
            docs_found = len(pdf_links)
            print(f"   Found {docs_found} PDF link(s) on page.")

            # Process discovered PDF links
            from document_ingestion import DIR_INCOMING
            os.makedirs(DIR_INCOMING, exist_ok=True)

            for pdf_url, link_text in pdf_links:
                if not is_safe_url(pdf_url):
                    continue

                time.sleep(0.5)  # Politeness delay
                download_res = self._download_and_ingest_pdf(
                    pdf_url=pdf_url,
                    link_text=link_text,
                    source_url=source_url,
                    category=source_name,
                )
                if download_res.get("action") == "downloaded":
                    docs_downloaded += 1
                elif download_res.get("action") == "updated":
                    docs_updated += 1

            self._update_source_status(source_id, status="success", error=False)
            status_str = "completed"

        except Exception as e:
            error_msg = str(e)
            status_str = "failed"
            self._update_source_status(source_id, status="error", error=True)
            print(f"⚠️ Error syncing source {source_id}: {e}")

        # Record source history
        self._record_history(
            source_id=source_id,
            source_url=source_url,
            docs_found=docs_found,
            docs_downloaded=docs_downloaded,
            docs_updated=docs_updated,
            status=status_str,
            error_message=error_msg,
        )

        return {
            "source_id": source_id,
            "source_name": source_name,
            "docs_found": docs_found,
            "docs_downloaded": docs_downloaded,
            "docs_updated": docs_updated,
            "status": status_str,
            "error": error_msg,
        }

    def _extract_pdf_links(self, soup: BeautifulSoup, base_url: str) -> List[Tuple[str, str]]:
        """Extract and resolve all .pdf hrefs safely."""
        links: List[Tuple[str, str]] = []
        seen = set()

        for a in soup.find_all("a", href=True):
            raw_href = a["href"].strip()
            if not raw_href or raw_href.startswith("#") or raw_href.startswith("javascript:"):
                continue

            resolved_url = urllib.parse.urljoin(base_url, raw_href)
            # Normalize and strip queries/fragments for link matching
            parsed = urllib.parse.urlparse(resolved_url)
            if parsed.path.lower().endswith(".pdf"):
                clean_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                if clean_url not in seen and is_safe_url(clean_url):
                    seen.add(clean_url)
                    link_title = a.get_text().strip() or os.path.basename(parsed.path)
                    links.append((clean_url, link_title))

        return links

    def _download_and_ingest_pdf(
        self,
        pdf_url: str,
        link_text: str,
        source_url: str,
        category: str,
    ) -> Dict[str, Any]:
        """Download remote PDF into staging, check content hash, and ingest."""
        from document_ingestion import DIR_INCOMING
        headers = {"User-Agent": "VJTI-CampusChat-SyncBot/1.0"}

        try:
            # HEAD request to check content length
            head_resp = requests.head(pdf_url, headers=headers, timeout=REQUEST_TIMEOUT_SEC, allow_redirects=True)
            content_len = int(head_resp.headers.get("Content-Length", 0))
            if content_len > MAX_DOWNLOAD_SIZE_BYTES:
                print(f"⚠️ Skipping {pdf_url}: size ({content_len} bytes) exceeds limit")
                return {"action": "skipped_size"}

            # GET request
            get_resp = requests.get(pdf_url, headers=headers, timeout=REQUEST_TIMEOUT_SEC * 2, stream=True)
            if get_resp.status_code != 200:
                return {"action": "failed_download"}

            # Save to temporary incoming staging file
            fname = os.path.basename(urllib.parse.urlparse(pdf_url).path) or f"sync_doc_{int(time.time())}.pdf"
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            staging_path = os.path.join(DIR_INCOMING, f"sync_{int(time.time())}_{fname}")

            with open(staging_path, "wb") as f:
                for chunk in get_resp.iter_content(chunk_size=65536):
                    f.write(chunk)

            # Check if this document exists by source URL in PostgreSQL
            existing_doc_id = self._find_doc_id_by_source_url(pdf_url)

            # Ingest through automated pipeline
            if self.ingestion_pipeline:
                res = self.ingestion_pipeline.process_file(
                    filepath=staging_path,
                    title=link_text if len(link_text) > 4 else None,
                    source_url=pdf_url,
                    upload_source="sync",
                    uploaded_by="vjti_sync_bot",
                    visibility="public",
                    auto_approve=False,  # Enforce administrative review
                    replace_doc_id=existing_doc_id,
                )
                action = "updated" if existing_doc_id else ("downloaded" if res.get("status") == "success" else "skipped")
                return {"action": action, "result": res}

            return {"action": "downloaded_only", "path": staging_path}

        except Exception as e:
            print(f"⚠️ Error downloading {pdf_url}: {e}")
            return {"action": "error", "error": str(e)}

    def _find_doc_id_by_source_url(self, source_url: str) -> Optional[int]:
        """Check if a document from this exact URL has already been recorded."""
        if not self.get_db_conn:
            return None
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT id FROM documents WHERE source_url = %s LIMIT 1;", (source_url,))
            r = cur.fetchone()
            cur.close()
            conn.close()
            return r[0] if r else None
        except Exception:
            return None

    def _update_source_status(self, source_id: int, status: str, error: bool = False):
        """Update last_checked_at and status in document_sync_sources."""
        if not self.get_db_conn:
            return
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE document_sync_sources 
                SET last_checked_at = CURRENT_TIMESTAMP,
                    last_status = %s,
                    error_count = CASE WHEN %s THEN error_count + 1 ELSE error_count END
                WHERE id = %s;
            """, (status, error, source_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    def _record_history(
        self,
        source_id: Optional[int],
        source_url: str,
        docs_found: int,
        docs_downloaded: int,
        docs_updated: int,
        status: str,
        error_message: Optional[str] = None,
    ):
        """Insert a sync history row."""
        if not self.get_db_conn:
            return
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO document_sync_history 
                    (source_id, source_url, docs_found, docs_downloaded, docs_updated, status, error_message, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
            """, (source_id, source_url, docs_found, docs_downloaded, docs_updated, status, error_message))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"⚠️ Error recording sync history: {e}")


if __name__ == "__main__":
    from backend_api_original import get_db_connection, vector_db, embeddings
    from document_ingestion import DocumentIngestionPipeline

    pipeline = DocumentIngestionPipeline(
        vector_db=vector_db,
        embeddings=embeddings,
        db_connection_factory=get_db_connection,
    )
    service = VJTIWebsiteSyncService(
        db_connection_factory=get_db_connection,
        ingestion_pipeline=pipeline,
    )
    print("Running manual VJTI website synchronization...")
    report = service.sync_all_sources()
    print(f"Sync Result: {report}")
