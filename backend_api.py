"""
Flask API wrapper for the VJTI Smart Campus Chatbot.
Run this separately: python backend_api.py
Frontend connects to http://localhost:5000/api/chat
"""

import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

app = Flask(__name__)
CORS(app)

# ── Configuration ──
MODEL_NAME = "llama3"
DOCS_FOLDER = "./campus_documents"

# ── Connect to databases ──
db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# ── LLM ──
llm = ChatOllama(model=MODEL_NAME, temperature=0)

tools_map = {
    "PDF_Knowledge_Base": None,  # set below
    "Campus_SQL_Data": None,
    "SQL": None,
    "PDF": None,
}

# ── Tool functions ──
def pdf_search(query):
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    raw_docs = vector_db.similarity_search(query, k=15)

    retrieved_sources = list(set([os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")

    target_k = ["TARGET", "B.TECH", "DIPLOMA", "FIRST YEAR", "FY", "EXCLUSIVELY", "SENIOR", "SY", "PG"]
    structure_k = ["FLOOR", "STRUCTURE", "ROOM", "CAPACITY", "OCCUPANCY", "SEATER", "GROUND"]
    fee_k = ["FEE", "TUITION", "MESS", "PAYMENT", "SBI", "CONTRACTOR", "REFUND", "TFWS"]
    cal_k = ["CALENDAR", "SCHEDULE", "DATE", "SEMESTER", "EXAM", "ESE", "MST", "CLASSES", "START", "END",
             "REGISTER", "REGISTRATION", "PORTAL", "WEBSITE", "FEST", "TECHNOVANZA", "PRATIBIMB", "HOLIDAY", "BREAK"]

    prioritized_docs = []
    other_docs = []
    q_upper = query.upper()

    for d in raw_docs:
        content = d.page_content.upper()
        source_name = os.path.basename(d.metadata.get('source', '')).upper()
        is_priority = False

        if any(k in q_upper for k in target_k) and any(k in content for k in target_k):
            is_priority = True
        elif any(k in q_upper for k in structure_k) and any(k in content for k in structure_k):
            is_priority = True
        elif any(k in q_upper for k in cal_k) and ("CALENDAR" in source_name or any(k in content for k in cal_k)):
            is_priority = True
        elif any(k in q_upper for k in fee_k) and ("FEES_" in source_name or "REFUND" in source_name or any(k in content for k in fee_k)):
            is_priority = True

        if is_priority:
            prioritized_docs.append(d)
        else:
            other_docs.append(d)

    final_docs = (prioritized_docs + other_docs)[:10]
    context_list = []
    for d in final_docs:
        source = os.path.basename(d.metadata.get('source', 'Unknown File'))
        context_list.append(f"[OFFICIAL SOURCE: {source}]\n{d.page_content}")

    return "\n\n---\n\n".join(context_list)


def sql_query(query):
    print(f"   🗄️  Running SQL Query: {query}...")
    try:
        clean_query = query.replace("```sql", "").replace("```", "").strip()
        result = db.run(clean_query)
        return str(result) if result else "No matching records found in SQL."
    except Exception as e:
        return f"SQL Error: {str(e)}"


tools_map["PDF_Knowledge_Base"] = pdf_search
tools_map["Campus_SQL_Data"] = sql_query
tools_map["SQL"] = sql_query
tools_map["PDF"] = pdf_search

# ── System prompt (same as original) ──
SYSTEM_INSTRUCTION = """You are the VJTI Smart Campus Assistant.

ROUTING PRIORITY (CRITICAL):
- Use 'Campus_SQL_Data' (or simply 'SQL') for: Lists of programs, intake numbers, faculty locations, HOD names, and cutoffs.
- Use 'PDF_Knowledge_Base' (or simply 'PDF') for: Hostel structure, room counts, fees, policies, academic calendars, important dates/schedules, Hostel details, Fees, Admission Stages (CAP), Seat Acceptance (Freeze/Float/Betterment), Anti-Ragging procedures, and Attendance Rules.
- CRITICAL: Hostel "Block C" structure, Dates for exams (MST/ESE), class start dates, and holiday schedules is ONLY in the PDF. NEVER use SQL for hostels.

SQL RULES (STRICT SCHEMA MAPPING):
INDEPENDENT COLUMN SELECTION: For every new query, evaluate exactly which columns the user wants. DO NOT carry over columns from previous questions. 
1. MANDATORY LIKE: For ALL string filters (department, branch, name, designation), you MUST use `LIKE '%keyword%'` instead of `=`. 
2. KEYWORD ISOLATION: When the user says 'Electrical dept' or 'Computer branch', use ONLY the core noun (e.g., '%Electrical%' or '%Computer%') for the LIKE pattern.
3. SYNONYM MAPPING (CRITICAL):
- 'IT' and 'Information Technology' -> MUST be treated as identical. Always search for `%Information Technology%` if the user says 'IT'.
- 'Entc' or 'Extc' or 'Electronics and telecommunication' or 'telecommunication' and 'Electronics & Telecom' -> MUST be treated as identical.
- 'mail' or 'email' -> use `email` column; 'office' or 'room' -> use `cabin_location`.
4. 'cutoffs' Table: Columns are [year, branch, category, percentile].
    - MANDATORY SELECT: ALWAYS include the `category` column in the SELECT clause when querying cutoffs.
    - CATEGORY CODES: 'Open' or 'General' -> '%OPENS%'. 'OBC' -> '%OBCS%'. 'SC' -> '%SCS%'. 'ST' -> '%STS%'. 'EWS' -> '%EWS%'.
5. 'programs' Table: Columns are [program_name, level, department, intake, duration_years].
6. 'faculty' Table: Columns are [name, department, designation, email, cabin_location].
    - ALWAYS use `LIKE '%HOD%'` for any query related to "HOD", "Head", or "Head of Department".
7. ELIGIBILITY & PERCENTILE LOGIC:
- When a user provides a percentile, query the 'cutoffs' table, NOT the 'programs' table.

PDF RULES (STRICT BLOCK ISOLATION):
1. BLOCK VERIFICATION: When asked about a specific hostel (e.g., Block C), ONLY use data explicitly listed under that block's heading.
2. DO NOT MIX BLOCKS.
3. GROUNDING: If the requested block's specific details are not in the tool output, say 'I don't have that info'.
4. CITE: Always cite the [OFFICIAL SOURCE].

FEE POLICY (CRITICAL):
- For fee questions, DO NOT state numerical figures. Inform the user fees vary by category and direct them to the specific PDF.

TO USE A TOOL, respond ONLY with this JSON format:
{"tool": "Campus_SQL_Data", "query": "SELECT ..."}
"""

# ── Store conversation histories per session ──
sessions = {}


@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    data = request.json
    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", "default")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Get or create session history
    if session_id not in sessions:
        sessions[session_id] = []

    chat_history = sessions[session_id]
    chat_history.append(HumanMessage(content=user_message))

    system_message = SystemMessage(content=SYSTEM_INSTRUCTION)
    messages_to_send = [system_message] + chat_history[-6:]

    response = llm.invoke(messages_to_send)
    content = response.content.strip()

    json_match = re.search(r'\{.*"tool":\s*"(.*?)",\s*"query":\s*"(.*?)"\s*\}', content, re.DOTALL)

    bot_text = content
    source_file = None

    if json_match:
        try:
            tool_call_json = json.loads(json_match.group(0))
            tool_name = tool_call_json.get("tool")
            query_arg = tool_call_json.get("query")

            if tool_name in tools_map and tools_map[tool_name]:
                print(f"⚙️  Executing {tool_name}...")
                result = tools_map[tool_name](query_arg)

                if tool_name in ["Campus_SQL_Data", "SQL"]:
                    final_task_note = "CRITICAL: Ensure your table includes 'branch' and 'category'. Do not guess data."
                else:
                    u_q_l = user_message.lower()
                    if any(k in u_q_l for k in ["hostel", "block", "room", "stay"]):
                        final_task_note = "STRICT NUMERICAL ACCURACY: Identify specific room counts for EACH floor from the text. Cite the source."
                    elif "technovanza" in u_q_l or "pratibimb" in u_q_l:
                        final_task_note = "ABSOLUTE GROUNDING: Only report dates found in the text. DO NOT use external knowledge."
                    elif any(k in u_q_l for k in ["calendar", "date", "semester", "register", "portal"]):
                        final_task_note = "STRICT DATE ACCURACY: Only report dates explicitly found in the TOOL OUTPUT. Cite the source."
                    else:
                        final_task_note = "STRICT GROUNDING: Answer based solely on the tool output."

                chat_history.append(AIMessage(content=content))
                tool_output_msg = HumanMessage(
                    content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: Based ONLY on this data, answer: '{user_message}'. {final_task_note}"
                )
                chat_history.append(tool_output_msg)

                final_response = llm.invoke([system_message] + chat_history[-6:])
                bot_text = final_response.content

                source_match = re.search(r'([A-Za-z0-9_\-]+\.pdf)', bot_text)
                if source_match:
                    source_file = source_match.group(1)

                chat_history.append(final_response)
        except Exception as e:
            bot_text = content
    else:
        chat_history.append(response)

    # Trim history
    if len(chat_history) > 20:
        sessions[session_id] = chat_history[-10:]

    response_data = {"reply": bot_text}
    if source_file:
        response_data["source_file"] = source_file

    return jsonify(response_data)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": MODEL_NAME})


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print(f"🤖 VJTI Bot API (Local {MODEL_NAME}) starting...")
    print("API running at http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
