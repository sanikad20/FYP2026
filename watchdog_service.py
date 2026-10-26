"""
watchdog_service.py — Directory Watcher for Automated PDF Document Ingestion (Week 4)

Monitors documents/incoming/ for newly added PDF documents using Python Watchdog:
- Waits for file writing/transfer to complete before processing (size stability & write lock checks).
- Triggers DocumentIngestionPipeline on detected files.
- Moves files safely through processing -> processed / quarantine / failed directories.
- Can run as a standalone worker process: python watchdog_service.py
- Can also be started as a background thread within Flask.
"""

import os
import sys
import time
import threading
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from document_ingestion import (
    DIR_INCOMING,
    DIR_PROCESSING,
    DIR_PROCESSED,
    DIR_FAILED,
    DIR_QUARANTINE,
    ensure_directories,
    DocumentIngestionPipeline,
)


def wait_for_file_ready(filepath: str, timeout_seconds: float = 15.0, check_interval: float = 0.5) -> bool:
    """
    Ensure the file has finished being copied/written to disk.
    Checks that file size > 0, size remains stable across intervals,
    and file can be opened for writing without lock contention.
    """
    start_time = time.time()
    last_size = -1

    while time.time() - start_time < timeout_seconds:
        if not os.path.exists(filepath):
            return False

        try:
            current_size = os.path.getsize(filepath)
            if current_size > 0 and current_size == last_size:
                # Test opening with append mode to verify file lock is released
                with open(filepath, "ab"):
                    pass
                return True
            last_size = current_size
        except (OSError, PermissionError):
            pass

        time.sleep(check_interval)

    return False


class IncomingPDFHandler(FileSystemEventHandler):
    """Event handler for newly dropped PDF documents in documents/incoming/."""

    def __init__(self, pipeline: DocumentIngestionPipeline):
        super().__init__()
        self.pipeline = pipeline
        self._processing_files = set()
        self._lock = threading.Lock()

    def on_created(self, event):
        if not event.is_directory:
            self._handle_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle_file(event.dest_path)

    def _handle_file(self, filepath: str):
        filename = os.path.basename(filepath)
        if not filename.lower().endswith(".pdf"):
            return

        with self._lock:
            if filepath in self._processing_files:
                return
            self._processing_files.add(filepath)

        threading.Thread(
            target=self._process_when_ready,
            args=(filepath,),
            daemon=True,
            name=f"Ingest-{filename[:15]}",
        ).start()

    def _process_when_ready(self, filepath: str):
        filename = os.path.basename(filepath)
        print(f"👀 Watchdog detected new file: {filename}")

        try:
            is_ready = wait_for_file_ready(filepath)
            if not is_ready:
                print(f"⚠️ File write timeout or locked: {filename}. Skipping for now.")
                return

            if not os.path.exists(filepath):
                return

            print(f"🚀 Watchdog starting ingestion pipeline for: {filename}")
            res = self.pipeline.process_file(
                filepath=filepath,
                upload_source="drop",
                uploaded_by="watchdog_service",
                visibility="public",
                auto_approve=False,
            )
            print(f"✨ Watchdog completed ingestion for: {filename} -> Status: {res.get('status')}")

        except Exception as e:
            print(f"❌ Watchdog error processing {filename}: {e}")
        finally:
            with self._lock:
                self._processing_files.discard(filepath)


class WatchdogIngestionService:
    """Manages the watchdog observer thread."""

    def __init__(self, pipeline: DocumentIngestionPipeline, watch_dir: str = DIR_INCOMING):
        self.pipeline = pipeline
        self.watch_dir = watch_dir
        self.observer = Observer()
        self.handler = IncomingPDFHandler(pipeline)
        self.is_running = False

    def start(self):
        ensure_directories()
        self.observer.schedule(self.handler, self.watch_dir, recursive=False)
        self.observer.start()
        self.is_running = True
        print(f"👁️ Watchdog Ingestion Service monitoring: {self.watch_dir}")

    def stop(self):
        if self.is_running:
            self.observer.stop()
            self.observer.join(timeout=3)
            self.is_running = False
            print("👁️ Watchdog Ingestion Service stopped.")


if __name__ == "__main__":
    from backend_api_original import get_db_connection, vector_db, embeddings

    print("=" * 60)
    print("  Starting Standalone Document Ingestion Watcher")
    print(f"  Watching: {DIR_INCOMING}")
    print("=" * 60)

    pipe = DocumentIngestionPipeline(
        vector_db=vector_db,
        embeddings=embeddings,
        db_connection_factory=get_db_connection,
    )
    service = WatchdogIngestionService(pipe)
    service.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()
        print("Watcher terminated by user.")
