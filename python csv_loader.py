import pandas as pd
import sqlite3
import os
import json

# --- CONFIGURATION ---
DB_NAME = "campus.db"
UPLOAD_FOLDER = "./data_uploads"
CONFIG_FILE = "db_config.json"

def load_config():
    """Loads the unique keys for each table from a JSON file."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def run_pipeline():
    """
    Scans the upload folder for CSVs and syncs them to SQLite.
    If a table exists, it performs an 'UPSERT' based on config keys.
    """
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"📁 Created {UPLOAD_FOLDER}. Drop your CSVs there.")
        return

    config = load_config()
    conn = sqlite3.connect(DB_NAME)
    
    csv_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.csv')]
    
    if not csv_files:
        print("⚠️ No CSV files found in data_uploads folder.")
        return

    for file in csv_files:
        table_name = os.path.splitext(file)[0].lower()
        file_path = os.path.join(UPLOAD_FOLDER, file)
        
        print(f"🔄 Processing table: [{table_name}]...")
        
        # 1. Read CSV
        df = pd.read_csv(file_path)
        
        # 2. Get Unique Keys from config for Upsert logic
        # Default to all columns if no specific keys are defined
        unique_keys = config.get(table_name, list(df.columns))
        
        # 3. Dynamic SQL Construction for UPSERT
        # This handles 'Update if exists, Insert if new' automatically
        columns = ", ".join(df.columns)
        placeholders = ", ".join(["?"] * len(df.columns))
        updates = ", ".join([f"{col}=excluded.{col}" for col in df.columns if col not in unique_keys])
        
        # SQLite UPSERT Syntax (Requires SQLite 3.24+)
        if updates:
            conflict_clause = f"ON CONFLICT({', '.join(unique_keys)}) DO UPDATE SET {updates}"
        else:
            conflict_clause = f"ON CONFLICT({', '.join(unique_keys)}) DO NOTHING"

        sql_upsert = f"""
        INSERT INTO {table_name} ({columns}) 
        VALUES ({placeholders}) 
        {conflict_clause}
        """

        # 4. Execute to Database
        try:
            # First, ensure table exists (Pandas creates it if missing)
            # We use head(0) to just create the schema if it's new
            df.head(0).to_sql(table_name, conn, if_exists='append', index=False)
        except:
            pass # Table already exists

        # Perform the actual data sync
        cursor = conn.cursor()
        data_tuples = [tuple(x) for x in df.values]
        
        try:
            cursor.executemany(sql_upsert, data_tuples)
            conn.commit()
            print(f"✅ Successfully synced {len(df)} rows to {table_name}.")
        except Exception as e:
            print(f"❌ Error syncing {table_name}: {e}")

    conn.close()
    print("\n✨ Database pipeline execution complete.")

if __name__ == "__main__":
    run_pipeline()