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
from flask import send_from_directory


app = Flask(__name__)
CORS(app)

# ── Configuration ──
MODEL_NAME = "llama3"
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DOCS_FOLDER = os.path.join(BASE_DIR, "campus_documents")

# ── Connect to databases ──
db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# ── LLM ──
llm = ChatOllama(model=MODEL_NAME, temperature=0)


# ── Tool functions ──
def pdf_search(query):
    """Retrieves text from PDFs with an enhanced re-ranker for structural data."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    raw_docs = vector_db.similarity_search(query, k=15)

    retrieved_sources = list(set([os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")

    target_k   = ["TARGET", "B.TECH", "DIPLOMA", "FIRST YEAR", "FY", "EXCLUSIVELY", "SENIOR", "SY", "PG"]
    structure_k = ["FLOOR", "STRUCTURE", "ROOM", "CAPACITY", "OCCUPANCY", "SEATER", "GROUND"]
    fee_k      = ["FEE", "TUITION", "MESS", "PAYMENT", "SBI", "CONTRACTOR", "REFUND", "TFWS"]
    cal_k      = ["CALENDAR", "SCHEDULE", "DATE", "SEMESTER", "EXAM", "ESE", "MST", "CLASSES",
                  "START", "END", "REGISTER", "REGISTRATION", "PORTAL", "WEBSITE",
                  "FEST", "TECHNOVANZA", "PRATIBIMB", "HOLIDAY", "BREAK"]

    prioritized_docs = []
    other_docs = []
    q_upper = query.upper()

    for d in raw_docs:
        content     = d.page_content.upper()
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

    final_docs   = (prioritized_docs + other_docs)[:10]
    context_list = []
    for d in final_docs:
        source = os.path.basename(d.metadata.get('source', 'Unknown File'))
        context_list.append(f"[OFFICIAL SOURCE: {source}]\n{d.page_content}")

    return "\n\n---\n\n".join(context_list)


def sql_query(query):
    """Runs a query against the SQL database."""
    print(f"   🗄️  Running SQL Query: {query}...")
    try:
        clean_query = query.replace("```sql", "").replace("```", "").strip()
        result = db.run(clean_query)
        return str(result) if result else "No matching records found in SQL."
    except Exception as e:
        return f"SQL Error: {str(e)}"


tools_map = {
    "PDF_Knowledge_Base": pdf_search,
    "Campus_SQL_Data":    sql_query,
    "SQL":                sql_query,
    "PDF":                pdf_search,
}

# ── System prompt (full version from main_chatbot_agent.py) ──
SYSTEM_INSTRUCTION = """You are the VJTI Smart Campus Assistant.

ROUTING PRIORITY (CRITICAL):
- Use 'Campus_SQL_Data' (or simply 'SQL') for: Lists of programs, intake numbers, faculty locations, HOD names, and cutoffs.
- Use 'PDF_Knowledge_Base' (or simply 'PDF') for: Hostel structure, room counts, fees, policies, academic calendars, important dates/schedules, Hostel details, Fees, Admission Stages (CAP), Seat Acceptance (Freeze/Float/Betterment), Anti-Ragging procedures,Reservation Norms and Attendance Rules.
- CRITICAL: Hostel "Block C" structure, Dates for exams (MST/ESE), class start dates, and holiday schedules is ONLY in the PDF. NEVER use SQL for hostels.

SQL RULES (STRICT SCHEMA MAPPING):
INDEPENDENT COLUMN SELECTION: For every new query, evaluate exactly which columns the user wants. DO NOT carry over columns from previous questions. 
1. MANDATORY LIKE: For ALL string filters (department, branch, name, designation), you MUST use `LIKE '%keyword%'` instead of `=`. 
2. KEYWORD ISOLATION: When the user says 'Electrical dept' or 'Computer branch', use ONLY the core noun (e.g., '%Electrical%' or '%Computer%') for the LIKE pattern. Ignore words like 'dept', 'department', 'branch', 'course', 'office'.
3. SYNONYM MAPPING (CRITICAL):
- 'IT' and 'Information Technology' -> MUST be treated as identical. Always search for `%Information Technology%` if the user says 'IT'.
- 'Entc' or 'Extc' or 'Electronics and telecommunication' or 'telecommunication' and 'Electronics & Telecom' -> MUST be treated as identical. Always search for `%Electronics & Telecom%` if the user says 'Entc' or 'Extc' or 'Electronics and telecommunication' or 'telecommunication'.
- 'mail' or 'email' -> use `email` column; 'office' or 'room' -> use `cabin_location`.
- 'Electronics' vs 'EXTC': 
    * If the user says 'Electronics' (without 'EXTC' or 'Telecom'), search for branch LIKE '%Electronics Engineering%'.
    * If the user says 'EXTC', 'ENTC', or 'Telecommunication', search for branch LIKE '%Electronics & Telecom%'.

4. 'cutoffs' Table: Columns are [year, branch, category, percentile].
    - MANDATORY SELECT: ALWAYS include the `category` column in the SELECT clause when querying cutoffs so the user can see which category the score belongs to.
    - CATEGORY CODES (CRITICAL): The database uses codes. 
     * 'Open' or 'General' -> use LIKE '%OPENS%'.
     * 'OBC' -> use LIKE '%OBCS%'.
     * 'SC' -> use LIKE '%SCS%'.
     * 'ST' -> use LIKE '%STS%'.
     * 'EWS' or 'Economically Weaker Section' -> use LIKE '%EWS%'.
    - If user asks for 'all categories', DO NOT filter by category. Simply use: SELECT category, percentile FROM cutoffs WHERE branch LIKE '%keyword%' AND year = 2025;

5. 'programs' Table: Columns are [program_name, level, department, intake, duration_years].
    - For M.Tech, level = 'Postgraduate'.
    - For B.Tech, level = 'Undergraduate'.

6. 'faculty' Table: Columns are [name, department, designation, email, cabin_location].
    - ALWAYS use `LIKE '%HOD%'` for any query related to "HOD", "Head", or "Head of Department". NEVER use long-form strings.
    - HOD Search Example: WHERE designation LIKE '%HOD%' AND department LIKE '%Computer%'.

7. ELIGIBILITY & PERCENTILE LOGIC:
- When a user provides a percentile and asks "what can I get" or "what did I clear", you MUST query the 'cutoffs' table, NOT the 'programs' table.
- The 'cutoffs' table DOES have a 'branch' column. Example query: SELECT branch, percentile FROM cutoffs WHERE percentile <= 90.3 AND category LIKE '%EWS%' AND year = 2025;

DEMO QUESTION TEMPLATES:
- M.Tech Intakes: SELECT program_name, intake FROM programs WHERE level = 'Postgraduate' AND program_name LIKE '%M.Tech%';
- Cutoff Comparison: SELECT year, category, percentile FROM cutoffs WHERE branch = 'Computer Engineering' AND category = 'GOPENS' AND (year=2024 OR year=2025);
- B.Tech Intake: SELECT intake FROM programs WHERE program_name = 'B.Tech Computer Engineering';

PDF RULES (STRICT BLOCK ISOLATION):
1. BLOCK VERIFICATION: When asked about a specific hostel (e.g., Block C), you MUST ONLY use data that is explicitly listed under that block's heading in the provided text.
2. DO NOT MIX BLOCKS: Never attribute features of one block (e.g., Block D's floors) to another (Block C).
3. GROUNDING: If the requested block's specific details are not in the tool output, say 'I don't have that info'.
4. CITE: Always cite the [OFFICIAL SOURCE].

DOCUMENT LOGIC MAPPING (HOSTEL):
- BLOCK C: Target: First-year B.Tech/Diploma only. Structure: Ground floor (16 rooms + Mess), 1st floor (32 rooms), 2nd floor (32 rooms). Occupancy: 4 students per room.
- BLOCK D: Intermediate & Senior boys. 4 floors. Majority 3-seater.
- PG-HOSTEL: Final year & PG. 6 floors. Floors 1-5 (36-40 rooms each). 2 students per room.
- BLOCKS A & B: Girls. 2 floors. 3 girls per room.
- ACADEMIC CALENDAR: Distinguish between "First Year (FY)" and "Senior Year (SY onwards)". Senior Year classes usually start in July; First Year classes usually start in September. Always check the specific semester (Odd/Even) and student level before answering.
- ERP PORTAL: For questions about "where to register" or "registration site", identify the Official VJTI ERP Portal URL: https://erp.vjti.ac.in/.
- MAJOR EVENTS: Technovanza is held in December/January. Pratibimb is held in February.
- ANTI-RAGGING: Step 1: Informal (Warden/Faculty). Step 2: Formal Written (Box/Dr. Gangopadhyay). Step 3: Online (UGC portal). Step 4: Committee Enquiry.

- RESERVATION NORMS (PDF ONLY — NEVER USE SQL):
  * Constitutional Reservations (Maharashtra domicile only):
    SC=13%, ST=7%, VJ/DT(A)=3%, NT-B=2.5%, NT-C=3.5%, NT-D=2%, SBC=2%, OBC=19%, EWS=10% (over & above intake).
  * Female Reservation: 30% WITHIN every category (horizontal). Vacant female seats go to males of SAME category.
  * PwD Quota: 5% of total intake. Minimum 40% disability required. Horizontal reservation.
  * Defense Quota: 5%. Covers Def-1 (ex-service), Def-2 (active service), Def-3 (active, transferred to MH). Parent must be Maharashtra domicile.
  * Orphan Reservation: 1%, within Open category only.
  * TFWS: 5% over & above intake. Family income < ₹8 LPA. Benefit = 100% tuition fee waiver ONLY. Development fees still apply.
  * All India Quota (AI): Filled via JEE Main. Minority of seats. Majority filled via MHT-CET for Maharashtra candidates.
  * Non-Creamy Layer Certificate: MANDATORY for OBC, VJ/DT, NT, SBC candidates.
  * Conversion Rule: Vacant seats after Round III are converted to other categories per inter-se-merit rules.
  * Domicile Rule: ALL reservations (constitutional + special) apply ONLY to Maharashtra domicile candidates.
  * CRITICAL: Do NOT invent percentages. If a category is not listed above, say you don't have that info.

FEE POLICY (CRITICAL):
- For any questions regarding tuition fees, development fees, or total annual amounts, DO NOT state any numerical figures or currency amounts.
- Inform the user that the fee structure is complex due to various categories (Open, Reserved, TFWS).
- Direct the user to cross-verify the details using the specific PDF file provided in your response.

TO USE A TOOL, respond ONLY with this JSON format:
{"tool": "Campus_SQL_Data", "query": "SELECT ..."}
"""

# ── Per-session conversation history ──
sessions = {}

# ═════════════════════════════════════════════════════════════════════════════
# INTERCEPT STACK  (evaluated top-to-bottom in chat_endpoint)
#
#  Layer 0 — _get_serve_pdf()        : serve fee/calendar PDF file directly
#  Layer 1 — _is_forced_pdf()        : force PDF_Knowledge_Base tool
#  Layer 2 — _try_hardcoded_answer() : return known reservation % instantly
#  Layer 3 — normal LLM routing
# ═════════════════════════════════════════════════════════════════════════════

# ── Layer 0: Direct PDF serve ─────────────────────────────────────────────────
# Trigger phrases that mean the user wants fee/calendar info.
# Kept as full phrases so single-word category mentions (obc, ews, sc …)
# in cutoff/eligibility questions do NOT accidentally match.
FEE_TRIGGER_PHRASES = {
    "fee structure", "fees structure", "tuition fee", "how much is the fee",
    "what are the fees", "what is the fee", "fee for", "fees for",
    "annual fee", "semester fee", "total fee", "development fee",
    "hostel fee", "mess fee",
}
CALENDAR_TRIGGER_PHRASES = {
    "academic calendar", "class schedule", "exam schedule", "exam dates",
    "mst date", "mst dates", "ese date", "ese dates", "holiday list",
    "holiday schedule", "class start date", "class end date",
    "semester start", "semester end", "registration date",
    "last date to register", "when do classes start", "when do classes end",
    "odd semester calendar", "even semester calendar",
}

# Fee file routing — first match wins
FEE_FILE_ROUTING = [
    ({"working professional", "wp", "weekend"},       "Fees_Working_Professionals_UG_PG_2025_26.pdf"),
    ({"hostel fee", "hostel fees"},                   "Fees_Hostel_FY_and_Lateral_Entry_2025_26.pdf"),
    ({"lateral", "direct second year", "dsy"},        "Fees_BTech_Direct_Second_Year_Lateral_2025_26.pdf"),
    ({"sy", "second year", "third year", "mtech",
      "m.tech"},                                      "Fees_SY_Onwards_BTech_MTech_MCA_PhD_2025_26.pdf"),
    ({"fy", "first year", "mca", "phd"},              "Fees_FY_BTech_MTech_MCA_PhD_2025_26.pdf"),
]

# Calendar file routing — first match wins
CALENDAR_FILE_ROUTING = [
    ({"diploma"},                                     "Calendar_Diploma_2025_26.pdf"),
    ({"working professional", "wp", "dsy"},           "Calendar_DSY_WP_BTech_MTech_2025_26.pdf"),
    ({"fy", "first year"},                            "Calendar_FY_BTech_MCA_MTech_PhD_2025_26.pdf"),
    ({"sy", "second year", "sy onwards", "senior"},   "Calendar_SY_Onwards_BTech_MCA_MTech_PhD_2025_26.pdf"),
]


def _get_serve_pdf(user_message: str) -> "tuple[str, str] | None":
    """
    Returns (pdf_filename, friendly_message) when the question is about fees
    or academic calendars — the PDF is served directly, LLM is bypassed.
    Returns None to continue with normal flow.
    """
    msg = user_message.lower()

    if any(phrase in msg for phrase in FEE_TRIGGER_PHRASES):
        for keywords, filename in FEE_FILE_ROUTING:
            if any(kw in msg for kw in keywords):
                return (filename,
                        "Here is the relevant fee structure PDF. Fees vary by program and "
                        "category (Open/Reserved/TFWS) — please check the applicable section.")
        return ("Fees_FY_BTech_MTech_MCA_PhD_2025_26.pdf",
                "Here is the fee structure PDF. If you need a different program's fees "
                "(SY/MTech/WP/Hostel), please specify.")

    if any(phrase in msg for phrase in CALENDAR_TRIGGER_PHRASES):
        for keywords, filename in CALENDAR_FILE_ROUTING:
            if any(kw in msg for kw in keywords):
                return (filename,
                        "Here is the academic calendar PDF. Check the relevant semester "
                        "section for exact dates.")
        return ("Calendar_SY_Onwards_BTech_MCA_MTech_PhD_2025_26.pdf",
                "Here is the academic calendar PDF. If you need a different program's "
                "calendar (FY/Diploma/WP), please specify.")

    return None


# ── Layer 1: Forced PDF routing ───────────────────────────────────────────────
# Forces PDF_Knowledge_Base before the LLM decides.
# "obc", "ews", "sc", "st" intentionally excluded so cutoff queries route to SQL.
PDF_FORCE_KEYWORDS = {
    "reservation", "quota", "reserve", "reserved",
    "vj/dt", "denotified", "nomadic tribe",
    "nt-b", "nt-c", "nt-d",
    "non-creamy", "non creamy", "creamy layer",
    "tfws", "tuition fee waiver", "fee waiver",
    "domicile", "pwd quota", "disability quota", "benchmark disability",
    "defense quota", "defence quota", "def-1", "def-2", "def-3",
    "ex-service", "orphan reservation",
    "all india quota", "ai quota", "jee main quota",
    "constitutional reservation", "inter-se-merit",
    "conversion rule", "seat conversion",
    "cap round", "freeze", "float", "betterment",
    "anti-ragging", "anti ragging", "ragging",
    "attendance rule", "attendance policy",
}


def _is_forced_pdf(user_message: str) -> bool:
    """Return True if the message must go to PDF_Knowledge_Base regardless of LLM routing."""
    return any(kw in user_message.lower() for kw in PDF_FORCE_KEYWORDS)


# ── Layer 2: Hardcoded reservation facts ─────────────────────────────────────
# Only fires when the question is EXCLUSIVELY about a reservation percentage.
RESERVATION_FACTS = {
    "sc":      ("SC (Scheduled Castes)",                       "13%",   "of total sanctioned intake. Maharashtra domicile required."),
    "st":      ("ST (Scheduled Tribes)",                       "7%",    "of total sanctioned intake. Maharashtra domicile required."),
    "vj":      ("VJ/DT-A (Vimukta Jati / Denotified Tribes)", "3%",    "of total sanctioned intake. Non-Creamy Layer certificate required."),
    "nt-b":    ("NT-B (Nomadic Tribes B)",                     "2.5%",  "of total sanctioned intake. Non-Creamy Layer certificate required."),
    "nt-c":    ("NT-C (Nomadic Tribes C)",                     "3.5%",  "of total sanctioned intake. Non-Creamy Layer certificate required."),
    "nt-d":    ("NT-D (Nomadic Tribes D)",                     "2%",    "of total sanctioned intake. Non-Creamy Layer certificate required."),
    "sbc":     ("SBC (Special Backward Class)",                "2%",    "of total sanctioned intake. Non-Creamy Layer certificate required."),
    "obc":     ("OBC (Other Backward Classes)",                "19%",   "of total sanctioned intake. Non-Creamy Layer certificate required."),
    "ews":     ("EWS (Economically Weaker Section)",           "10%",   "OVER AND ABOVE sanctioned intake. Maharashtra domicile required."),
    "tfws":    ("TFWS (Tuition Fee Waiver Scheme)",            "5%",    "over and above intake. Family income < ₹8 LPA. Tuition fee only — development fees still apply."),
    "pwd":     ("PwD (Persons with Disability)",               "5%",    "of total intake. Minimum 40% disability. Horizontal reservation."),
    "defense": ("Defense Quota",                               "5%",    "for children of ex-service (Def-1), active service (Def-2), active personnel transferred to MH (Def-3). Parent must be Maharashtra domicile."),
    "orphan":  ("Orphan Reservation",                          "1%",    "within the Open category only."),
    "female":  ("Female Reservation",                          "30%",   "WITHIN every category (horizontal). Vacant female seats go to males of the SAME category."),
}

_CATEGORY_TRIGGERS = {
    "nt-c": "nt-c", "ntc": "nt-c", "nt c": "nt-c",
    "nt-b": "nt-b", "ntb": "nt-b", "nt b": "nt-b",
    "nt-d": "nt-d", "ntd": "nt-d", "nt d": "nt-d",
    "obc": "obc", "other backward class": "obc",
    "scheduled caste": "sc", "scheduled tribe": "st",
    "ews": "ews", "economically weaker": "ews",
    "sbc": "sbc", "special backward class": "sbc",
    "vj/dt": "vj", "vimukta": "vj", "denotified": "vj",
    "tfws": "tfws", "fee waiver": "tfws",
    "pwd": "pwd", "persons with disability": "pwd",
    "defense quota": "defense", "defence quota": "defense",
    "orphan": "orphan",
    "female reservation": "female", "women reservation": "female",
}

_DISQUALIFYING_TERMS = {
    "percentile", "cutoff", "cut-off", "cleared", "eligible", "get admission",
    "which branch", "what branch", "branch can", "can i get",
    "floor", "block", "hostel", "room", "intake", "seats available",
    "program", "faculty", "hod", "professor", "course", "score", "rank", "marks",
}


def _try_hardcoded_answer(user_message: str) -> "str | None":
    """
    Returns a pre-built answer ONLY when the question is purely about a
    reservation category percentage. Returns None for everything else.
    """
    msg_lower = user_message.lower()

    # Gate 1: bail if any disqualifying context word is present
    if any(t in msg_lower for t in _DISQUALIFYING_TERMS):
        return None

    # Gate 2: must explicitly ask about a percentage / quota size
    MUST_HAVE = [
        "percentage", "percent", "% reserved", "how much is reserved",
        "how much", "what is the reservation", "reserved for me",
        "quota for", "reservation for", "what percentage",
        "what percent", "belong to", "what is reserved",
    ]
    if not any(t in msg_lower for t in MUST_HAVE):
        return None

    # Gate 3: must match a specific category trigger
    matched_key = None
    for trigger, key in _CATEGORY_TRIGGERS.items():
        if trigger in msg_lower:
            matched_key = key
            break

    if matched_key and matched_key in RESERVATION_FACTS:
        name, pct, detail = RESERVATION_FACTS[matched_key]
        return (
            f"**{name}: {pct}** {detail}\n\n"
            f"*(Source: Reservation_Norms.pdf — VJTI Admission Reservation Norms & Quota System 2025-26)*"
        )
    return None


# ── _build_final_task_note (used inside chat_endpoint after tool execution) ───
def _build_final_task_note(tool_name: str, user_message: str) -> str:
    """Returns the context-sensitive grounding instruction appended to tool output."""
    if tool_name in ["Campus_SQL_Data", "SQL"]:
        return "CRITICAL: Ensure your table includes 'branch' and 'category'. Do not guess data."

    u_q_l = user_message.lower()

    if _is_forced_pdf(user_message):
        return (
            "ABSOLUTE NUMBER LOCK: You MUST copy the EXACT percentage figures from the "
            "RETRIEVED DOCUMENT CONTENT above. DO NOT add, subtract, round, or compute "
            "any numbers. DO NOT use your training knowledge. "
            "If you see 'OBC: 19%' in the text, you say 19%. "
            "If a specific figure is NOT present in the document, say 'I don't have that info'. "
            "Cite [OFFICIAL SOURCE] at the end."
        )
    if any(k in u_q_l for k in ["hostel", "block", "room", "stay"]):
        return "STRICT NUMERICAL ACCURACY: Identify specific room counts for EACH floor from the text. Cite the source."
    elif "technovanza" in u_q_l or "pratibimb" in u_q_l:
        return (
            "ABSOLUTE GROUNDING: Only report Technovanza as Dec/Jan and Pratibimb as Feb IF found in the text. "
            "If the text says otherwise, follow the text. If not in text, say you don't know. DO NOT use external knowledge."
        )
    elif any(k in u_q_l for k in ["calendar", "date", "semester", "register", "portal"]):
        return (
            "STRICT DATE ACCURACY: Only report dates explicitly found in the TOOL OUTPUT. "
            "If Even Semester registration dates aren't there, say you don't have that info. "
            "Cite the source and URL (https://erp.vjti.ac.in/)."
        )
    return "STRICT GROUNDING: Answer based solely on the tool output."


# ── Routes ──

@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    data         = request.json
    user_message = data.get("message", "").strip()
    session_id   = data.get("session_id", "default")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in sessions:
        sessions[session_id] = []

    chat_history   = sessions[session_id]
    system_message = SystemMessage(content=SYSTEM_INSTRUCTION)

    chat_history.append(HumanMessage(content=user_message))

    # ── Layer 0: Direct PDF serve (fees / calendars) ──
    serve = _get_serve_pdf(user_message)
    if serve:
        pdf_filename, friendly_msg = serve
        print(f"📄 Serving PDF directly: {pdf_filename}")
        chat_history.append(AIMessage(content=friendly_msg))
        if len(chat_history) > 20:
            sessions[session_id] = chat_history[-10:]
        return jsonify({
            "reply":          friendly_msg,
            "serve_pdf":      pdf_filename,
            "serve_pdf_path": os.path.join(DOCS_FOLDER, pdf_filename),
        })

    # ── Layer 2: Hardcoded reservation fact ──
    hardcoded = _try_hardcoded_answer(user_message)
    if hardcoded:
        print(f"📋 Hardcoded fact returned for: '{user_message}'")
        chat_history.append(AIMessage(content=hardcoded))
        if len(chat_history) > 20:
            sessions[session_id] = chat_history[-10:]
        return jsonify({"reply": hardcoded, "source_file": "Reservation_Norms.pdf"})

    # ── Layer 1: Forced PDF routing ──
    if _is_forced_pdf(user_message):
        print(f"🔒 Forced PDF routing for: '{user_message}'")
        safe_query = user_message.replace('"', "'")
        content    = f'{{"tool": "PDF_Knowledge_Base", "query": "{safe_query}"}}'
        json_match = re.search(
            r'\{.*"tool":\s*"(.*?)",\s*"query":\s*"(.*?)"\s*\}', content, re.DOTALL
        )
    else:
        # ── Layer 3: Normal LLM routing ──
        messages_to_send = [system_message] + chat_history[-6:]
        response         = llm.invoke(messages_to_send)
        content          = response.content.strip()
        json_match       = re.search(
            r'\{.*"tool":\s*"(.*?)",\s*"query":\s*"(.*?)"\s*\}', content, re.DOTALL
        )

    bot_text    = content
    source_file = None

    if json_match:
        try:
            tool_call_json = json.loads(json_match.group(0))
            tool_name  = tool_call_json.get("tool")
            query_arg  = tool_call_json.get("query")

            if tool_name in tools_map:
                print(f"⚙️  Executing {tool_name}...")
                result = tools_map[tool_name](query_arg)

                final_task_note = _build_final_task_note(tool_name, user_message)

                if tool_name in ["Campus_SQL_Data", "SQL"]:
                    # SQL: sliding window — needs conversational context
                    chat_history.append(AIMessage(content=content))
                    chat_history.append(HumanMessage(
                        content=(
                            f"TOOL OUTPUT:\n{result}\n\n"
                            f"FINAL TASK: Based ONLY on this data, answer: '{user_message}'. {final_task_note}"
                        )
                    ))
                    final_response = llm.invoke([system_message] + chat_history[-6:])
                else:
                    # PDF: isolated call — no chat history so training weights
                    # cannot override what the document actually says.
                    isolated_prompt = HumanMessage(
                        content=(
                            f"RETRIEVED DOCUMENT CONTENT:\n{result}\n\n"
                            f"---\n"
                            f"USER QUESTION: {user_message}\n\n"
                            f"INSTRUCTION: {final_task_note}\n"
                            f"Find the exact sentence or bullet in the RETRIEVED DOCUMENT CONTENT "
                            f"that answers the question. Copy the number/fact VERBATIM. "
                            f"Do not use any other knowledge."
                        )
                    )
                    final_response = llm.invoke([system_message, isolated_prompt])
                    chat_history.append(AIMessage(content=content))
                    chat_history.append(HumanMessage(
                        content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: answer '{user_message}'. {final_task_note}"
                    ))

                bot_text = final_response.content
                chat_history.append(final_response)

                source_match = re.search(r'([A-Za-z0-9_\-]+\.pdf)', bot_text)
                if source_match:
                    source_file = source_match.group(1)
            else:
                bot_text = "[Internal Error] Invalid tool selected."
        except Exception as e:
            bot_text = content
    else:
        chat_history.append(response)

    # Trim sliding window
    if len(chat_history) > 20:
        sessions[session_id] = chat_history[-10:]

    response_data = {"reply": bot_text}
    if source_file:
        response_data["source_file"] = source_file
        response_data["source_path"] = os.path.join(DOCS_FOLDER, source_file)

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
            serialized.append({"role": "user",      "content": msg.content})
        elif isinstance(msg, AIMessage):
            serialized.append({"role": "assistant", "content": msg.content})
        # SystemMessage and internal tool messages are intentionally excluded

    return jsonify({"session_id": session_id, "history": serialized})


@app.route("/api/reset", methods=["POST"])
def reset_endpoint():
    """Clear the conversation history for a session."""
    data       = request.json or {}
    session_id = data.get("session_id", "default")

    if session_id in sessions:
        sessions.pop(session_id)

    return jsonify({"status": "ok", "message": f"Session '{session_id}' cleared."})


@app.route("/api/sessions", methods=["GET"])
def sessions_endpoint():
    """List all active session IDs and their message counts."""
    return jsonify({
        "sessions": [
            {"session_id": sid, "message_count": len(msgs)}
            for sid, msgs in sessions.items()
        ]
    })


@app.route("/api/health", methods=["GET"])
def health():
    """Health-check endpoint."""
    return jsonify({"status": "ok", "model": MODEL_NAME})


@app.route("/debug/docs", methods=["GET"])
def debug_docs():
    import glob
    files = glob.glob(os.path.join(DOCS_FOLDER, "*.pdf"))
    return {"docs_folder": DOCS_FOLDER, "exists": os.path.isdir(DOCS_FOLDER), "pdf_files": sorted([os.path.basename(f) for f in files])}


@app.route("/docs/<path:filename>", methods=["GET"])
def serve_document(filename):
    """Serve PDFs from campus_documents."""
    return send_from_directory(DOCS_FOLDER, filename)


# ── Entry point ──
if __name__ == "__main__":
    print("\n" + "=" * 50)
    print(f"🤖 VJTI Bot API (Local {MODEL_NAME}) starting...")
    print("API running at http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)