"""
Flask API wrapper for the VJTI Smart Campus Chatbot.
Run this separately: python backend_api.py
Frontend connects to http://localhost:5000/api/chat

Speed improvements:
  Option A — Dual model:
              llama3.2:1b  → Call #1 (routing only — picks tool)   ~0.3-0.5s
              llama3:8b    → Call #2 (SQL generation + final answer) ~3-5s
  Option B — Streaming:
              /api/chat/stream  returns SSE so the user sees
              tokens as they are generated instead of waiting
              for the full response.

Run once before starting:
    ollama pull llama3.2:1b
"""

import os
import json
import re
import sqlite3
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from flask import send_from_directory

from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from navigation import navigation_bp, get_navigation, detect_navigation_intent
NAV_IMAGES_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campus_navigation_images")

app = Flask(__name__)
CORS(app)
app.register_blueprint(navigation_bp)   # registers /api/navigate endpoints

# ── Configuration ──
ROUTING_MODEL  = "llama3.2:1b"   # fast small model — ONLY picks which tool to use
RESPONSE_MODEL = "llama3"        # full model — writes SQL + generates the final answer
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DOCS_FOLDER = os.path.join(BASE_DIR, "campus_documents")

# ── Connect to databases ──
db         = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db  = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# ── LLMs ──
# routing_llm  : small + fast, temperature=0 for deterministic classification
# response_llm : full model, writes SQL and generates natural language answers
routing_llm  = ChatOllama(model=ROUTING_MODEL,  temperature=0)
response_llm = ChatOllama(model=RESPONSE_MODEL, temperature=0.1)


# ── Tool functions ──────────────────────────────────────────────────────────

def pdf_search(query):
    """Retrieves text from PDFs with an enhanced re-ranker for structural data."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    raw_docs = vector_db.similarity_search(query, k=15)

    retrieved_sources = list(set([
        os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs
    ]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")

    target_k    = ["TARGET", "B.TECH", "DIPLOMA", "FIRST YEAR", "FY",
                   "EXCLUSIVELY", "SENIOR", "SY", "PG"]
    structure_k = ["FLOOR", "STRUCTURE", "ROOM", "CAPACITY", "OCCUPANCY",
                   "SEATER", "GROUND"]
    fee_k       = ["FEE", "TUITION", "MESS", "PAYMENT", "SBI",
                   "CONTRACTOR", "REFUND", "TFWS"]
    cal_k       = ["CALENDAR", "SCHEDULE", "DATE", "SEMESTER", "EXAM",
                   "ESE", "MST", "CLASSES", "START", "END", "REGISTER",
                   "REGISTRATION", "PORTAL", "WEBSITE", "FEST",
                   "TECHNOVANZA", "PRATIBIMB", "HOLIDAY", "BREAK"]

    prioritized_docs = []
    other_docs       = []
    q_upper          = query.upper()

    for d in raw_docs:
        content     = d.page_content.upper()
        source_name = os.path.basename(d.metadata.get('source', '')).upper()
        is_priority = False

        if any(k in q_upper for k in target_k) and any(k in content for k in target_k):
            is_priority = True
        elif any(k in q_upper for k in structure_k) and any(k in content for k in structure_k):
            is_priority = True
        elif any(k in q_upper for k in cal_k) and (
            "CALENDAR" in source_name or any(k in content for k in cal_k)
        ):
            is_priority = True
        elif any(k in q_upper for k in fee_k) and (
            "FEES_" in source_name or "REFUND" in source_name
            or any(k in content for k in fee_k)
        ):
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


def _extract_sql_from_text(text: str) -> str:
    """
    Robustly extracts a clean SQL SELECT statement from LLM output.
    Handles markdown fences, explanatory text before/after, and multi-line queries.
    """
    # 1. Try to extract from ```sql ... ``` fences first
    fence_match = re.search(r'```(?:sql)?\s*(SELECT[\s\S]+?)```', text, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # 2. Try to find a raw SELECT statement in the text
    select_match = re.search(r'(SELECT\s[\s\S]+?;)', text, re.IGNORECASE)
    if select_match:
        return select_match.group(1).strip()

    # 3. Find SELECT and take everything from there to end of string (no semicolon)
    select_start = re.search(r'(SELECT\s[\s\S]+)', text, re.IGNORECASE)
    if select_start:
        candidate = select_start.group(1).strip()
        # Cut off at any line that looks like explanation (starts with a letter after a blank line)
        lines = candidate.split('\n')
        sql_lines = []
        for line in lines:
            stripped = line.strip()
            # Stop if we hit an explanation line (not SQL keywords)
            if sql_lines and stripped and not any(
                stripped.upper().startswith(kw) for kw in
                ['SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER',
                'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'AND', 'OR', 'ON',
                'LIKE', 'IN', 'NOT', ')', '(', '--', 'UNION']
            ) and not stripped.startswith(('*', "'", '"', '%')):
                break
            sql_lines.append(line)
        return '\n'.join(sql_lines).strip()

    # 4. Fallback: return the raw text stripped of fences
    cleaned = text.replace("```sql", "").replace("```", "").strip()
    return cleaned


def sql_query(query):
    """Runs a query against the SQL database with robust SQL extraction."""
    print(f"   🗄️  Running SQL Query: {query[:200]}...")
    try:
        clean_query = _extract_sql_from_text(query)
        # Common typo normalization from LLM output.
        clean_query = re.sub(r'\bdesignatioon\b', 'designation', clean_query, flags=re.IGNORECASE)
        clean_query = re.sub(r'\blikee\b', 'LIKE', clean_query, flags=re.IGNORECASE)
        # Schema guardrail: `cutoffs` uses `branch` (not `department`).
        if re.search(r'\bfrom\s+cutoffs\b', clean_query, re.IGNORECASE):
            clean_query = re.sub(r'\bdepartment\b', 'branch', clean_query, flags=re.IGNORECASE)
        print(f"   🗄️  Cleaned SQL: {clean_query[:200]}")
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


# ── System prompts ──────────────────────────────────────────────────────────

# ROUTING_SYSTEM: used by llama3.2:1b for Call #1.
# ONLY classifies which tool to use — does NOT write SQL.
# Kept extremely short so the 1B model can follow it reliably.
ROUTING_SYSTEM = """You are a router for the VJTI Campus Assistant.
Your ONLY job: decide which tool to use. Output ONE JSON line. Nothing else.

TOOLS:
- Campus_SQL_Data     : faculty, HOD, programs, intake, cutoffs, percentiles
- PDF_Knowledge_Base  : hostel, Block, PG, fees, calendars, dates, policies, reservation norms, anti-ragging, attendance

OUTPUT FORMAT (copy exactly, fill in the blanks):
{"tool": "Campus_SQL_Data", "query": "short description of what data is needed"}
{"tool": "PDF_Knowledge_Base", "query": "short description of what to look up"}

EXAMPLES:
Q: "What is the intake of B.Tech Computer Engineering?"
A: {"tool": "Campus_SQL_Data", "query": "intake of B.Tech Computer Engineering"}

Q: "List all M.Tech programs and their intakes"
A: {"tool": "Campus_SQL_Data", "query": "all M.Tech programs and intakes"}

Q: "Who is the HOD of IT department?"
A: {"tool": "Campus_SQL_Data", "query": "HOD of IT department"}

Q: "What is Block C hostel structure?"
A: {"tool": "PDF_Knowledge_Base", "query": "Block C hostel structure"}

Q: "When do classes start for FY students?"
A: {"tool": "PDF_Knowledge_Base", "query": "FY class start date"}

Q: "What is the cutoff for Computer Engineering OBC 2024?"
A: {"tool": "Campus_SQL_Data", "query": "cutoff Computer Engineering OBC 2024"}

Respond with ONLY the JSON line, no explanation before or after."""


# SQL_GEN_SYSTEM: used by llama3:8b to write the actual SQL query.
# Separated from routing so the capable model handles all SQL complexity.
SQL_GEN_SYSTEM = """You are a SQLite expert for the VJTI campus database.
Write ONE valid SQLite SELECT query. Output ONLY the raw SQL — no markdown fences, no explanation, no preamble.

DATABASE SCHEMA:
- faculty(name, department, designation, email, aliases)
- cutoffs(year, branch, category, percentile)
- programs(program_name, level, department, intake, duration_years)

CRITICAL RULES:
1. Use LIKE '%keyword%' for ALL string comparisons — NEVER use = for text.
2. SYNONYM MAPPING:
   - 'IT' or 'Information Technology' → department/branch LIKE '%Information Technology%'
   - 'EXTC' or 'ENTC' or 'Telecom' → LIKE '%Electronics & Telecom%'
   - 'Electronics' (alone, no EXTC/Telecom) → LIKE '%Electronics Engineering%'
   - 'Computer' → LIKE '%Computer%'
   - 'Civil' → LIKE '%Civil%'
   - 'Mechanical' → LIKE '%Mechanical%'
   - 'HOD' / 'Head' / 'Head of Department' → designation LIKE '%HOD%'
   - 'Director' → designation LIKE '%Director%'
   - 'Deputy Director' → designation LIKE '%Deputy Director%'
   - 'Dean' → designation LIKE '%Dean%'
   - 'mail' / 'email' / 'contact' / 'email id' / 'mail id' → email column
   - department aliases:
       * CE/Civil → '%Civil%'
       * CSE/CS/Computer → '%Computer%'
       * IT → '%Information Technology%' OR '%Computer & IT%'
       * EE/Electrical → '%Electrical%'
       * EXTC/ENTC/Telecom → '%Electronics%'
       * Mech/Mechanical → '%Mechanical%'
       * Prod/Production → '%Production%'
       * Textile → '%Textile%'
       * Humanities/Management/HS → '%Humanities%'
       * Structural/ST → '%Structural%'
   - 'email' / 'mail' / 'contact' → email column
    - 'office' / 'room' / 'cabin' in faculty context → return name + email (no cabin column in this schema)
3. programs TABLE:
   - B.Tech → level = 'Undergraduate'
   - M.Tech → level = 'Postgraduate'
   - For intake queries: SELECT program_name, intake FROM programs WHERE ...
   - For ALL M.Tech programs: SELECT program_name, intake FROM programs WHERE level = 'Postgraduate'
4. cutoffs TABLE — CATEGORY CODES (use LIKE):
   - Open/General → LIKE '%OPENS%'
   - OBC → LIKE '%OBCS%'
   - SC → LIKE '%SCS%'
   - ST → LIKE '%STS%'
   - EWS → LIKE '%EWS%'
   - ALWAYS include the category column in SELECT when querying cutoffs.
5. faculty TABLE:
   - HOD query example: SELECT name, email FROM faculty WHERE designation LIKE '%HOD%' AND department LIKE '%Computer%'
    - Director email example: SELECT name, designation, email FROM faculty WHERE designation LIKE '%Director%' ORDER BY CASE WHEN designation LIKE '%Deputy%' THEN 1 ELSE 0 END, name
    - Dean contact example: SELECT name, designation, email FROM faculty WHERE designation LIKE '%Dean%'
6. ELIGIBILITY: If user gives a percentile score → SELECT branch, category, percentile FROM cutoffs WHERE percentile <= <score> AND year = 2025
7. COMPARISON QUERIES: For "compare ... between YEAR1 and YEAR2", return both years in one query using IN (...) and ORDER BY year ASC.
7. Output ONLY the SQL query. No text before or after. No semicolons unless at the very end."""


SQL_FIX_SYSTEM = """You repair broken SQLite SELECT queries for this exact schema.
Return ONLY one corrected SQL query.

SCHEMA:
- faculty(name, department, designation, email)
- cutoffs(year, branch, category, percentile)
- programs(program_name, level, department, intake, duration_years)
"""


# RESPONSE_SYSTEM: used by llama3:8b for the final natural language answer.
RESPONSE_SYSTEM = """You are the VJTI Smart Campus Assistant. Answer clearly and helpfully.

CRITICAL RULES:
- If TOOL OUTPUT is provided, base your answer ONLY on that data. Do not guess or use training knowledge.
- If the tool output is empty or says "No matching records", say clearly: "I couldn't find that information in the database. Please verify the department name or try rephrasing."
- For SQL results: present data in a clean, readable format (table or bullet list as appropriate).
- For PDF results: cite the [OFFICIAL SOURCE] at the end of your answer.
- Never mention internal terms such as "TOOL OUTPUT", "router", "SQL error", or "database schema" in the final user-facing response.

SQL DATA RULES:
- Present intake numbers, cutoffs, faculty info exactly as returned — do not modify numbers.
- If multiple rows are returned, list all of them clearly.
- Always mention what the data represents (e.g., "The intake for B.Tech Computer Engineering is 60 students").
- For one value, respond in one concise sentence.
- For multiple rows, write a clean paragraph or sentence list in plain text.
- NEVER use markdown tables, pipe symbols (`|`), or spreadsheet-style formatting.

PDF DATA RULES:
1. BLOCK VERIFICATION: When asked about a specific hostel block, ONLY use data explicitly listed under that block's heading.
2. DO NOT MIX BLOCKS: Never attribute features of one block to another.
3. Cite [OFFICIAL SOURCE] at the end.

HOSTEL QUICK REFERENCE (use only if confirmed by tool output):
- BLOCK C: First-year B.Tech/Diploma. Ground (16 rooms + Mess), 1st floor (32 rooms), 2nd floor (32 rooms). 4 students/room.
- BLOCK D: Intermediate & Senior boys. 4 floors. Mostly 3-seater.
- PG-HOSTEL: Final year & PG. 6 floors. 2 students/room.
- BLOCKS A & B: Girls. 2 floors. 3 girls/room.

CALENDAR / DATES:
- Distinguish FY (First Year) vs SY (Senior Year). Senior Year starts July; First Year starts September.
- ERP Portal for registration: https://erp.vjti.ac.in/

RESERVATION NORMS (use only if confirmed by tool output):
- SC=13%, ST=7%, VJ/DT(A)=3%, NT-B=2.5%, NT-C=3.5%, NT-D=2%, SBC=2%, OBC=19%, EWS=10% (over & above intake).
- Female: 30% within every category (horizontal).
- PwD: 5%. Defense: 5%. Orphan: 1% (Open category only). TFWS: 5% over & above intake.

FEE POLICY:
- Do NOT state specific fee amounts. Inform that fees vary by category (Open/Reserved/TFWS) and direct user to the fee PDF.

EVENTS:
- Technovanza: December/January. Pratibimb: February.

ANTI-RAGGING:
- Step 1: Informal (Warden/Faculty). Step 2: Formal Written (Box/Dr. Gangopadhyay). Step 3: UGC portal. Step 4: Committee Enquiry."""


# ── Per-session conversation history ──
sessions = {}

# ═════════════════════════════════════════════════════════════════════════════
# INTERCEPT STACK  (evaluated top-to-bottom in _run_routing)
#
#  Layer 0 — _get_serve_pdf()        : serve fee/calendar PDF file directly
#  Layer 1 — _is_forced_pdf()        : force PDF_Knowledge_Base tool
#  Layer 2 — _try_hardcoded_answer() : return known reservation % instantly
#  Layer 3 — routing_llm (Call #1)   : small model picks tool only
#  Layer 4 — response_llm (Call #2)  : full model writes SQL + generates answer
# ═════════════════════════════════════════════════════════════════════════════

# ── Layer 0: Direct PDF serve ─────────────────────────────────────────────────

# ── Calendar detection ──
# Instead of exact multi-word phrases, we use TWO independent keyword sets.
# If the message contains at least one word from EACH set → it's a calendar query.
# This handles typos ("calender"), alternate word order, and synonym phrasings.

# Set A: words that signal the user wants a timetable / schedule document
_CAL_SIGNAL_WORDS = {
    # direct names
    "calendar", "calender",          # common typo
    # schedule synonyms
    "schedule", "timetable", "time-table",
    # date-related intents
    "dates", "important dates",
    # specific exam/event keywords that alone imply calendar context
    "mst", "ese", "exam date", "exam dates",
    "holiday", "holidays",
    "orientation",
    # class/lecture timing questions
    "class", "classes", "lecture", "lectures",
}

# Set B: words that signal a calendar SCOPE (what kind of calendar)
# If none of these are present we still serve the default calendar.
_CAL_SCOPE_WORDS = {
    # document-level scope
    "academic", "semester", "odd semester", "even semester",
    # action words that imply wanting a document
    "show", "give", "get", "send", "share", "display", "open",
    "see", "view", "check", "find", "want", "need",
    # time-intent words
    "when", "start", "end", "begin", "commence",
    "last date", "registration", "register",
    # schedule/timetable alone are strong enough scope signals
    "schedule", "timetable", "time-table",
    # year/level markers are also scope signals
    "first year", "second year", "third year", "fourth year",
    "fy", "sy", "ty", "be", "fresher", "freshman", "senior",
    "diploma", "mtech", "m.tech", "mca", "phd",
}

# Fee detection — same two-set approach
_FEE_SIGNAL_WORDS = {
    "fee", "fees", "tuition", "payment", "charges", "cost",
    "annual", "semester fee", "development fee", "mess fee",
    "hostel fee", "how much",
}
_FEE_SCOPE_WORDS = {
    "show", "give", "get", "send", "share", "display", "open",
    "see", "view", "check", "find", "want", "need",
    "structure", "details", "breakdown", "amount",
    "for", "of", "what", "total",
}

# Reservation-category phrasing should not be treated as fee/calendar intent.
_RESERVATION_QUERY_WORDS = {
    "reservation", "reserve", "reserved", "quota", "category",
    "sc", "st", "obc", "ews", "nt-b", "nt-c", "nt-d", "sbc", "vj", "tfws",
    "pwd", "female", "defense", "defence", "orphan",
}


def _has_term(msg: str, term: str) -> bool:
    """Whole-term matcher to avoid accidental substring hits (e.g. 'ese' in 'reserved')."""
    pattern = r'(?<!\w)' + re.escape(term.lower()) + r'(?!\w)'
    return re.search(pattern, msg.lower()) is not None


def _has_any_term(msg: str, terms) -> bool:
    return any(_has_term(msg, t) for t in terms)


def _is_calendar_query(msg: str) -> bool:
    """
    Returns True if the message is asking for a calendar/schedule PDF.
    Matches on: any calendar-signal word AND any scope word,
    OR any direct single-word trigger that alone is sufficient.
    """
    # Single-word triggers that are unambiguous on their own
    SOLO_TRIGGERS = {"mst", "ese"}
    if _has_any_term(msg, SOLO_TRIGGERS):
        return True
    has_signal = _has_any_term(msg, _CAL_SIGNAL_WORDS)
    has_scope  = _has_any_term(msg, _CAL_SCOPE_WORDS)
    return has_signal and has_scope


def _is_fee_query(msg: str) -> bool:
    """Returns True if the message is asking for a fee structure PDF."""
    if _has_any_term(msg, _RESERVATION_QUERY_WORDS):
        return False
    has_signal = _has_any_term(msg, _FEE_SIGNAL_WORDS)
    has_scope  = _has_any_term(msg, _FEE_SCOPE_WORDS)
    return has_signal and has_scope


# File routing: ordered list of (keyword_set, filename).
# First match wins. Keywords checked against the lowercased message.
FEE_FILE_ROUTING = [
    ({"working professional", "wp", "weekend"},       "Fees_Working_Professionals_UG_PG_2025_26.pdf"),
    ({"hostel fee", "hostel fees", "hostel"},         "Fees_Hostel_FY_and_Lateral_Entry_2025_26.pdf"),
    ({"lateral", "direct second year", "dsy"},        "Fees_BTech_Direct_Second_Year_Lateral_2025_26.pdf"),
    ({"sy", "second year", "third year", "mtech",
      "m.tech"},                                      "Fees_SY_Onwards_BTech_MTech_MCA_PhD_2025_26.pdf"),
    ({"fy", "first year", "mca", "phd"},              "Fees_FY_BTech_MTech_MCA_PhD_2025_26.pdf"),
]

CALENDAR_FILE_ROUTING = [
    ({"diploma"},                                                  "Calendar_Diploma_2025_26.pdf"),
    ({"working professional", "wp", "dsy"},                        "Calendar_DSY_WP_BTech_MTech_2025_26.pdf"),
    ({"fy", "first year", "first-year", "1st year", "fresher",
      "freshman", "frm", "fy student"},                            "Calendar_FY_BTech_MCA_MTech_PhD_2025_26.pdf"),
    ({"sy", "second year", "sy onwards", "senior",
      "third year", "fourth year", "ty", "be"},                    "Calendar_SY_Onwards_BTech_MCA_MTech_PhD_2025_26.pdf"),
]


def _get_serve_pdf(user_message: str) -> "tuple[str, str] | None":
    msg = user_message.lower()

    # ── Fee check ──
    if _is_fee_query(msg):
        for keywords, filename in FEE_FILE_ROUTING:
            if _has_any_term(msg, keywords):
                return (filename,
                        "Here is the relevant fee structure PDF. Fees vary by program and "
                        "category (Open/Reserved/TFWS) — please check the applicable section.")
        return ("Fees_FY_BTech_MTech_MCA_PhD_2025_26.pdf",
                "Here is the fee structure PDF. If you need a different program's fees "
                "(SY/MTech/WP/Hostel), please specify.")

    # ── Calendar check ──
    if _is_calendar_query(msg):
        for keywords, filename in CALENDAR_FILE_ROUTING:
            if _has_any_term(msg, keywords):
                return (filename,
                        "Here is the academic calendar PDF. Check the relevant semester "
                        "section for exact dates.")
        return ("Calendar_SY_Onwards_BTech_MCA_MTech_PhD_2025_26.pdf",
                "Here is the academic calendar PDF. If you need a different program's "
                "calendar (FY/Diploma/WP), please specify.")

    return None


# ── Layer 1: Forced PDF routing ───────────────────────────────────────────────
PDF_FORCE_KEYWORDS = {
    "reservation", "quota", "reserve", "reserved",
    "hostel" , "Block", "PG-Block",
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
    return any(kw in user_message.lower() for kw in PDF_FORCE_KEYWORDS)


# ── Layer 2: Hardcoded reservation facts ─────────────────────────────────────
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
    msg_lower = user_message.lower()
    if any(t in msg_lower for t in _DISQUALIFYING_TERMS):
        return None
    MUST_HAVE = [
        "percentage", "percent", "% reserved", "how much is reserved",
        "how much", "what is the reservation", "reserved for me",
        "quota for", "reservation for", "what percentage",
        "what percent", "belong to", "what is reserved",
    ]
    if not any(t in msg_lower for t in MUST_HAVE):
        return None
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


# ── _build_final_task_note ────────────────────────────────────────────────────
def _build_final_task_note(tool_name: str, user_message: str) -> str:
    """Returns context-sensitive grounding instruction for the response model."""
    if tool_name in ["Campus_SQL_Data", "SQL"]:
        return (
            "Use a professional tone. For single values, give one direct sentence. "
            "For multi-row SQL results, write a plain paragraph or sentence list (no table). "
            "Never use pipe symbols or markdown table format. "
            "Do not mention internal processing text (like TOOL OUTPUT or SQL errors). "
            "If rows are present, do not claim data is unavailable."
        )

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


# ── Shared trim helper ────────────────────────────────────────────────────────
def _trim_history(session_id: str, chat_history: list):
    """Keep sliding window at max 20 messages."""
    if len(chat_history) > 20:
        sessions[session_id] = chat_history[-10:]


# ── SQL generation by response_llm ───────────────────────────────────────────
def _generate_sql(user_message: str, intent_hint: str) -> str:
    """
    Uses response_llm (llama3:8b) to write the SQL query.
    Returns a clean SQL string ready to pass to db.run().
    """
    sql_prompt = (
        f"User question: \"{user_message}\"\n"
        f"Intent hint from router: {intent_hint}\n\n"
        f"Write the SQLite query now:"
    )
    print(f"   ✍️  Asking {RESPONSE_MODEL} to write SQL...")
    sql_response = response_llm.invoke([
        SystemMessage(content=SQL_GEN_SYSTEM),
        HumanMessage(content=sql_prompt)
    ])
    raw_sql = sql_response.content.strip()
    print(f"   📝 Raw SQL from {RESPONSE_MODEL}: {raw_sql[:300]}")
    clean_sql = _extract_sql_from_text(raw_sql)
    clean_sql = _sanitize_faculty_role_sql(user_message, clean_sql)
    print(f"   ✅ Extracted SQL: {clean_sql[:300]}")
    return clean_sql


def _sanitize_faculty_role_sql(user_message: str, sql_text: str) -> str:
    """For role-only faculty queries, remove accidental department filters from generated SQL."""
    msg_lower = f" {user_message.lower()} "
    sql = sql_text

    is_faculty_sql = re.search(r'\bfrom\s+faculty\b', sql, re.IGNORECASE) is not None
    asks_role = any(k in msg_lower for k in [" director", " dean", " hod", "head of department", "head "])
    has_explicit_dept = any(
        k in msg_lower
        for k in [
            " civil", " computer", " information technology", " it ", " electrical", " electronics",
            " extc", " entc", " telecom", " mechanical", " production", " textile", " humanities", " structural"
        ]
    )

    if not (is_faculty_sql and asks_role and not has_explicit_dept):
        return sql

    # Remove accidental department predicates when the user did not ask for a department.
    sql = re.sub(r"\s+AND\s+department\s+LIKE\s+'[^']*'", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"department\s+LIKE\s+'[^']*'\s+AND\s+", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bWHERE\s*\)", "WHERE 1=1)", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bWHERE\s*$", "", sql, flags=re.IGNORECASE)
    return sql


def _fix_sql(user_message: str, bad_sql: str, sql_error: str) -> str:
    """Attempt one SQL repair pass using the worker model and DB error context."""
    fix_prompt = (
        f"User question: \"{user_message}\"\n"
        f"Broken SQL:\n{bad_sql}\n\n"
        f"SQLite error:\n{sql_error}\n\n"
        "Return ONLY corrected SQL for the schema."
    )
    fix_response = response_llm.invoke([
        SystemMessage(content=SQL_FIX_SYSTEM),
        HumanMessage(content=fix_prompt)
    ])
    repaired = _extract_sql_from_text(fix_response.content.strip())
    print(f"   🛠️  Repaired SQL: {repaired[:300]}")
    return repaired


def _run_sql_with_repair(user_message: str, sql_text: str) -> tuple[str, str]:
    """Executes SQL once, then retries once with repaired SQL if needed."""
    result = tools_map["Campus_SQL_Data"](sql_text)
    final_sql = sql_text

    if isinstance(result, str) and result.startswith("SQL Error:"):
        repaired_sql = _fix_sql(user_message, sql_text, result)
        retry_result = tools_map["Campus_SQL_Data"](repaired_sql)
        if not (isinstance(retry_result, str) and retry_result.startswith("SQL Error:")):
            return retry_result, repaired_sql
        return retry_result, repaired_sql

    return result, final_sql


def _dept_patterns_for_query(msg_lower: str) -> list[str]:
    """Returns SQL LIKE patterns for detected department aliases in user query."""
    patterns = []

    alias_map = {
        "Civil": [" civil", "civil engineering", " ce "],
        "Computer": ["computer", " cse", " cs "],
        "Information Technology": [" information technology", " it ", " it department"],
        "Electrical": ["electrical", " ee "],
        "Electronics": ["extc", "entc", "telecom", "electronics"],
        "Mechanical": ["mechanical", " mech", " me "],
        "Production": ["production", " prod "],
        "Textile": ["textile"],
        "Humanities": ["humanities", "management", " hs "],
        "Structural": ["structural", " st "],
    }

    padded = f" {msg_lower} "
    for pattern, keys in alias_map.items():
        if any(k in padded for k in keys):
            patterns.append(pattern)
    return patterns


def _try_faculty_contact_answer(user_message: str) -> str | None:
    """Direct faculty contact resolver for role/name email queries (LLM bypass)."""
    msg_lower = user_message.lower().strip()
    asks_contact = any(k in msg_lower for k in ["mail", "email", "contact", "email id", "mail id"])
    is_faculty_intent = any(k in msg_lower for k in ["director", "dean", "hod", "head of department", "prof", "faculty"])
    if not (asks_contact or is_faculty_intent):
        return None

    where_clauses = []
    params: list[str] = []

    # Role filters
    if "deputy director" in msg_lower:
        where_clauses.append("designation LIKE ?")
        params.append("%Deputy Director%")
    elif "director" in msg_lower:
        where_clauses.append("designation LIKE ?")
        params.append("%Director%")

    if "dean" in msg_lower:
        where_clauses.append("designation LIKE ?")
        params.append("%Dean%")

    if any(k in msg_lower for k in ["hod", "head of department", "head "]):
        where_clauses.append("designation LIKE ?")
        params.append("%HOD%")

    # Department alias filters
    dept_patterns = _dept_patterns_for_query(msg_lower)
    if dept_patterns:
        dept_sub = []
        for pat in dept_patterns:
            dept_sub.append("department LIKE ?")
            params.append(f"%{pat}%")
        where_clauses.append("(" + " OR ".join(dept_sub) + ")")

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    sql = (
        "SELECT name, designation, email "
        "FROM faculty"
        f"{where_sql} "
        "ORDER BY "
        "CASE WHEN designation LIKE '%Director%' THEN 0 "
        "WHEN designation LIKE '%Dean%' THEN 1 "
        "WHEN designation LIKE '%HOD%' THEN 2 ELSE 3 END, "
        "name"
    )

    try:
        conn = sqlite3.connect("campus.db")
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    # Keep response concise and paragraph-style.
    if len(rows) == 1:
        name, designation, email = rows[0]
        return f"The email for {designation} {name} is {email}."

    parts = []
    for name, designation, email in rows[:6]:
        parts.append(f"{designation} {name}: {email}")
    return "Here are the relevant faculty contacts: " + "; ".join(parts) + "."


def _table_to_paragraph(text: str) -> str:
    """Converts markdown table output into plain paragraph text."""
    lines = [ln.strip() for ln in text.splitlines()]
    table_start = -1
    for i in range(len(lines) - 1):
        if '|' in lines[i] and re.search(r'^\|?\s*:?-{3,}', lines[i + 1].replace(' ', '')):
            table_start = i
            break

    if table_start == -1:
        return text

    header_line = lines[table_start].strip().strip('|')
    headers = [h.strip() for h in header_line.split('|') if h.strip()]
    if not headers:
        return text

    row_items = []
    i = table_start + 2
    while i < len(lines):
        row = lines[i]
        if '|' not in row or not row:
            break
        cols = [c.strip() for c in row.strip('|').split('|')]
        if len(cols) < len(headers):
            break
        pairs = []
        for idx, head in enumerate(headers):
            value = cols[idx].strip()
            if value:
                pairs.append(f"{head}: {value}")
        if pairs:
            row_items.append('; '.join(pairs))
        i += 1

    if not row_items:
        return text.replace('|', ' ')

    prefix = "Here are the details: "
    paragraph = prefix + "; ".join(row_items) + "."

    before = "\n".join([ln for ln in lines[:table_start] if ln])
    after = "\n".join([ln for ln in lines[i:] if ln])
    merged_parts = [part for part in [before, paragraph, after] if part]
    return "\n\n".join(merged_parts)


def _sanitize_response_style(text: str) -> str:
    """Final style sanitizer to avoid markdown table output in user-facing responses."""
    cleaned = _table_to_paragraph(text)
    if '|' in cleaned and re.search(r'^\s*\|', cleaned, re.MULTILINE):
        cleaned = cleaned.replace('|', ' ')
    return cleaned

# add this near your other helpers (for example after _generate_sql)

def _build_nav_image_url(filename: str | None) -> "str | None":
    if not filename:
        return None
    safe = str(filename).strip().lstrip("/")
    return f"/nav-images/{safe}"


def _attach_image_urls(directions: dict | None) -> dict | None:
    if not directions:
        return None
    for step in directions.get("steps", []):
        step["image_url"] = _build_nav_image_url(step.get("image"))
    return directions

# ── Core shared logic ─────────────────────────────────────────────────────────
def _run_routing(user_message: str, chat_history: list):
    
    # ── Navigation intercept (before all other layers) ──
    nav_intent = detect_navigation_intent(user_message)
    if nav_intent:
        origin, destination = nav_intent
        result = get_navigation(origin, destination)
        result["directions"] = _attach_image_urls(result.get("directions"))
        return ("navigation", result, None)
    
    """
    Runs Layers 0-4 and returns either:
      ("serve_pdf",  pdf_filename, friendly_msg)  — direct PDF serve
      ("hardcoded",  answer_text,  source_file)   — hardcoded fact
      ("tool",       tool_name,    query_arg)      — tool to execute
      ("direct",     answer_text,  None)           — direct LLM answer (no tool)
    """
    # Layer 0: Direct PDF file serving
    serve = _get_serve_pdf(user_message)
    if serve:
        return ("serve_pdf", serve[0], serve[1])

    # Layer 2: Hardcoded reservation answers
    hardcoded = _try_hardcoded_answer(user_message)
    if hardcoded:
        return ("hardcoded", hardcoded, "Reservation_Norms.pdf")

    # Layer 2.5: Deterministic faculty contact lookup for roles/departments.
    faculty_contact = _try_faculty_contact_answer(user_message)
    if faculty_contact:
        return ("direct", faculty_contact, None)

    # Layer 1: Forced PDF routing for policy/reservation keywords
    if _is_forced_pdf(user_message):
        safe_query = user_message.replace('"', "'")
        content = f'{{"tool": "PDF_Knowledge_Base", "query": "{safe_query}"}}'
    else:
        # Layer 3: routing_llm — ONLY classifies which tool to use
        routing_sys = SystemMessage(content=ROUTING_SYSTEM)
        messages_routing = [routing_sys, HumanMessage(content=user_message)]
        print(f"🔀 Routing with {ROUTING_MODEL}...")
        routing_response = routing_llm.invoke(messages_routing)
        content = routing_response.content.strip()
        print(f"   Router decision: {content[:200]}")

    json_match = re.search(
        r'\{\s*"tool"\s*:\s*"([^"]+)"\s*,\s*"query"\s*:\s*"([^"]*?)"\s*\}',
        content, re.DOTALL
    )

    if json_match:
        tool_name = json_match.group(1).strip()
        intent_hint = json_match.group(2).strip()

        if tool_name in ("SQL", "sql"):
            tool_name = "Campus_SQL_Data"
        elif tool_name in ("PDF", "pdf"):
            tool_name = "PDF_Knowledge_Base"

        if tool_name in tools_map:
            if tool_name == "Campus_SQL_Data":
                # Layer 4a: response_llm writes the actual SQL
                query_arg = _generate_sql(user_message, intent_hint)
            else:
                # PDF: use the intent hint as the search query
                query_arg = intent_hint if intent_hint else user_message
            return ("tool", tool_name, query_arg)

    print("⚠️  Router output not parseable — falling back to direct response_llm answer")
    fallback_msg = response_llm.invoke([
        SystemMessage(content=RESPONSE_SYSTEM),
        HumanMessage(content=user_message)
    ])
    return ("direct", fallback_msg.content, None)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    """Standard JSON response endpoint (non-streaming)."""
    data         = request.json
    user_message = data.get("message", "").strip()
    session_id   = data.get("session_id", "default")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in sessions:
        sessions[session_id] = []

    chat_history = sessions[session_id]
    response_sys = SystemMessage(content=RESPONSE_SYSTEM)
    chat_history.append(HumanMessage(content=user_message))

    route_type, arg1, arg2 = _run_routing(user_message, chat_history)

    # ── serve_pdf ──
    if route_type == "serve_pdf":
        pdf_filename, friendly_msg = arg1, arg2
        print(f"📄 Serving PDF directly: {pdf_filename}")
        chat_history.append(AIMessage(content=friendly_msg))
        _trim_history(session_id, chat_history)
        return jsonify({
            "reply":          friendly_msg,
            "serve_pdf":      pdf_filename,
            "serve_pdf_path": os.path.join(DOCS_FOLDER, pdf_filename),
        })

    # ── hardcoded ──
    if route_type == "hardcoded":
        answer, source_file = arg1, arg2
        print(f"📋 Hardcoded fact returned")
        chat_history.append(AIMessage(content=answer))
        _trim_history(session_id, chat_history)
        return jsonify({"reply": answer, "source_file": source_file})
    
        # ── navigation ──
    if route_type == "navigation":
        nav_result = arg1
        nav_text = nav_result.get("summary", "")
        chat_history.append(AIMessage(content=nav_text))
        _trim_history(session_id, chat_history)
        return jsonify({
            "reply": nav_text,
            "navigation": nav_result.get("directions"),
        })

    # ── direct (no tool call) ──
    if route_type == "direct":
        chat_history.append(AIMessage(content=arg1))
        _trim_history(session_id, chat_history)
        return jsonify({"reply": arg1})

    # ── tool call → response_llm ──
    tool_name, query_arg = arg1, arg2
    print(f"⚙️  Executing {tool_name}...")
    if tool_name in ["Campus_SQL_Data", "SQL"]:
        result, query_arg = _run_sql_with_repair(user_message, query_arg)
    else:
        result = tools_map[tool_name](query_arg)
    final_task_note = _build_final_task_note(tool_name, user_message)

    print(f"   📊 Tool result (first 300 chars): {str(result)[:300]}")

    if tool_name in ["Campus_SQL_Data", "SQL"]:
        chat_history.append(AIMessage(content=f'{{"tool":"{tool_name}","sql":"{query_arg}"}}'))
        chat_history.append(HumanMessage(
            content=(
                f"SQL RESULT:\n{result}\n\n"
                f"FINAL TASK: Use only this SQL result to answer the user's question: '{user_message}'. "
                f"{final_task_note}"
            )
        ))
        print(f"✍️  Generating answer with {RESPONSE_MODEL}...")
        final_response = response_llm.invoke([response_sys] + chat_history[-6:])
    else:
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
        print(f"✍️  Generating answer with {RESPONSE_MODEL}...")
        final_response = response_llm.invoke([response_sys, isolated_prompt])
        chat_history.append(AIMessage(content=f'{{"tool":"{tool_name}","query":"{query_arg}"}}'))
        chat_history.append(HumanMessage(
            content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: answer '{user_message}'. {final_task_note}"
        ))

    bot_text = _sanitize_response_style(final_response.content)
    chat_history.append(final_response)
    _trim_history(session_id, chat_history)

    source_file  = None
    source_match = re.search(r'([A-Za-z0-9_\-]+\.pdf)', bot_text)
    if source_match:
        source_file = source_match.group(1)

    response_data = {"reply": bot_text}
    if source_file:
        response_data["source_file"] = source_file
        response_data["source_path"] = os.path.join(DOCS_FOLDER, source_file)
    return jsonify(response_data)


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream_endpoint():
    """
    Option B — Streaming SSE endpoint.
    Sends tokens to the frontend as they are generated so the user sees
    text appearing immediately instead of waiting for the full response.

    Response format: Server-Sent Events (SSE)
      data: {"token": "Hello"}
      data: {"token": " there"}
      data: {"done": true, "source_file": "...", "serve_pdf": "..."}

    Frontend usage (fetch with ReadableStream):
      const resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ message, session_id })
      })
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const lines = decoder.decode(value).split('\\n')
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = JSON.parse(line.slice(6))
            if (payload.token) appendTokenToUI(payload.token)
            if (payload.done)  handleDone(payload)
          }
        }
      }
    """
    data         = request.json
    user_message = data.get("message", "").strip()
    session_id   = data.get("session_id", "default")

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in sessions:
        sessions[session_id] = []

    chat_history = sessions[session_id]
    response_sys = SystemMessage(content=RESPONSE_SYSTEM)
    chat_history.append(HumanMessage(content=user_message))

    def generate():
        route_type, arg1, arg2 = _run_routing(user_message, chat_history)

        # ── serve_pdf ──
                # ── navigation ──
        if route_type == "navigation":
            nav_result = arg1
            nav_text = nav_result.get("summary", "")
            chat_history.append(AIMessage(content=nav_text))
            _trim_history(session_id, chat_history)
            for word in nav_text.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            yield f"data: {json.dumps({'done': True, 'navigation': nav_result.get('directions')})}\n\n"
            return
        
        if route_type == "serve_pdf":
            pdf_filename, friendly_msg = arg1, arg2
            print(f"📄 Serving PDF directly: {pdf_filename}")
            chat_history.append(AIMessage(content=friendly_msg))
            _trim_history(session_id, chat_history)
            for word in friendly_msg.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            yield f"data: {json.dumps({'done': True, 'serve_pdf': pdf_filename, 'serve_pdf_path': os.path.join(DOCS_FOLDER, pdf_filename)})}\n\n"
            return

        # ── hardcoded ──
        if route_type == "hardcoded":
            answer, source_file = arg1, arg2
            print(f"📋 Hardcoded fact returned")
            chat_history.append(AIMessage(content=answer))
            _trim_history(session_id, chat_history)
            for word in answer.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            yield f"data: {json.dumps({'done': True, 'source_file': source_file})}\n\n"
            return

        # ── direct ──
        if route_type == "direct":
            chat_history.append(AIMessage(content=arg1))
            _trim_history(session_id, chat_history)
            for word in arg1.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            return

        # ── tool call → stream response_llm ──
        tool_name, query_arg = arg1, arg2
        print(f"⚙️  Executing {tool_name}...")
        if tool_name in ["Campus_SQL_Data", "SQL"]:
            result, query_arg = _run_sql_with_repair(user_message, query_arg)
        else:
            result = tools_map[tool_name](query_arg)
        final_task_note = _build_final_task_note(tool_name, user_message)

        print(f"   📊 Tool result (first 300 chars): {str(result)[:300]}")

        if tool_name in ["Campus_SQL_Data", "SQL"]:
            chat_history.append(AIMessage(content=f'{{"tool":"{tool_name}","sql":"{query_arg}"}}'))
            chat_history.append(HumanMessage(
                content=(
                    f"SQL RESULT:\n{result}\n\n"
                    f"FINAL TASK: Use only this SQL result to answer the user's question: '{user_message}'. "
                    f"{final_task_note}"
                )
            ))
            stream_messages = [response_sys] + chat_history[-6:]
        else:
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
            stream_messages = [response_sys, isolated_prompt]
            chat_history.append(AIMessage(content=f'{{"tool":"{tool_name}","query":"{query_arg}"}}'))
            chat_history.append(HumanMessage(
                content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: answer '{user_message}'. {final_task_note}"
            ))

        print(f"✍️  Streaming answer with {RESPONSE_MODEL}...")
        full_response = ""
        try:
            for chunk in response_llm.stream(stream_messages):
                token = chunk.content
                if token:
                    full_response += token
        except Exception as e:
            print(f"❌ Streaming error: {e}")
            yield f"data: {json.dumps({'token': '[Error during streaming]'})}\n\n"

        cleaned_response = _sanitize_response_style(full_response)
        for word in cleaned_response.split(" "):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"
        chat_history.append(AIMessage(content=cleaned_response))
        _trim_history(session_id, chat_history)

        source_file  = None
        source_match = re.search(r'([A-Za-z0-9_\-]+\.pdf)', cleaned_response)
        if source_match:
            source_file = source_match.group(1)

        done_payload = {"done": True, "final_reply": cleaned_response}
        if source_file:
            done_payload["source_file"] = source_file
            done_payload["source_path"] = os.path.join(DOCS_FOLDER, source_file)
        yield f"data: {json.dumps(done_payload)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/api/history", methods=["GET"])
def history_endpoint():
    session_id = request.args.get("session_id", "default")
    if session_id not in sessions:
        return jsonify({"session_id": session_id, "history": []})
    serialized = []
    for msg in sessions[session_id]:
        if isinstance(msg, HumanMessage):
            serialized.append({"role": "user",      "content": msg.content})
        elif isinstance(msg, AIMessage):
            serialized.append({"role": "assistant", "content": msg.content})
    return jsonify({"session_id": session_id, "history": serialized})


@app.route("/api/reset", methods=["POST"])
def reset_endpoint():
    data       = request.json or {}
    session_id = data.get("session_id", "default")
    if session_id in sessions:
        sessions.pop(session_id)
    return jsonify({"status": "ok", "message": f"Session '{session_id}' cleared."})


@app.route("/api/sessions", methods=["GET"])
def sessions_endpoint():
    return jsonify({
        "sessions": [
            {"session_id": sid, "message_count": len(msgs)}
            for sid, msgs in sessions.items()
        ]
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status":         "ok",
        "routing_model":  ROUTING_MODEL,
        "response_model": RESPONSE_MODEL,
    })


@app.route("/debug/docs", methods=["GET"])
def debug_docs():
    import glob
    files = glob.glob(os.path.join(DOCS_FOLDER, "*.pdf"))
    return {
        "docs_folder": DOCS_FOLDER,
        "exists":      os.path.isdir(DOCS_FOLDER),
        "pdf_files":   sorted([os.path.basename(f) for f in files]),
    }


@app.route("/docs/<path:filename>", methods=["GET"])
def serve_document(filename):
    """Serve PDFs from campus_documents."""
    return send_from_directory(DOCS_FOLDER, filename)

@app.route("/nav-images/<path:filename>", methods=["GET"])
def serve_navigation_image(filename):
    """Serve navigation reference images to the frontend."""
    return send_from_directory(NAV_IMAGES_FOLDER, filename)

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"🤖 VJTI Bot API starting...")
    print(f"   Routing model  : {ROUTING_MODEL}  (Call #1 — picks tool only)")
    print(f"   Response model : {RESPONSE_MODEL}  (Call #2 — writes SQL + answers)")
    print(f"   Docs folder    : {DOCS_FOLDER}")
    print(f"   Navigation images folder : {NAV_IMAGES_FOLDER}")
    print(f"   Endpoints      : /api/chat         (JSON)")
    print(f"                    /api/chat/stream  (SSE streaming)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)