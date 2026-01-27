import os
from langchain_community.document_loaders import PyPDFDirectoryLoader, DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
# Import Google Embeddings instead of OpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# 1. SETUP
# Your key is a Google key, so we set the GOOGLE_API_KEY environment variable
os.environ["GOOGLE_API_KEY"] = "AIzaSyCrqUH9Cz1D_4JzRdND9S9xlQE9zfT6QjU" 

DOCS_PATH = "./campus_documents"
PERSIST_DIRECTORY = "./chroma_db"

def create_vector_store():
    if not os.path.exists(DOCS_PATH):
        print(f"❌ Error: The folder '{DOCS_PATH}' does not exist.")
        return

    print(f"📂 Loading documents from {DOCS_PATH}...")

    # 2. LOAD DOCUMENTS
    pdf_loader = PyPDFDirectoryLoader(DOCS_PATH)
    pdf_docs = pdf_loader.load()
    
    txt_loader = DirectoryLoader(DOCS_PATH, glob="./*.txt", loader_cls=TextLoader)
    txt_docs = txt_loader.load()
    
    all_docs = pdf_docs + txt_docs
    
    if not all_docs:
        print("⚠️ No PDF or TXT files found.")
        return

    # 3. SPLIT TEXT
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, 
        chunk_overlap=100,
        add_start_index=True
    )
    chunks = text_splitter.split_documents(all_docs)
    
    print(f"✂️ Split documents into {len(chunks)} chunks.")

    # 4. CREATE & PERSIST VECTOR DB
    print("🔄 Generating Google Embeddings and updating Vector Database...")
    
    # Use GoogleGenerativeAIEmbeddings instead of OpenAI
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    vector_db = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=PERSIST_DIRECTORY
    )
    
    print(f"✅ Vector Database created successfully in '{PERSIST_DIRECTORY}'.")

if __name__ == "__main__":
    create_vector_store()