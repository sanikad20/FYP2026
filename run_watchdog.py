"""
run_watchdog.py — Dedicated Ingestion Worker for Campus Chat (Week 4)

Monitors `documents/incoming/` for new PDFs, runs text extraction, chunking,
embedding generation, ChromaDB vector indexing, and PostgreSQL metadata recording.
Runs as a dedicated process to avoid duplicate file watchers or threads inside Flask web workers.

Usage:
    python run_watchdog.py
"""

import sys
import time
import os

from watchdog_service import WatchdogIngestionService, DIR_INCOMING
from document_ingestion import DocumentIngestionPipeline, ensure_directories
from backend_api_original import get_db_connection, vector_db, embeddings

def main():
    print("=" * 65)
    print("  🚀 Campus Chat Dedicated Document Watchdog Worker (Week 4)")
    print(f"  📂 Monitoring incoming directory: {os.path.abspath(DIR_INCOMING)}")
    print("  Press Ctrl+C to terminate.")
    print("=" * 65)

    ensure_directories()

    pipeline = DocumentIngestionPipeline(
        vector_db=vector_db,
        embeddings=embeddings,
        db_connection_factory=get_db_connection,
    )

    service = WatchdogIngestionService(pipeline=pipeline, watch_dir=DIR_INCOMING)
    service.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping Watchdog service...")
        service.stop()
        print("✅ Watchdog service stopped cleanly.")
        sys.exit(0)

if __name__ == "__main__":
    main()
