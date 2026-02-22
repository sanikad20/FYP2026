import os
import sqlite3
import json
import re
import webbrowser
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
    """Retrieves text from PDFs with an enhanced re-ranker for structural data."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    # k=15 gives a wide net for similarity before we re-rank
    raw_docs = vector_db.similarity_search(query, k=15)
    
    # --- DEBUG: SHOW RETRIEVED SOURCES ---
    retrieved_sources = list(set([os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")
    
    # --- ENHANCED KEYWORD RE-RANKER ---
    # Detect intent keywords for prioritization
    target_match = re.search(r'(Target|Group|B.Tech|Diploma|First Year|FY|Exclusively|Senior)', query, re.IGNORECASE)
    structure_match = re.search(r'(Floor|Structure|Room|Capacity|Occupancy|Seater|Ground)', query, re.IGNORECASE)
    fee_match = re.search(r'(Fee|Tuition|Mess|Payment|SBI|Contractor)', query, re.IGNORECASE)
    # Added 'Register' and 'Portal' to ensure registration links are prioritized
    calendar_match = re.search(r'(Calendar|Schedule|Date|Semester|Exam|ESE|MST|Classes|Start|End|Register|Portal|Website)', query, re.IGNORECASE)
    
    prioritized_docs = []
    other_docs = []
    
    for d in raw_docs:
        content = d.page_content.upper()
        source_name = os.path.basename(d.metadata.get('source', '')).upper()
        
        is_priority = False
        if target_match and any(word.upper() in content for word in ["TARGET", "B.TECH", "DIPLOMA", "EXCLUSIVELY"]):
            is_priority = True
        elif structure_match and any(word.upper() in content for word in ["FLOOR", "ROOM", "CAPACITY", "OCCUPANCY"]):
            is_priority = True
        elif calendar_match and ("CALENDAR" in source_name or "DATE" in content or "CLASSES" in content or "SEMESTER" in content or "REGISTER" in content or "PORTAL" in content):
            is_priority = True
        elif fee_match and ("FEES_" in source_name or "MESS" in content):
            is_priority = True
            
        if is_priority:
            prioritized_docs.append(d)
        else:
            other_docs.append(d)
    
    # Combine prioritized results first, taking the top 8 for context
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
        # Clean potential markdown or extra words from the AI
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
    print("Memory Protection Logic: Active.")
    print("Type 'exit' to quit.")
    print("="*50)
    
    system_instruction = """You are the VJTI Smart Campus Assistant.

ROUTING PRIORITY (CRITICAL):
- Use 'Campus_SQL_Data' (or simply 'SQL') for: Lists of programs, intake numbers, faculty locations, HOD names, and cutoffs.
- Use 'PDF_Knowledge_Base' (or simply 'PDF') for: Hostel structure, room counts, fees, policies, academic calendars, and important dates/schedules.
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
     * 'EWS' or 'Economically Weaker Section'  -> use LIKE '%EWS%'.
    - If user asks for 'all categories', DO NOT filter by category. Simply use: SELECT category, percentile FROM cutoffs WHERE branch LIKE '%keyword%' AND year = 2025;

5. 'programs' Table: Columns are [program_name, level, department, intake, duration_years].
    - For M.Tech, level = 'Postgraduate'.
    - For B.Tech, level = 'Undergraduate'.

6. 'faculty' Table: Columns are [name, department, designation, email, cabin_location].
    - ALWAYS use `LIKE '%HOD%'` for any query related to "HOD", "Head", or "Head of Department". NEVER use long-form strings.
    - HOD Search Example: WHERE designation LIKE '%HOD%' AND department LIKE '%Computer%'.

7. ELIGIBILITY & PERCENTILE LOGIC (NEW):
- When a user provides a percentile and asks "what can I get" or "what did I clear", you MUST query the 'cutoffs' table, NOT the 'programs' table.
- The 'cutoffs' table DOES have a 'branch' column. Example query: SELECT branch, percentile FROM cutoffs WHERE percentile <= 90.3 AND category LIKE '%EWS%' AND year = 2025;

DEMO QUESTION TEMPLATES:
- M.Tech Intakes: SELECT program_name, intake FROM programs WHERE level = 'Postgraduate' AND program_name LIKE 'M.Tech%';
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

FEE POLICY (CRITICAL):
- For any questions regarding tuition fees, development fees, or total annual amounts, DO NOT state any numerical figures or currency amounts.
- Inform the user that the fee structure is complex due to various categories (Open, Reserved, TFWS).
- Direct the user to cross-verify the details using the specific PDF file provided in your response.

TO USE A TOOL, respond ONLY with this JSON format:
{"tool": "Campus_SQL_Data", "query": "SELECT ..."}
"""
    # Initialize separate system message and chat history
    system_message = SystemMessage(content=system_instruction)
    chat_history = [] 

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit", "bye"]: break
            if not user_input.strip(): continue
                
            chat_history.append(HumanMessage(content=user_input))
            
            # SLIDING WINDOW: Combine System Instructions with ONLY the last 6 messages
            # This prevents the bot from fumbling early questions after a long session
            messages_to_send = [system_message] + chat_history[-6:]
            
            response = llm.invoke(messages_to_send)
            content = response.content.strip()
            
            json_match = re.search(r'\{.*"tool":\s*"(.*?)",\s*"query":\s*"(.*?)"\s*\}', content, re.DOTALL)
            
            if json_match:
                try:
                    tool_call_json = json.loads(json_match.group(0))
                    tool_name = tool_call_json.get("tool")
                    query_arg = tool_call_json.get("query")
                    
                    if tool_name in tools_map:
                        print(f"⚙️  Executing {tool_name}...")
                        result = tools_map[tool_name](query_arg)
                        
                        if tool_name in ["Campus_SQL_Data", "SQL"]:
                            final_task_note = "CRITICAL: Ensure your Markdown table includes the 'category' column. Note that 'branch' is a valid column in the 'cutoffs' table."
                        else:
                            # Context-Sensitive Task Note Selection
                            user_q_lower = user_input.lower()
                            if any(k in user_q_lower for k in ["hostel", "block", "room", "stay", "accommodation"]):
                                final_task_note = "STRICT BLOCK ISOLATION & NUMERICAL ACCURACY: Carefully identify the room count for EACH floor (Ground, 1st, 2nd) mentioned in the text for the requested block. Do not confuse 'students per room' with 'total rooms'."
                            elif any(k in user_q_lower for k in ["calendar", "date", "semester", "schedule", "start", "end", "mst", "ese", "register", "registration", "portal", "site", "website", "link"]):
                                final_task_note = "STRICT ACCURACY: Identify specific dates or URLs for the requested query. If asking about registration, you MUST look for and report the 'ERP Portal' link (https://erp.vjti.ac.in/) found in the text. Cite the [OFFICIAL SOURCE]."
                            elif any(k in user_q_lower for k in ["fee", "tuition", "pay", "charge"]):
                                final_task_note = "REMINDER: For fee queries, do not state numbers. Provide the official filename for cross-verification."
                            else:
                                final_task_note = "STRICT GROUNDING: Answer based solely on the provided tool output. If the answer is not in the text, say you don't have that info."

                        chat_history.append(AIMessage(content=content))
                        
                        # Add tool output to history for the next turn
                        tool_output_msg = HumanMessage(content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: Based ONLY on this data, answer: '{user_input}'. {final_task_note}")
                        chat_history.append(tool_output_msg)
                        
                        # Get final answer with the updated window
                        final_response = llm.invoke([system_message] + chat_history[-6:])
                        bot_text = final_response.content
                        
                        source_match = re.search(r'([A-Za-z0-9_-]+\.pdf)', bot_text)
                        attachment_msg = ""
                        if source_match:
                            filename = source_match.group(1)
                            full_path = os.path.join(DOCS_FOLDER, filename)
                            attachment_msg = f"\n\n📎 [Attachment Found: {filename}]\n> Location: {full_path}\n> (You can verify this document in your campus_documents folder)"
                        
                        print(f"\nBot: {bot_text}{attachment_msg}")
                        chat_history.append(final_response)
                    else:
                        print(f"\nBot: [Internal Error] Invalid tool selected.")
                except Exception as e:
                    print(f"\nBot: {content}")
            else:
                print(f"\nBot: {content}")
                chat_history.append(response)

            # Prune chat history to prevent memory leaks in extreme cases
            if len(chat_history) > 20:
                chat_history = chat_history[-10:]

        except Exception as e:
            print(f"\nBot: Error: {str(e)}")

if __name__ == "__main__":
    chat()