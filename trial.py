import os
import sqlite3
import json
import re
import webbrowser
import tiktoken
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# 1. CONFIGURATION
MODEL_NAME = "llama3" 
DOCS_FOLDER = "./campus_documents"
MAX_TOKENS = 7000  # Leave 1000 tokens for response generation
TOKEN_BUFFER = 1000  # Safety buffer

# 2. CONNECT TO DATABASES
db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# 3. TOKEN COUNTER FUNCTION
def count_tokens(text, model="llama3"):
    """Count tokens in text - using tiktoken as approximation for Llama"""
    try:
        enc = tiktoken.get_encoding("cl100k_base")  # Good approximation for many models
        return len(enc.encode(text))
    except:
        # Fallback: rough estimate (4 chars per token)
        return len(text) // 4

def count_messages_tokens(messages):
    """Count total tokens in a list of messages"""
    total = 0
    for msg in messages:
        total += count_tokens(msg.content)
    return total

def trim_chat_history(system_msg, chat_history, max_tokens=MAX_TOKENS):
    """Trim chat history based on token count, keeping most recent messages"""
    messages = [system_msg] + chat_history
    total_tokens = count_messages_tokens(messages)
    
    # If within limits, return original history
    if total_tokens <= max_tokens:
        return chat_history
    
    # Remove oldest messages until under limit
    trimmed_history = chat_history.copy()
    while total_tokens > max_tokens and len(trimmed_history) > 2:  # Keep at least 2 most recent
        removed = trimmed_history.pop(0)
        total_tokens -= count_tokens(removed.content)
        # Also remove the corresponding message pair if it was a tool output
        if len(trimmed_history) > 0 and isinstance(removed, HumanMessage) and "TOOL OUTPUT:" in removed.content:
            # This was a tool output message, we already removed it
            pass
    
    print(f"   📊 Trimmed history from {len(chat_history)} to {len(trimmed_history)} messages ({total_tokens}/{max_tokens} tokens)")
    return trimmed_history

# 4. DEFINE THE TOOLS (OPTIMIZED FOR TOKEN USAGE)
def pdf_search(query):
    """Retrieves text from PDFs with enhanced re-ranker and token optimization."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    
    # REDUCED: k=8 instead of 15 to save tokens
    raw_docs = vector_db.similarity_search(query, k=8)
    
    # --- DEBUG: SHOW RETRIEVED SOURCES ---
    retrieved_sources = list(set([os.path.basename(d.metadata.get('source', 'Unknown')) for d in raw_docs]))
    print(f"   📂 Retrieved Chunks from: {retrieved_sources}")
    
    # --- ENHANCED KEYWORD RE-RANKER ---
    target_k = ["TARGET", "B.TECH", "DIPLOMA", "FIRST YEAR", "FY", "EXCLUSIVELY", "SENIOR", "SY", "PG"]
    structure_k = ["FLOOR", "STRUCTURE", "ROOM", "CAPACITY", "OCCUPANCY", "SEATER", "GROUND"]
    fee_k = ["FEE", "TUITION", "MESS", "PAYMENT", "SBI", "CONTRACTOR", "REFUND", "TFWS"]
    cal_k = ["CALENDAR", "SCHEDULE", "DATE", "SEMESTER", "EXAM", "ESE", "MST", "CLASSES", "START", "END", "REGISTER", "REGISTRATION", "PORTAL", "WEBSITE", "FEST", "TECHNOVANZA", "PRATIBIMB", "HOLIDAY", "BREAK"]
    
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
    
    # REDUCED: Take top 5 prioritized chunks instead of 10
    final_docs = (prioritized_docs + other_docs)[:5]
    
    # TRUNCATE: Limit each chunk to ~200 words to save tokens
    context_list = []
    for d in final_docs:
        source = os.path.basename(d.metadata.get('source', 'Unknown File'))
        
        # Truncate long chunks
        content = d.page_content
        words = content.split()
        if len(words) > 250:  # ~250 words = ~300-350 tokens
            content = ' '.join(words[:250]) + '... [truncated]'
        
        context_list.append(f"[OFFICIAL SOURCE: {source}]\n{content}")
    
    return "\n\n---\n\n".join(context_list)


def sql_query(query):
    """Runs a query against the SQL database with result truncation."""
    print(f"   🗄️  Running SQL Query: {query}...")
    try:
        clean_query = query.replace("```sql", "").replace("```", "").strip()
        result = db.run(clean_query)
        
        # Truncate large results
        if result and len(str(result)) > 1000:
            result_str = str(result)
            # Try to parse as list/dict and truncate
            if result_str.startswith('[') or result_str.startswith('{'):
                truncated = result_str[:800] + f'... [truncated: total length {len(result_str)} chars]'
                return truncated
            else:
                return result_str[:800] + '... [truncated]'
        
        return str(result) if result else "No matching records found in SQL."
    except Exception as e:
        return f"SQL Error: {str(e)}"

# 5. INITIALIZE OLLAMA
llm = ChatOllama(model=MODEL_NAME, temperature=0)

tools_map = {
    "PDF_Knowledge_Base": pdf_search,
    "Campus_SQL_Data": sql_query,
    "SQL": sql_query,
    "PDF": pdf_search
}

# 6. SYSTEM PROMPT (OPTIMIZED - removed redundant examples to save tokens)
system_instruction = """You are the VJTI Smart Campus Assistant.

ROUTING PRIORITY (CRITICAL):
- Use 'Campus_SQL_Data' (or simply 'SQL') for: Lists of programs, intake numbers, faculty locations, HOD names, and cutoffs.
- Use 'PDF_Knowledge_Base' (or simply 'PDF') for: Hostel structure, room counts, fees, policies, academic calendars, important dates/schedules, Hostel details, Fees, Admission Stages (CAP), Seat Acceptance (Freeze/Float/Betterment), Anti-Ragging procedures, and Attendance Rules..
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
- MAJOR EVENTS: Technovanza is held in December/January. Pratibimb is held in February.
- ANTI-RAGGING: Step 1: Informal (Warden/Faculty). Step 2: Formal Written (Box/Dr. Gangopadhyay). Step 3: Online (UGC portal). Step 4: Committee Enquiry.

FEE POLICY (CRITICAL):
- For any questions regarding tuition fees, development fees, or total annual amounts, DO NOT state any numerical figures or currency amounts.
- Inform the user that the fee structure is complex due to various categories (Open, Reserved, TFWS).
- Direct the user to cross-verify the details using the specific PDF file provided in your response.

TO USE A TOOL, respond ONLY with this JSON format:
{"tool": "Campus_SQL_Data", "query": "SELECT ..."}
"""

# 7. THE CHAT LOOP
def chat():
    print("\n" + "="*50)
    print(f"🤖 VJTI Bot (Local {MODEL_NAME}) is Online!")
    print(f"Token Management: Active (Max {MAX_TOKENS} tokens)")
    print("Commands: !reset - Clear memory, !stats - Show token usage")
    print("="*50)
    
    system_message = SystemMessage(content=system_instruction)
    chat_history = []
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit", "bye"]: 
                break
            if user_input.lower() == "!reset":
                chat_history = []
                print("Bot: Memory cleared.")
                continue
            if user_input.lower() == "!stats":
                total = count_messages_tokens([system_message] + chat_history)
                print(f"📊 Current token usage: {total}/{MAX_TOKENS} (System + History)")
                print(f"   Messages in history: {len(chat_history)}")
                continue
            if not user_input.strip(): 
                continue
            
            chat_history.append(HumanMessage(content=user_input))
            
            # Trim history based on tokens BEFORE sending
            chat_history = trim_chat_history(system_message, chat_history)
            
            # Prepare messages for LLM
            messages_to_send = [system_message] + chat_history[-6:]  # Keep last 6 messages after trimming
            
            # Debug token count
            token_count = count_messages_tokens(messages_to_send)
            print(f"   📊 Sending {token_count} tokens to LLM")
            
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
                        
                        # Context-sensitive task note (shortened to save tokens)
                        u_q_l = user_input.lower()
                        if any(k in u_q_l for k in ["hostel", "block", "room", "stay"]):
                            final_task_note = "Use ONLY room counts from text. Cite source."
                        elif "technovanza" in u_q_l or "pratibimb" in u_q_l:
                            final_task_note = "Only use dates from text. If not there, say unknown."
                        elif any(k in u_q_l for k in ["calendar", "date", "semester", "register", "portal"]):
                            final_task_note = f"Use ONLY dates from output. Cite source & https://erp.vjti.ac.in/"
                        else:
                            final_task_note = "Answer based ONLY on tool output."

                        # Store the tool call
                        chat_history.append(AIMessage(content=content))
                        
                        # Create tool output message (truncated if too long)
                        tool_output = f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: {final_task_note}"
                        if count_tokens(tool_output) > 1500:
                            # Aggressively truncate if still too long
                            tool_output = f"TOOL OUTPUT:\n{result[:1000]}...\n\nFINAL TASK: {final_task_note}"
                        
                        tool_output_msg = HumanMessage(content=tool_output)
                        chat_history.append(tool_output_msg)
                        
                        # Trim again before final response
                        chat_history = trim_chat_history(system_message, chat_history)
                        
                        # Get final response
                        final_response = llm.invoke([system_message] + chat_history[-4:])  # Use fewer messages for final
                        bot_text = final_response.content
                        
                        # Extract source for attachment
                        source_match = re.search(r'([A-Za-z0-9_-]+\.pdf)', bot_text)
                        attachment_msg = ""
                        if source_match:
                            filename = source_match.group(1)
                            full_path = os.path.join(DOCS_FOLDER, filename)
                            if os.path.exists(full_path):
                                attachment_msg = f"\n\n📎 [Attachment: {filename}]"
                        
                        print(f"\nBot: {bot_text}{attachment_msg}")
                        chat_history.append(final_response)
                    else:
                        print(f"\nBot: [Error] Invalid tool: {tool_name}")
                except Exception as e:
                    print(f"\nBot: Error processing tool: {str(e)}")
                    print(f"Raw response: {content}")
            else:
                print(f"\nBot: {content}")
                chat_history.append(response)
            
            # Final safety trim - keep history under control
            if len(chat_history) > 20:
                # Keep more recent messages but ensure token count is managed
                chat_history = chat_history[-15:]
                # Force a token-based trim
                chat_history = trim_chat_history(system_message, chat_history, MAX_TOKENS - TOKEN_BUFFER)

        except KeyboardInterrupt:
            print("\nBot: Goodbye!")
            break
        except Exception as e:
            print(f"\nBot: Unexpected error: {str(e)}")
            # Don't break the loop on error
            continue

if __name__ == "__main__":
    chat()