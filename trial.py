import os
import sqlite3
import json
import re
import webbrowser # For opening files during local demo
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# 1. CONFIGURATION
MODEL_NAME = "llama3" 
DOCS_FOLDER = "./campus_documents"

# 2. CONNECT TO DATABASES
db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# 3. DEFINE THE TOOLS
def pdf_search(query):
    """Retrieves text from PDFs and tracks file paths for the attachment feature."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    raw_docs = vector_db.similarity_search(query, k=15)
    
    # --- DEBUG: SHOW RETRIEVED SOURCES IN TERMINAL ---
    retrieved_sources = list(set([os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")
    
    # --- ENHANCED KEYWORD RE-RANKER ---
    block_match = re.search(r'Block\s+([A-Z])', query, re.IGNORECASE)
    pg_match = re.search(r'(PG|Postgraduate)\s*Hostel', query, re.IGNORECASE)
    fee_match = re.search(r'(Fee|Tuition|TFWS|Refund|Amount|Deposit|Open)', query, re.IGNORECASE)
    
    prioritized_docs = []
    other_docs = []
    
    for d in raw_docs:
        content = d.page_content.upper()
        source_name = os.path.basename(d.metadata.get('source', '')).upper()
        
        is_priority = False
        if block_match and f"BLOCK {block_match.group(1).upper()}" in content:
            is_priority = True
        elif pg_match and ("PG-HOSTEL" in content or "PG HOSTEL" in content or "POSTGRADUATE" in content):
            is_priority = True
        elif fee_match and "FEES_" in source_name:
            is_priority = True
            
        if is_priority:
            prioritized_docs.append(d)
        else:
            other_docs.append(d)
    
    final_docs = (prioritized_docs + other_docs)[:8]
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

# 4. INITIALIZE OLLAMA
llm = ChatOllama(model=MODEL_NAME, temperature=0)

tools_map = {
    "PDF_Knowledge_Base": pdf_search,
    "Campus_SQL_Data": sql_query,
    "SQL": sql_query,
    "PDF": pdf_search
}

# 5. THE CHAT LOOP
def chat():
    print("\n" + "="*50)
    print(f"🤖 VJTI Bot (Local {MODEL_NAME}) is Online!")
    print("Verification Mode: Check Terminal for Source Document IDs.")
    print("Type 'exit' to quit.")
    print("="*50)
    
    system_instruction = """You are the VJTI Smart Campus Assistant.

ROUTING PRIORITY (CRITICAL):
- Use 'Campus_SQL_Data' (or simply 'SQL') for: Lists of programs, intake numbers, faculty locations, HOD names, and cutoffs.
- Use 'PDF_Knowledge_Base' (or simply 'PDF') for: Hostel structure, room counts, fees, and policies.
- CRITICAL: Hostel "Block C" structure is ONLY in the PDF. NEVER use SQL for hostels.

SQL RULES (STRICT SCHEMA MAPPING):
1. 'cutoffs' Table: Columns are [year, branch, category, percentile]. NEVER use 'program' or 'program_name' in this table.
2. 'programs' Table: Columns are [program_name, level, department, intake, duration_years].
   - For M.Tech, level = 'Postgraduate'.
   - For B.Tech, level = 'Undergraduate'.
3. 'faculty' Table: Columns are [name, department, designation, email, cabin_location].
   - ALWAYS use LIKE '%keyword%' for the 'department' column to ensure partial matches (e.g., searching for 'Electrical' should use department LIKE '%Electrical%' to match 'Electrical Engineering').
   - HOD search: WHERE designation LIKE '%HOD%' AND department LIKE '%Computer%'.

DEMO QUESTION TEMPLATES:
- M.Tech Intakes: SELECT program_name, intake FROM programs WHERE level = 'Postgraduate' AND program_name LIKE 'M.Tech%';
- Cutoff Comparison: SELECT year, percentile FROM cutoffs WHERE branch = 'Computer Engineering' AND category = 'GOPENS' AND (year=2024 OR year=2025);
- B.Tech Intake: SELECT intake FROM programs WHERE program_name = 'B.Tech Computer Engineering';

PDF RULES (STRICT GROUNDING):
- You MUST answer ONLY based on the provided TOOL OUTPUT.
- DO NOT GUESS NUMBERS. If data is missing from the output, say 'I don't have that info'.
- When answering from a PDF, YOU MUST CITE the filename from the [OFFICIAL SOURCE] tag.

FEE POLICY (CRITICAL):
- For any questions regarding tuition fees, development fees, or total annual amounts, DO NOT state any numerical figures or currency amounts.
- Inform the user that the fee structure is complex due to various categories (Open, Reserved, TFWS).
- Direct the user to cross-verify the details using the specific PDF file provided in your response.

TO USE A TOOL, respond ONLY with this JSON format:
{"tool": "Campus_SQL_Data", "query": "SELECT ..."}
"""
    messages = [SystemMessage(content=system_instruction)]

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit", "bye"]: break
            if not user_input.strip(): continue
                
            messages.append(HumanMessage(content=user_input))
            
            response = llm.invoke(messages)
            content = response.content.strip()
            
            json_match = re.search(r'\{.*"tool":\s*"(.*?)",\s*"query":\s*"(.*?)"\s*\}', content, re.DOTALL)
            
            if json_match:
                try:
                    tool_call_json = json.loads(json_match.group(0))
                    tool_name = tool_call_json.get("tool")
                    query_arg = tool_call_json.get("query")
                    
                    if tool_name in tools_map:
                        result = tools_map[tool_name](query_arg)
                        
                        if tool_name in ["Campus_SQL_Data", "SQL"]:
                            final_task_note = "For cutoffs/intakes, use a clear Markdown table."
                        else:
                            final_task_note = "REMINDER: For fee queries, do not state numbers. Provide the official filename for cross-verification. For Hostels, report the exact structure found."

                        messages.append(AIMessage(content=content))
                        messages.append(HumanMessage(content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: Based ONLY on this data, answer: '{user_input}'. {final_task_note}"))
                        
                        final_response = llm.invoke(messages)
                        bot_text = final_response.content
                        
                        # --- PDF ATTACHMENT LOGIC ---
                        source_match = re.search(r'([A-Za-z0-9_-]+\.pdf)', bot_text)
                        attachment_msg = ""
                        if source_match:
                            filename = source_match.group(1)
                            full_path = os.path.join(DOCS_FOLDER, filename)
                            attachment_msg = f"\n\n📎 [Attachment Found: {filename}]\n> Location: {full_path}\n> (You can verify this document in your campus_documents folder)"
                        
                        print(f"\nBot: {bot_text}{attachment_msg}")
                        messages.append(final_response)
                    else:
                        print(f"\nBot: [Internal Error] Invalid tool: {tool_name}")
                except Exception as e:
                    print(f"\nBot: {content}")
            else:
                print(f"\nBot: {content}")
                messages.append(response)

        except Exception as e:
            print(f"\nBot: Error: {str(e)}")

if __name__ == "__main__":
    chat()