"""
admin_api.py — Secure Administrative Endpoints for Campus Chat (Week 4)

Provides role-based REST endpoints for:
- Document upload (single & multiple PDF files).
- Document management (list, view details, approve, reject, archive, reprocess, replace).
- Website synchronization (trigger sync, view status, history, configure sources).
- Predictive prefetching metrics and simulation.
- Strict server-side RBAC: requires @role_required('admin').
"""

import os
import tempfile
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

admin_bp = Blueprint("admin_bp", __name__)

# References initialized from backend_api_original
document_manager = None
ingestion_pipeline = None
sync_service = None
prefetch_engine = None
role_required_decorator = None


def init_admin_api(doc_mgr, pipeline, sync_svc, prefetch_eng, role_dec):
    """Dependency injection from backend_api_original."""
    global document_manager, ingestion_pipeline, sync_service, prefetch_engine, role_required_decorator
    document_manager = doc_mgr
    ingestion_pipeline = pipeline
    sync_service = sync_svc
    prefetch_engine = prefetch_eng
    role_required_decorator = role_dec


def _require_admin():
    """Helper decorator applying the injected role_required('admin') decorator."""
    def decorator(f):
        if role_required_decorator:
            return role_required_decorator("admin")(f)
        return f
    return decorator


# ── Overview / Dashboard Summary ──────────────────────────────────────────────

@admin_bp.route("/api/admin/overview", methods=["GET"])
def admin_overview():
    """Dashboard statistics and system health."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden", "message": "Admin privileges required"}), 403

    doc_stats = document_manager.get_stats() if document_manager else {}
    sync_stats = sync_service.get_status() if sync_service else {}
    prefetch_stats = prefetch_engine.get_stats() if prefetch_engine else {}

    return jsonify({
        "status": "ok",
        "role": "admin",
        "documents": doc_stats,
        "sync": sync_stats,
        "prefetch": prefetch_stats,
    }), 200


# ── Document Management ───────────────────────────────────────────────────────

@admin_bp.route("/api/admin/documents", methods=["GET"])
def list_documents():
    """List documents with optional search, approval filter, and pagination."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    search = request.args.get("search", "").strip() or None
    status = request.args.get("status", "all").strip()
    source = request.args.get("source", "all").strip()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    if not document_manager:
        return jsonify({"documents": [], "total": 0})

    result = document_manager.list_documents(
        search=search,
        approval_status=status,
        upload_source=source,
        limit=limit,
        offset=offset,
    )
    return jsonify(result), 200


@admin_bp.route("/api/admin/documents/<int:doc_id>", methods=["GET"])
def get_document(doc_id: int):
    """Get single document details, versions, and audit history."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    if not document_manager:
        return jsonify({"error": "Service unavailable"}), 503

    doc = document_manager.get_document_details(doc_id)
    if not doc:
        return jsonify({"error": f"Document {doc_id} not found"}), 404

    return jsonify({"document": doc}), 200


@admin_bp.route("/api/admin/documents/upload", methods=["POST"])
def upload_documents():
    """
    Upload one or multiple PDF documents.
    Validates, chunks, embeds, and records metadata.
    """
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden", "message": "Admin privileges required to upload knowledge base documents"}), 403
        username = user.get("username", "admin")
    else:
        username = "admin"

    if not ingestion_pipeline:
        return jsonify({"error": "Ingestion pipeline not configured"}), 503

    # Check multipart files
    files = request.files.getlist("files") or ([request.files["file"]] if "file" in request.files else [])
    if not files:
        return jsonify({"error": "No file uploaded. Use field 'file' or 'files'"}), 400

    auto_approve = request.form.get("auto_approve", "false").lower() in ("true", "1", "yes")
    custom_title = request.form.get("title", "").strip() or None
    visibility = request.form.get("visibility", "public").strip()

    from document_ingestion import DIR_INCOMING
    os.makedirs(DIR_INCOMING, exist_ok=True)

    results = []
    errors = []

    for file in files:
        if not file or not file.filename:
            continue

        raw_filename = secure_filename(file.filename)
        if not raw_filename.lower().endswith(".pdf"):
            errors.append({"filename": file.filename, "error": "Only PDF files are supported"})
            continue

        temp_target = os.path.join(DIR_INCOMING, f"upload_{raw_filename}")
        file.save(temp_target)

        try:
            res = ingestion_pipeline.process_file(
                filepath=temp_target,
                title=custom_title if len(files) == 1 else None,
                upload_source="upload",
                uploaded_by=username,
                visibility=visibility,
                auto_approve=auto_approve,
            )
            results.append(res)
        except Exception as e:
            errors.append({"filename": file.filename, "error": str(e)})

    status_code = 201 if results else (400 if errors else 200)
    return jsonify({
        "status": "success" if results else "failure",
        "uploaded_count": len(results),
        "results": results,
        "errors": errors,
    }), status_code


@admin_bp.route("/api/admin/documents/<int:doc_id>/approve", methods=["POST"])
def approve_document(doc_id: int):
    """Approve a document to make it searchable in RAG and invalidate old cache entries."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403
        username = user.get("username", "admin")
    else:
        username = "admin"

    data = request.json or {}
    version_id = data.get("version_id")

    try:
        res = document_manager.approve_document(
            document_id=doc_id,
            approved_by=username,
            version_id=version_id,
        )
        return jsonify(res), 200
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        return jsonify({"error": f"Approval failed: {e}"}), 500


@admin_bp.route("/api/admin/documents/<int:doc_id>/reject", methods=["POST"])
def reject_document(doc_id: int):
    """Reject a document."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403
        username = user.get("username", "admin")
    else:
        username = "admin"

    data = request.json or {}
    reason = data.get("reason", "Rejected by administrator")
    version_id = data.get("version_id")

    try:
        res = document_manager.reject_document(
            document_id=doc_id,
            reason=reason,
            rejected_by=username,
            version_id=version_id,
        )
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/admin/documents/<int:doc_id>/archive", methods=["POST"])
def archive_document(doc_id: int):
    """Archive a document and exclude it from public chatbot retrieval."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403
        username = user.get("username", "admin")
    else:
        username = "admin"

    try:
        res = document_manager.archive_document(document_id=doc_id, archived_by=username)
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/admin/documents/<int:doc_id>/replace", methods=["POST"])
def replace_document(doc_id: int):
    """
    Replace an existing document with a newer PDF file.
    Creates version N+1 while retaining audit history.
    """
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403
        username = user.get("username", "admin")
    else:
        username = "admin"

    if "file" not in request.files:
        return jsonify({"error": "No replacement file provided"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files allowed"}), 400

    from document_ingestion import DIR_INCOMING
    os.makedirs(DIR_INCOMING, exist_ok=True)
    temp_target = os.path.join(DIR_INCOMING, f"replace_{doc_id}_{filename}")
    file.save(temp_target)

    auto_approve = request.form.get("auto_approve", "false").lower() in ("true", "1", "yes")

    try:
        res = ingestion_pipeline.process_file(
            filepath=temp_target,
            upload_source="upload",
            uploaded_by=username,
            auto_approve=auto_approve,
            replace_doc_id=doc_id,
        )
        # If auto-approved, trigger version promotion and cache invalidation
        if auto_approve and res.get("version_id"):
            document_manager.approve_document(doc_id, approved_by=username, version_id=res["version_id"])

        return jsonify({
            "status": "success",
            "message": f"Document {doc_id} successfully updated with version {res.get('version_number')}",
            "result": res,
        }), 200
    except Exception as e:
        return jsonify({"error": f"Replacement failed: {e}"}), 500


@admin_bp.route("/api/admin/documents/<int:doc_id>/reprocess", methods=["POST"])
def reprocess_document(doc_id: int):
    """Re-run ingestion on an existing document file."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    doc = document_manager.get_document_details(doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404

    cur_v = doc.get("versions", [{}])[0]
    storage_path = cur_v.get("storage_path")
    if not storage_path or not os.path.exists(storage_path):
        return jsonify({"error": "Original file not found on storage"}), 404

    try:
        # Re-run pipeline
        res = ingestion_pipeline.process_file(
            filepath=storage_path,
            title=doc.get("title"),
            replace_doc_id=doc_id,
        )
        return jsonify({"status": "success", "reprocessed": res}), 200
    except Exception as e:
        return jsonify({"error": f"Reprocessing failed: {e}"}), 500


# ── Website Synchronization Endpoints ─────────────────────────────────────────

@admin_bp.route("/api/admin/sync/status", methods=["GET"])
def sync_status():
    """Return synchronization scheduler state."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    if not sync_service:
        return jsonify({"error": "Sync service not configured"}), 503

    return jsonify(sync_service.get_status()), 200


@admin_bp.route("/api/admin/sync/run", methods=["POST"])
def run_sync_now():
    """Trigger an immediate manual synchronization run."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    if not sync_service:
        return jsonify({"error": "Sync service not configured"}), 503

    res = sync_service.sync_all_sources()
    return jsonify(res), 200


@admin_bp.route("/api/admin/sync/history", methods=["GET"])
def sync_history():
    """Get history of synchronization cycles."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    limit = int(request.args.get("limit", 20))
    if not sync_service:
        return jsonify({"history": []})

    return jsonify({"history": sync_service.get_history(limit=limit)}), 200


@admin_bp.route("/api/admin/sync/sources", methods=["GET", "POST"])
def sync_sources():
    """List or add/update sync sources."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    if request.method == "GET":
        sources = sync_service.get_sources() if sync_service else []
        return jsonify({"sources": sources}), 200

    # POST: Add new source or toggle
    data = request.json or {}
    source_url = data.get("source_url", "").strip()
    name = data.get("name", "").strip()
    category = data.get("category", "circulars").strip()

    from sync_service import is_safe_url
    if not is_safe_url(source_url):
        return jsonify({"error": "Invalid or unsafe URL. Must be an approved https://vjti.ac.in address"}), 400

    conn = None
    try:
        from backend_api_original import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO document_sync_sources (name, category, source_url, check_interval_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_url) DO UPDATE SET 
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                is_enabled = TRUE
            RETURNING id, name, source_url;
        """, (name or "Custom Source", category, source_url, 360))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return jsonify({
            "status": "success",
            "source": {"id": row[0], "name": row[1], "source_url": row[2]}
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


# ── Predictive Prefetching Endpoints ──────────────────────────────────────────

@admin_bp.route("/api/cache/prefetch/stats", methods=["GET"])
def prefetch_stats():
    """Telemetry and transition graph statistics for predictive prefetching."""
    if not prefetch_engine:
        return jsonify({"error": "Prefetch engine not configured"}), 503

    return jsonify(prefetch_engine.get_stats()), 200


@admin_bp.route("/api/cache/prefetch/simulate", methods=["POST"])
def prefetch_simulate():
    """
    Simulate CacheMind performance with predictive prefetching ON vs OFF
    on a test sequence of queries.
    """
    data = request.json or {}
    queries = data.get("queries")
    if not queries:
        queries = [
            "what are the hostel fees?",
            "where is the hostel located?",
            "what is the mess fee structure?",
            "where is the hostel located?",
            "what are the hostel fees?",
            "how to pay the hostel fees online?",
            "where is the hostel located?",
            "what are the hostel fees?",
            "what is the mess fee structure?",
        ]

    if not prefetch_engine:
        return jsonify({"error": "Prefetch engine not initialized"}), 503

    sim_res = prefetch_engine.simulate_comparison(queries)
    return jsonify({
        "status": "ok",
        "simulation": sim_res,
    }), 200


@admin_bp.route("/api/cache/prefetch/toggle", methods=["POST"])
def prefetch_toggle():
    """Enable or disable predictive prefetching."""
    if role_required_decorator:
        from backend_api_original import get_current_user
        user = get_current_user()
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    enabled = bool(data.get("enabled", True))
    if prefetch_engine:
        prefetch_engine.enabled = enabled
        return jsonify({"status": "ok", "prefetch_enabled": prefetch_engine.enabled}), 200
    return jsonify({"error": "Prefetch engine unavailable"}), 503
