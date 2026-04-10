import os
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase

# ── Paths & Connections ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_FOLDER = os.path.join(BASE_DIR, "campus_documents")

db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

def pdf_search(query):
    """Retrieves text from PDFs with an enhanced re-ranker for structural data."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    raw_docs = vector_db.similarity_search(query, k=15)

    retrieved_sources = list(set([os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")

    target_k    = ["TARGET", "B.TECH", "DIPLOMA", "FIRST YEAR", "FY", "EXCLUSIVELY", "SENIOR", "SY", "PG"]
    structure_k = ["FLOOR", "STRUCTURE", "ROOM", "CAPACITY", "OCCUPANCY", "SEATER", "GROUND"]
    fee_k       = ["FEE", "TUITION", "MESS", "PAYMENT", "SBI", "CONTRACTOR", "REFUND", "TFWS"]
    cal_k       = ["CALENDAR", "SCHEDULE", "DATE", "SEMESTER", "EXAM", "ESE", "MST", "CLASSES",
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