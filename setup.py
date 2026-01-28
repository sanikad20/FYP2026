import sqlite3
import pandas as pd
import os

# 1. Name of your database file
DB_NAME = "campus.db"

def create_database():
    """Creates the tables for the Smart Campus Chatbot."""
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    print(f"🔌 Connected to {DB_NAME}")

    # RESET: Drop tables if they exist to prevent duplicates
    cursor.execute('DROP TABLE IF EXISTS faculty')
    cursor.execute('DROP TABLE IF EXISTS placements')
    cursor.execute('DROP TABLE IF EXISTS locations')
    cursor.execute('DROP TABLE IF EXISTS programs')
    cursor.execute('DROP TABLE IF EXISTS cutoffs')
    print("🗑️  Previous data cleared.")

    # ---------------------------------------------------------
    # TABLE 1: FACULTY & DEPARTMENTS
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS faculty (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department TEXT,
        designation TEXT,
        email TEXT
    )
    ''')

    # ---------------------------------------------------------
    # TABLE 2: PLACEMENTS
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS placements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER,
        company TEXT,
        branch TEXT,
        package_lpa REAL,
        students_placed INTEGER
    )
    ''')

    # ---------------------------------------------------------
    # TABLE 3: LOCATIONS (For Maps)
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,             
        aliases TEXT,          
        category TEXT,         
        latitude REAL,         
        longitude REAL,
        parent_building TEXT,  -- NULL for buildings, Name of bldg for rooms
        floor_info TEXT,       
        image_url TEXT         
    )
    ''')

    # ---------------------------------------------------------
    # TABLE 4: ACADEMIC PROGRAMS
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS programs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_name TEXT,
        level TEXT,
        department TEXT,
        intake INTEGER,
        duration_years INTEGER
    )
    ''')

    # ---------------------------------------------------------
    # TABLE 5: ADMISSION CUTOFFS
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cutoffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER,
        branch TEXT,
        category TEXT,
        percentile REAL
    )
    ''')

    print("✅ Tables created successfully.")
    
    # =========================================================
    # INSERTING DATA
    # =========================================================

    # --- 1. Program Data ---
    programs_data = [
        # Undergraduate (B.Tech) - 4 Years
        ('B.Tech Civil Engineering', 'Undergraduate', 'Civil', 60, 4),
        ('B.Tech Computer Engineering', 'Undergraduate', 'Computer', 60, 4),
        ('B.Tech Information Technology', 'Undergraduate', 'IT', 60, 4),
        ('B.Tech Electrical Engineering', 'Undergraduate', 'Electrical', 60, 4),
        ('B.Tech Electronics Engineering', 'Undergraduate', 'Electrical', 60, 4),
        ('B.Tech Electronics & Telecom', 'Undergraduate', 'Electrical', 60, 4),
        ('B.Tech Mechanical Engineering', 'Undergraduate', 'Mechanical', 60, 4),
        ('B.Tech Production Engineering', 'Undergraduate', 'Production', 60, 4),
        ('B.Tech Textile Technology', 'Undergraduate', 'Textile', 60, 4),

        # Post Graduate (M.Tech) - 2 Years
        ('M.Tech Structural Engineering', 'Postgraduate', 'Civil', 25, 2),
        ('M.Tech Construction Management', 'Postgraduate', 'Civil', 18, 2),
        ('M.Tech Environmental Engineering', 'Postgraduate', 'Civil', 18, 2),
        ('M.Tech Computer Engineering', 'Postgraduate', 'Computer', 18, 2),
        ('M.Tech Software Engineering', 'Postgraduate', 'Computer', 18, 2),
        ('M.Tech Network Infrastructure', 'Postgraduate', 'IT', 18, 2),
        ('M.Tech Power Systems', 'Postgraduate', 'Electrical', 18, 2),
        ('M.Tech Control Systems', 'Postgraduate', 'Electrical', 18, 2),
        ('M.Tech Electronics', 'Postgraduate', 'Electrical', 18, 2),
        ('M.Tech EXTC', 'Postgraduate', 'Electrical', 18, 2),
        ('M.Tech Machine Design', 'Postgraduate', 'Mechanical', 18, 2),
        ('M.Tech Automobile Engineering', 'Postgraduate', 'Mechanical', 18, 2),
        ('M.Tech CAD/CAM', 'Postgraduate', 'Production', 18, 2),
        ('M.Tech Textile Technology', 'Postgraduate', 'Textile', 18, 2),

        # Diploma - 3 Years
        ('Diploma in Civil Engineering', 'Diploma', 'Civil', 60, 3),
        ('Diploma in Mechanical Engineering', 'Diploma', 'Mechanical', 60, 3),
        ('Diploma in Electrical Engineering', 'Diploma', 'Electrical', 60, 3),
        ('Diploma in Industrial Electronics', 'Diploma', 'Electrical', 60, 3),
        ('Diploma in Textile Manufactures', 'Diploma', 'Textile', 60, 3),
        ('Diploma in Chemical Engineering', 'Diploma', 'Chemical', 60, 3),

        # MCA - 2 Years
        ('Master in Computer Applications (MCA)', 'Postgraduate', 'MCA', 60, 2)
    ]
    cursor.executemany('INSERT INTO programs (program_name, level, department, intake, duration_years) VALUES (?, ?, ?, ?, ?)', programs_data)

    # --- 2. Cutoff Data (2025 Admissions) ---
    # Format: (Year, Branch, Category, Lowest_Percentile)
    cutoffs_data = [
        # --- GOPENS (General Open) ---
        (2025, 'Computer Engineering', 'GOPENS', 99.95),
        (2025, 'Information Technology', 'GOPENS', 99.76),
        (2025, 'Electronics & Telecom', 'GOPENS', 99.59),
        (2025, 'Electronics Engineering', 'GOPENS', 99.54),
        (2025, 'Electrical Engineering', 'GOPENS', 99.40),
        (2025, 'Mechanical Engineering', 'GOPENS', 99.26),
        (2025, 'Production Engineering', 'GOPENS', 98.28),
        (2025, 'Civil Engineering', 'GOPENS', 98.47),
        (2025, 'Textile Technology', 'GOPENS', 97.15),

        # --- GOBCS (General OBC) ---
        (2025, 'Computer Engineering', 'GOBCS', 99.71),
        (2025, 'Information Technology', 'GOBCS', 99.71),
        (2025, 'Electronics & Telecom', 'GOBCS', 99.52),
        (2025, 'Electronics Engineering', 'GOBCS', 99.42),
        (2025, 'Electrical Engineering', 'GOBCS', 99.06),
        (2025, 'Mechanical Engineering', 'GOBCS', 98.93),
        (2025, 'Production Engineering', 'GOBCS', 98.02),
        (2025, 'Civil Engineering', 'GOBCS', 98.19),
        (2025, 'Textile Technology', 'GOBCS', 95.73),

        # --- EWS (Economically Weaker Section) ---
        (2025, 'Computer Engineering', 'EWS', 99.69),
        (2025, 'Information Technology', 'EWS', 99.50),
        (2025, 'Electronics & Telecom', 'EWS', 99.25),
        (2025, 'Electronics Engineering', 'EWS', 98.94),
        (2025, 'Electrical Engineering', 'EWS', 98.48),
        (2025, 'Mechanical Engineering', 'EWS', 98.41),
        (2025, 'Production Engineering', 'EWS', 96.07),
        (2025, 'Civil Engineering', 'EWS', 95.57),
        (2025, 'Textile Technology', 'EWS', 92.71),

        # --- GSCS (Scheduled Castes) ---
        (2025, 'Computer Engineering', 'GSCS', 98.72),
        (2025, 'Information Technology', 'GSCS', 98.60),
        (2025, 'Electronics & Telecom', 'GSCS', 97.56),
        (2025, 'Electronics Engineering', 'GSCS', 97.10),
        (2025, 'Electrical Engineering', 'GSCS', 96.40),
        (2025, 'Mechanical Engineering', 'GSCS', 96.22),
        (2025, 'Production Engineering', 'GSCS', 94.11),
        (2025, 'Civil Engineering', 'GSCS', 94.89),
        (2025, 'Textile Technology', 'GSCS', 92.12),

        # --- GSTS (Scheduled Tribes) ---
        (2025, 'Computer Engineering', 'GSTS', 94.91),
        (2025, 'Information Technology', 'GSTS', 96.09),
        (2025, 'Electronics & Telecom', 'GSTS', 91.70),
        (2025, 'Electronics Engineering', 'GSTS', 90.72),
        (2025, 'Electrical Engineering', 'GSTS', 86.72),
        (2025, 'Mechanical Engineering', 'GSTS', 84.87),
        (2025, 'Production Engineering', 'GSTS', 83.72),
        (2025, 'Civil Engineering', 'GSTS', 87.68),
        (2025, 'Textile Technology', 'GSTS', 71.56),
        
        # --- LOPENS (Ladies Open) ---
        (2025, 'Computer Engineering', 'LOPENS', 99.85),
        (2025, 'Information Technology', 'LOPENS', 99.78),
        (2025, 'Electronics & Telecom', 'LOPENS', 99.65),
        (2025, 'Electrical Engineering', 'LOPENS', 99.23),
        (2025, 'Mechanical Engineering', 'LOPENS', 99.18),
        (2025, 'Civil Engineering', 'LOPENS', 98.05),
        (2025, 'Textile Technology', 'LOPENS', 96.64),

        # ==========================================
        # 2024 Cutoff Data (From VJTI 2023-24 PDF)
        # ==========================================
        
        # --- GOPENS 2024 ---
        (2024, 'Civil Engineering', 'GOPENS', 98.99),
        (2024, 'Computer Engineering', 'GOPENS', 99.89),
        (2024, 'Information Technology', 'GOPENS', 99.84),
        (2024, 'Electrical Engineering', 'GOPENS', 99.11),
        (2024, 'Electronics & Telecom', 'GOPENS', 99.59),
        (2024, 'Electronics Engineering', 'GOPENS', 99.43),
        (2024, 'Mechanical Engineering', 'GOPENS', 99.04),
        (2024, 'Production Engineering', 'GOPENS', 97.66),
        (2024, 'Textile Technology', 'GOPENS', 95.50),

        # --- GOBCS 2024 ---
        (2024, 'Civil Engineering', 'GOBCS', 96.06),
        (2024, 'Computer Engineering', 'GOBCS', 99.76),
        (2024, 'Information Technology', 'GOBCS', 99.74),
        (2024, 'Electrical Engineering', 'GOBCS', 98.93),
        (2024, 'Electronics & Telecom', 'GOBCS', 99.48),
        (2024, 'Electronics Engineering', 'GOBCS', 99.16),
        (2024, 'Mechanical Engineering', 'GOBCS', 98.47),
        (2024, 'Production Engineering', 'GOBCS', 97.32),
        (2024, 'Textile Technology', 'GOBCS', 92.49),

        # --- GSCS 2024 ---
        (2024, 'Civil Engineering', 'GSCS', 94.38),
        (2024, 'Computer Engineering', 'GSCS', 99.06),
        (2024, 'Information Technology', 'GSCS', 98.64),
        (2024, 'Electrical Engineering', 'GSCS', 95.65),
        (2024, 'Electronics & Telecom', 'GSCS', 97.51),
        (2024, 'Electronics Engineering', 'GSCS', 96.20),
        (2024, 'Mechanical Engineering', 'GSCS', 95.40),
        (2024, 'Production Engineering', 'GSCS', 91.71),
        (2024, 'Textile Technology', 'GSCS', 85.61),

        # --- GSTS 2024 ---
        (2024, 'Civil Engineering', 'GSTS', 76.83),
        (2024, 'Computer Engineering', 'GSTS', 95.49),
        (2024, 'Information Technology', 'GSTS', 95.07),
        (2024, 'Electrical Engineering', 'GSTS', 88.51),
        (2024, 'Electronics & Telecom', 'GSTS', 89.35),
        (2024, 'Electronics Engineering', 'GSTS', 81.03),
        (2024, 'Mechanical Engineering', 'GSTS', 66.67),
        (2024, 'Production Engineering', 'GSTS', 22.88),
        (2024, 'Textile Technology', 'GSTS', 45.84),

        # --- EWS 2024 ---
        (2024, 'Civil Engineering', 'EWS', 96.54),
        (2024, 'Computer Engineering', 'EWS', 99.72),
        (2024, 'Information Technology', 'EWS', 99.66),
        (2024, 'Electrical Engineering', 'EWS', 98.19),
        (2024, 'Electronics & Telecom', 'EWS', 99.30),
        (2024, 'Electronics Engineering', 'EWS', 98.85),
        (2024, 'Mechanical Engineering', 'EWS', 98.08),
        (2024, 'Production Engineering', 'EWS', 96.12),
        (2024, 'Textile Technology', 'EWS', 94.16),

        # --- LOPENS 2024 ---
        (2024, 'Civil Engineering', 'LOPENS', 96.73),
        (2024, 'Computer Engineering', 'LOPENS', 99.83),
        (2024, 'Information Technology', 'LOPENS', 99.71),
        (2024, 'Electrical Engineering', 'LOPENS', 99.03),
        (2024, 'Electronics & Telecom', 'LOPENS', 99.46),
        (2024, 'Electronics Engineering', 'LOPENS', 99.14),
        (2024, 'Mechanical Engineering', 'LOPENS', 98.07),
        (2024, 'Production Engineering', 'LOPENS', 98.07),
        (2024, 'Textile Technology', 'LOPENS', 90.86)
    ]
    cursor.executemany('INSERT INTO cutoffs (year, branch, category, percentile) VALUES (?, ?, ?, ?)', cutoffs_data)

    # --- 3. Faculty Data ---
    faculty_data = [
    # Institute Administration & Deans
    ('Dr. Sachin D. Kore', 'Administration', 'Director', 'director@vjti.ac.in'),
    ('Dr. R.N. Awale', 'Administration', 'Deputy Director / Dean R&D', 'dydirector@vjti.ac.in'),
    ('Dr. K.K. Sangle', 'Academics', 'Dean Academic Programmes', 'dean_ap@vjti.ac.in'),
    ('Dr. S.P. Borkar', 'Administration', 'Dean Administration', 'dean_admin@vjti.ac.in'),
    ('Dr. A.N. Bambole', 'Infrastructure', 'Dean Infrastructure & Chief Rector', 'dean_infra@vjti.ac.in'),

    # Civil & Environmental Engineering
    ('Dr. A.S. Wayal', 'Civil & Environmental Engineering', 'Associate Professor & HOD', 'hod_degree@ci.vjti.ac.in'),
    ('Dr. S.Y. Mhaske', 'Civil & Environmental Engineering', 'Associate Professor', 'N/A'),
    ('Prof. P.S. Chaudhari', 'Civil & Environmental Engineering', 'Assistant Professor', 'N/A'),
    ('Dr. V.B. Varekar', 'Civil & Environmental Engineering', 'Assistant Professor', 'N/A'),
    ('Dr. Annie Joy', 'Civil & Environmental Engineering', 'Assistant Professor (Tenure)', 'N/A'),

    # Computer Engineering & IT
    ('Dr. V.B. Nikam', 'Computer & IT', 'Associate Professor & HOD', 'hod_degree@ce.vjti.ac.in'),
    ('Prof. P.M. Chawan', 'Computer Engineering', 'Associate Professor', 'N/A'),
    ('Dr. M.R. Shirole', 'Information Technology', 'Associate Professor', 'N/A'),
    ('Dr. M.M. Chandane', 'Information Technology', 'Associate Professor', 'N/A'),
    ('Dr. V.K. Sambhe', 'Information Technology', 'Assistant Professor', 'N/A'),
    ('Dr. S.S. Udmale', 'Information Technology', 'Assistant Professor', 'N/A'),
    ('Dr. S.D. Kale', 'Computer Engineering', 'Assistant Professor', 'N/A'),

    # Electrical & Electronics Engineering
    ('Dr. R.A. Patil', 'Electrical Engineering', 'HOD', 'hod_degree@ee.vjti.ac.in'),
    ('Dr. S.K. Bhil', 'Electrical Engineering (Diploma)', 'HOD', 'skbhil@ee.vjti.ac.in'),
    ('Dr. Yogesh Wankhede', 'Electronics Engineering (Diploma)', 'HOD', 'yewankhede@el.vjti.ac.in'),
    ('Prof. H.B. Chaudhari', 'Electrical Engineering', 'Associate Professor', 'hbchoudhari@ee.vjti.ac.in'),
    ('Dr. S.R. Wagh', 'Electrical Engineering', 'Assistant Professor', 'srwagh@ee.vjti.ac.in'),
    ('Dr. Pragati Gupta', 'Electrical Engineering', 'Assistant Professor', 'ppgupta@ee.vjti.ac.in'),
    ('Dr. Ayush Saxena', 'Electrical Engineering', 'Assistant Professor', 'asaxena@ee.vjti.ac.in'),

    # Mechanical Engineering
    ('Dr. Sachin S. Naik', 'Mechanical Engineering', 'Associate Professor & HOD', 'ssnaik@me.vjti.ac.in'),
    ('Dr. W.S. Rathod', 'Mechanical Engineering', 'Associate Professor', 'wsrathod@me.vjti.ac.in'),
    ('Dr. N.P. Gulhane', 'Mechanical Engineering', 'Associate Professor', 'npgulhane@me.vjti.ac.in'),
    ('Dr. A.V. Deshpande', 'Mechanical Engineering', 'Associate Professor', 'avdeshpande@me.vjti.ac.in'),
    ('Dr. A.S. Rao', 'Mechanical Engineering', 'Assistant Professor', 'asrao@me.vjti.ac.in'),

    # Production Engineering
    ('Dr. D.N. Raut', 'Production Engineering', 'Professor & HOD', 'dnraut@pe.vjti.ac.in'),
    ('Dr. D.K. Shinde', 'Production Engineering', 'Associate Professor', 'dkshinde@pe.vjti.ac.in'),
    ('Dr. M.R. Nagare', 'Production Engineering', 'Associate Professor', 'mrnagare@pe.vjti.ac.in'),
    ('Dr. Srinath E. Gudur', 'Production Engineering', 'Assistant Professor', 'segudur@pe.vjti.ac.in'),

    # Structural Engineering
    ('Dr. V.B. Deshmukh', 'Structural Engineering', 'Associate Professor & HOD', 'vbdeshmukh@st.vjti.ac.in'),
    ('Dr. K.K. Sangle', 'Structural Engineering', 'Professor', 'kksangle@st.vjti.ac.in'),
    ('Dr. A.N. Bambole', 'Structural Engineering', 'Professor', 'anbambole@st.vjti.ac.in'),
    ('Dr. S.S. Pendhari', 'Structural Engineering', 'Associate Professor', 'sspendhari@st.vjti.ac.in'),

    # Textile Engineering
    ('Dr. S.P. Borkar', 'Textile Engineering', 'Professor & HOD', 'spborkar@tx.vjti.ac.in'),
    ('Dr. Suranjana Gangopadhyay', 'Textile Engineering', 'Assistant Professor', 'sgangopadhyay@tx.vjti.ac.in'),
    ('Dr. Neha Mehra', 'Textile Engineering', 'Assistant Professor', 'nehamehra@tx.vjti.ac.in'),
    ('Prof. Aniket Gajbhiye', 'Textile Engineering', 'Assistant Professor', 'akgajbhiye@tx.vjti.ac.in'),

    # Humanities & Management
    ('Dr. K.K. Sangle', 'Humanities & Management', 'Professor & HOD', 'hod_humanities@hs.vjti.ac.in'),
    ('Prof. Kishor Borase', 'Humanities & Management', 'Assistant Professor', 'krborase@hs.vjti.ac.in'),
    ('Dr. Nilima Chaudhary', 'Humanities & Management', 'Assistant Professor', 'nchaudhary@hs.vjti.ac.in'),
]
    cursor.executemany('INSERT INTO faculty (name, department, designation, email) VALUES (?, ?, ?, ?)', faculty_data)
    
    # --- 4. Location Data ---
    location_data = [
        # Buildings (Lat/Long required)
        ('Main Gate', 'Entrance, VJTI Gate, Security', 'Gate', 19.022350, 72.855950, None, 'Ground', 'assets/gate.jpg'),
        ('Main Building', 'Admin Office, Principal Office, Main Audi', 'Academic', 19.022750, 72.856200, None, 'G+3', 'assets/main_bldg.jpg'),
        ('IT Dept', 'Computer Dept, IT Building, CS Dept', 'Academic', 19.022500, 72.856300, None, 'G+2', 'assets/it_dept.jpg'),
        ('Central Library', 'Main Library, Reading Hall, Books', 'Academic', 19.022200, 72.856500, None, 'G+1', 'assets/library.jpg'),
        ('Mechanical Dept', 'Mech Building, Workshop', 'Academic', 19.022900, 72.855800, None, 'G+2', 'assets/mech_dept.jpg'),
        
        # Classrooms/Rooms (Linked to Parent Buildings)
        ('Room 101', 'FY Class, 101', 'Classroom', 19.022750, 72.856200, 'Main Building', '1st Floor', 'assets/room101.jpg'),
        ('Room 205', 'Electronics Class, 205', 'Classroom', 19.022750, 72.856200, 'Main Building', '2nd Floor', 'assets/room205.jpg'),
        ('CC Lab', 'Computer Center, CC', 'Lab', 19.022500, 72.856300, 'IT Dept', 'Ground Floor', 'assets/cc_lab.jpg'),
        ('Seminar Hall', 'IT Seminar Hall', 'Academic', 19.022500, 72.856300, 'IT Dept', '2nd Floor', 'assets/it_seminar.jpg')
    ]
    cursor.executemany('INSERT INTO locations (name, aliases, category, latitude, longitude, parent_building, floor_info, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', location_data)

    conn.commit()
    print("✅ All data inserted successfully (Cutoffs, Programs, Faculty, Locations).")
    conn.close()

if __name__ == "__main__":
    create_database()