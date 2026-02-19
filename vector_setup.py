import os
import shutil
from langchain_community.document_loaders import PyPDFDirectoryLoader, DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

# 1. SETUP
DOCS_PATH = "./campus_documents"
PERSIST_DIRECTORY = "./chroma_db"

def build_knowledge_base():
    """
    Scans the documents folder, cleans the old database, 
    and indexes both PDF and TXT files using local Hugging Face Embeddings.
    """
    # --- CRITICAL: CLEAN WIPE ---
    # Removes stale data to prevent incorrect/hallucinated answers from old versions
    if os.path.exists(PERSIST_DIRECTORY):
        print(f"🗑️  Removing old database at {PERSIST_DIRECTORY}...")
        shutil.rmtree(PERSIST_DIRECTORY)
    
    if not os.path.exists(DOCS_PATH):
        print(f"❌ Error: The folder '{DOCS_PATH}' does not exist.")
        return

    print(f"📂 Scanning folder: {DOCS_PATH}...")

    # 2. LOAD DOCUMENTS (PDF + TXT)
    pdf_loader = PyPDFDirectoryLoader(DOCS_PATH)
    pdf_docs = pdf_loader.load()
    
    txt_loader = DirectoryLoader(DOCS_PATH, glob="./*.txt", loader_cls=TextLoader)
    txt_docs = txt_loader.load()
    
    all_docs = pdf_docs + txt_docs
    
    if not all_docs:
        print("⚠️ No PDF or TXT files found in ./campus_documents.")
        return

    print(f"📄 Found {len(all_docs)} total document pages/files.")

    # 3. CHUNKING
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        add_start_index=True
    )
    chunks = text_splitter.split_documents(all_docs)
    print(f"✂️  Split into {len(chunks)} searchable chunks.")

    # 4. EMBEDDING & STORAGE (LOCAL)
    print("🔄 Generating Hugging Face Embeddings (Local) and indexing documents...")
    
    # This model runs locally and doesn't require an API Key
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    vector_db = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=PERSIST_DIRECTORY
    )
    
    # Ensure data is written to disk
    vector_db.persist()
    print(f"✅ Success! Vector database is now fresh in '{PERSIST_DIRECTORY}'")

if __name__ == "__main__":
    build_knowledge_base()