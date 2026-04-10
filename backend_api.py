"""
Flask API wrapper for the VJTI Smart Campus Chatbot.
Run this separately: python backend_api.py
Frontend connects to http://localhost:5000/api/chat
"""
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from langchain_core.messages import HumanMessage, AIMessage

# ── Import Brain Module (Layer 2) and Data Paths (Layer 1) ──
from chat_engine import process_turn
from data_retrieval import DOCS_FOLDER

app = Flask(__name__)
CORS(app)

# ── Per-session conversation history ──
sessions = {}

@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    data         = request.json
    user_message = data.get("message", "").strip()
    session_id   = data.get("session_id", "default")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Initialize session if it doesn't exist
    if session_id not in sessions:
        sessions[session_id] = []

    # Get user's active history
    chat_history = sessions[session_id]

    # Let the chat engine process the turn (this modifies chat_history in place)
    response_data = process_turn(user_message, chat_history)

    # Trim sliding window history to prevent context overflow 
    # (Keeps the last 10 messages / 5 conversation turns)
    if len(chat_history) > 20:
        sessions[session_id] = chat_history[-10:]

    return jsonify(response_data)


@app.route("/api/history", methods=["GET"])
def history_endpoint():
    """Return the message history for a session."""
    session_id = request.args.get("session_id", "default")
    if session_id not in sessions:
        return jsonify({"session_id": session_id, "history": []})

    serialized = []
    for msg in sessions[session_id]:
        if isinstance(msg, HumanMessage):
            serialized.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            serialized.append({"role": "assistant", "content": msg.content})

    return jsonify({"session_id": session_id, "history": serialized})


@app.route("/api/reset", methods=["POST"])
def reset_endpoint():
    """Clear the conversation history for a session."""
    data = request.json or {}
    session_id = data.get("session_id", "default")
    if session_id in sessions:
        sessions.pop(session_id)
    return jsonify({"status": "ok", "message": f"Session '{session_id}' cleared."})


@app.route("/api/sessions", methods=["GET"])
def sessions_endpoint():
    """List all active session IDs and their message counts."""
    return jsonify({
        "sessions": [{"session_id": sid, "message_count": len(msgs)} for sid, msgs in sessions.items()]
    })


@app.route("/api/health", methods=["GET"])
def health():
    """Health-check endpoint."""
    return jsonify({"status": "ok", "architecture": "Decoupled 3-Layer"})


@app.route("/debug/docs", methods=["GET"])
def debug_docs():
    """Debug route to verify PDFs are detected."""
    import glob
    files = glob.glob(os.path.join(DOCS_FOLDER, "*.pdf"))
    return {"docs_folder": DOCS_FOLDER, "exists": os.path.isdir(DOCS_FOLDER), "pdf_files": sorted([os.path.basename(f) for f in files])}


@app.route("/docs/<path:filename>", methods=["GET"])
def serve_document(filename):
    """Serve PDFs directly to the frontend for viewing/downloading."""
    return send_from_directory(DOCS_FOLDER, filename)


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("🚀 VJTI Bot API (Decoupled Architecture) starting...")
    print("API running at http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)