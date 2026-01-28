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
    """Retrieves text from PDFs with a manual keyword re-ranker."""
    print(f"   🔍 Searching PDF Database for: '{query}'...")
    raw_docs = vector_db.similarity_search(query, k=10)
    
    match = re.search(r'Block\s+([A-Z])', query, re.IGNORECASE)
    target_identifier = f"Block {match.group(1).upper()}" if match else None
    
    prioritized_docs = []
    other_docs = []
    for d in raw_docs:
        content = d.page_content.upper()
        if target_identifier and target_identifier.upper() in content:
            prioritized_docs.append(d)
        else:
            other_docs.append(d)
    
    final_docs = (prioritized_docs + other_docs)[:5]
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
    print("Resilient SQL/PDF Routing Logic Enabled.")
    print("Type 'exit' to quit.")
    print("="*50)
    
    system_instruction = """You are the VJTI Smart Campus Assistant.

ROUTING PRIORITY (CRITICAL):
- Use 'Campus_SQL_Data' (or simply 'SQL') for: ANY lists of programs, student intake numbers, faculty locations, HOD names, and cutoffs.
- Use 'PDF_Knowledge_Base' (or simply 'PDF') for: Fees, hostel rules, calendars, and academic policies.
- If a question asks for "How many", "List all", or "Compare", it is ALWAYS a SQL query.

SQL RULES:
- You MUST write a VALID SQLite query.
- Table 'programs' values for column 'level' are strictly: 'Undergraduate' (for B.Tech), 'Postgraduate' (for M.Tech/MCA), and 'Diploma'. 
- NEVER use 'B.Tech' or 'M.Tech' as values in the 'level' column; use 'Undergraduate' or 'Postgraduate' instead.
- Table 'programs' has: program_name, level, department, intake, duration_years.
- To find B.Tech Intake: SELECT intake FROM programs WHERE level = 'Undergraduate' AND program_name LIKE '%Computer%';
- To find M.Tech: SELECT program_name, intake FROM programs WHERE level = 'Postgraduate' AND program_name LIKE 'M.Tech%';
- Table 'cutoffs' has: year, branch, category, percentile.
- Table 'faculty' has: name, department, designation, email, cabin_location.

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
                        
                        messages.append(AIMessage(content=content))
                        messages.append(HumanMessage(content=f"TOOL OUTPUT:\n{result}\n\nFINAL TASK: Based ONLY on this data, provide the final answer. Use a table for lists/intakes."))
                        
                        final_response = llm.invoke(messages)
                        print(f"\nBot: {final_response.content}")
                        messages.append(final_response)
                    else:
                        print(f"\nBot: [Internal Error] Invalid tool: {tool_name}")
                        print(f"   (Hint: The model used '{tool_name}' which is not in {list(tools_map.keys())})")
                except Exception as e:
                    print(f"\nBot: {content}")
            else:
                print(f"\nBot: {content}")
                messages.append(response)

        except Exception as e:
            print(f"\nBot: Error: {str(e)}")

if __name__ == "__main__":
    chat()