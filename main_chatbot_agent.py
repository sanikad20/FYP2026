import os
import sqlite3
import json
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage, AIMessage

# 1. CONFIGURATION
# No API Keys needed! We are running locally.
MODEL_NAME = "llama3" 

# 2. CONNECT TO DATABASES
db = SQLDatabase.from_uri("sqlite:///campus.db")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# 3. DEFINE THE TOOLS
def pdf_search(query):
    """Retrieves text from the PDFs in the folder."""
    print(f"   (Searching PDF for: {query})...")
    docs = vector_db.similarity_search(query, k=3)
    return "\n\n".join([d.page_content for d in docs])

def sql_query(query):
    """Runs a query against the SQL database."""
    print(f"   (Running SQL: {query})...")
    try:
        clean_query = query.replace("```sql", "").replace("```", "").strip()
        result = db.run(clean_query)
        return str(result) if result else "No matching records found."
    except Exception as e:
        return f"SQL Error: {str(e)}"

# 4. INITIALIZE OLLAMA (Local AI)
llm = ChatOllama(model=MODEL_NAME, temperature=0)

tools_map = {"PDF_Knowledge_Base": pdf_search, "Campus_SQL_Data": sql_query}

# 5. THE CHAT LOOP
def chat():
    print("\n" + "="*50)
    print(f"🤖 VJTI Bot (Local {MODEL_NAME}) is Online!")
    print("Zero cost. Unlimited queries.")
    print("Type 'exit' to quit.")
    print("="*50)
    
    # We use a Prompt-Based Tool Calling approach because bind_tools is not supported by ChatOllama yet
    system_instruction = """You are the VJTI Smart Campus Assistant.
You have access to two tools:
1. "PDF_Knowledge_Base": Useful for questions about FEES, HOSTEL RULES, CALENDARS, POLICIES, and ADMISSION DOCS. Input should be a search phrase.
2. "Campus_SQL_Data": Useful for specific FACTS like FACULTY names, CUTOFFS, INTAKE, and ROOM locations. Input should be a valid SQL query for SQLite. 
   - Database Tables: 
     - faculty (name, department, designation, email, cabin_location)
     - placements (year, company, branch, package_lpa)
     - locations (name, latitude, longitude, floor_info)
     - programs (program_name, intake, department)
     - cutoffs (year, branch, category, percentile)

To use a tool, you MUST respond with ONLY a JSON object in this exact format:
{"tool": "tool_name", "query": "your_query"}

If you do not need a tool, answer normally.
"""
    messages = [SystemMessage(content=system_instruction)]

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit", "bye"]: break
            if not user_input.strip(): continue
                
            messages.append(HumanMessage(content=user_input))
            
            # 1. Get AI Response
            response = llm.invoke(messages)
            content = response.content.strip()
            
            # 2. Check if AI returned a JSON tool call
            # We look for the start/end of a JSON block
            if "{" in content and "}" in content and '"tool":' in content:
                try:
                    # Extract JSON string even if there is extra text
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    json_str = content[start:end]
                    
                    tool_call = json.loads(json_str)
                    tool_name = tool_call.get("tool")
                    query_arg = tool_call.get("query")
                    
                    if tool_name in tools_map:
                        print(f"⚙️  Executing {tool_name}...")
                        
                        # Execute Tool
                        result = tools_map[tool_name](query_arg)
                        
                        # Append the interaction to history so Llama knows what happened
                        messages.append(AIMessage(content=json_str))
                        messages.append(HumanMessage(content=f"Tool Output: {result}\n\nBased on this output, provide the final answer to the user."))
                        
                        # 3. Get Final Answer
                        final_response = llm.invoke(messages)
                        print(f"\nBot: {final_response.content}")
                        messages.append(final_response)
                        
                    else:
                        print(f"\nBot: {content}") # Just print if tool name is wrong
                        messages.append(response)
                        
                except json.JSONDecodeError:
                    # If JSON parsing fails, just print the raw response
                    print(f"\nBot: {content}")
                    messages.append(response)
            
            else:
                # Normal response (no tool needed)
                print(f"\nBot: {content}")
                messages.append(response)

        except Exception as e:
            print(f"\nBot: Error: {str(e)}")

if __name__ == "__main__":
    chat()