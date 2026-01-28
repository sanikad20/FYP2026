import os
import sqlite3
import json
import re
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage, AIMessage

# 1. CONFIGURATION
MODEL_NAME = "llama3" 

# 2. CONNECT TO DATABASES
db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# 3. DEFINE THE TOOLS
def pdf_search(query):
    """Retrieves text from PDFs with an enhanced keyword re-ranker for Blocks and PG-Hostel."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    # Fetch 12 chunks for better coverage of multi-floor descriptions
    raw_docs = vector_db.similarity_search(query, k=12)
    
    # --- ENHANCED SELECTOR LOGIC ---
    # Detect specific targets: Block [Letter] or PG Hostel/Postgraduate
    block_match = re.search(r'Block\s+([A-Z])', query, re.IGNORECASE)
    pg_match = re.search(r'(PG|Postgraduate)\s*Hostel', query, re.IGNORECASE)
    
    target_identifiers = []
    if block_match:
        target_identifiers.append(f"Block {block_match.group(1).upper()}")
    if pg_match:
        target_identifiers.extend(["PG-HOSTEL", "PG HOSTEL", "POSTGRADUATE HOSTEL"])
    
    prioritized_docs = []
    other_docs = []
    for d in raw_docs:
        content = d.page_content.upper()
        # Prioritize if any specific target identifier is found in the chunk
        if target_identifiers and any(tid.upper() in content for tid in target_identifiers):
            prioritized_docs.append(d)
        else:
            other_docs.append(d)
    
    # Re-assemble: Prioritized docs first, limit to top 6 chunks for the model
    final_docs = (prioritized_docs + other_docs)[:6]
    context_list = []
    for d in final_docs:
        source = os.path.basename(d.metadata.get('source', 'Unknown File'))
        context_list.append(f"[Source: {source}]\n{d.page_content}")
    
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

# Add aliases to tools_map to handle Llama 3's tendency to simplify tool names
tools_map = {
    "PDF_Knowledge_Base": pdf_search,
    "Campus_SQL_Data": sql_query,
    "SQL": sql_query,        # Alias for resilience
    "PDF": pdf_search        # Alias for resilience
}

# 5. THE CHAT LOOP
def chat():
    print("\n" + "="*50)
    print(f"🤖 VJTI Bot (Local {MODEL_NAME}) is Online!")
    print("Demo-Ready Mode Enabled (Fixed Cutoffs & Hostels).")
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
   - Computer HOD search: WHERE designation LIKE '%HOD%' AND department LIKE '%Computer%'.

DEMO QUESTION TEMPLATES:
- M.Tech Intakes: SELECT program_name, intake FROM programs WHERE level = 'Postgraduate' AND program_name LIKE 'M.Tech%';
- Cutoff Comparison: SELECT year, percentile FROM cutoffs WHERE branch = 'Computer Engineering' AND category = 'GOPENS' AND (year=2024 OR year=2025);
- B.Tech Intake: SELECT intake FROM programs WHERE program_name = 'B.Tech Computer Engineering';

PDF RULES (STRICT GROUNDING):
- You MUST answer ONLY based on the provided TOOL OUTPUT.
- Do NOT use internal knowledge for hostel room counts or floor structures.
- If data for a specific building is found in the TOOL OUTPUT, report it exactly.
- If data is missing from the TOOL OUTPUT, say 'I don't have that specific info'. DO NOT hallucinate numbers.

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
            
            # Use RegEx to find JSON anywhere in the response
            json_match = re.search(r'\{.*"tool":\s*"(.*?)",\s*"query":\s*"(.*?)"\s*\}', content, re.DOTALL)
            
            if json_match:
                try:
                    tool_call_json = json.loads(json_match.group(0))
                    tool_name = tool_call_json.get("tool")
                    query_arg = tool_call_json.get("query")
                    
                    if tool_name in tools_map:
                        print(f"⚙️  Executing {tool_name}...")
                        result = tools_map[tool_name](query_arg)
                        
                        # Determine follow-up instruction based on the tool used
                        if tool_name in ["Campus_SQL_Data", "SQL"]:
                            final_task_note = "For cutoffs/intakes, use a clear Markdown table."
                        else:
                            final_task_note = "For Hostels, report the floor-by-floor room counts exactly as written in the text. Cite the source."

                        messages.append(AIMessage(content=content))
                        messages.append(HumanMessage(content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: Using ONLY this data, answer the original user query: '{user_input}'. {final_task_note}"))
                        
                        final_response = llm.invoke(messages)
                        print(f"\nBot: {final_response.content}")
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