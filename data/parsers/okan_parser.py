"""
Module for parsing real-world university dataset (Okan University).
Uses pandas to clean and map raw Excel exports into the CSP domain architecture.
"""

import pandas as pd
from collections import defaultdict
from src.models.domain import Exam, TimeSlot, Room, Instructor, ProblemInstance

def parse_okan(
    student_excel_path: str,
    schedule_excel_path: str,
    exams_sheet_name: str = "FINAL(8-18 OCAK)"
) -> ProblemInstance:
    """
    Parses messy real-world Excel files and builds a ProblemInstance.
    Handles heterogeneous exam modes (online vs. face-to-face) via Virtual Rooms.
    Features robust header detection to bypass Excel title rows.
    """

    print("Reading data from Excel files (applying robust header detection)...")

    # ==========================================
    # STEP 1: Parse Rooms & Create Virtual Room
    # ==========================================
    df_rooms = pd.read_excel(schedule_excel_path, sheet_name="DERSLİK KAPASİTE")
    
    rooms = []
    room_name_to_id = {}
    room_id_counter = 0

    for index, row in df_rooms.iterrows():
        room_name = str(row.iloc[0]).strip()
        capacity = row.iloc[1]
        
        if pd.isna(room_name) or room_name == 'nan':
            continue
            
        if isinstance(capacity, str):
            capacity = int(''.join(filter(str.isdigit, capacity)))
            
        rooms.append(Room(id=room_id_counter, capacity=int(capacity)))
        room_name_to_id[room_name] = room_id_counter
        room_id_counter += 1

    # Virtual Room for ONLINE exams
    VIRTUAL_ROOM_ID = room_id_counter 
    rooms.append(Room(id=VIRTUAL_ROOM_ID, capacity=100000))

    # ==========================================
    # STEP 2: Parse Instructors Metadata (Delayed Instantiation)
    # ==========================================
    # We delay creating Instructor objects until timeslots are parsed to satisfy domain rules.
    df_inst_raw = pd.read_excel(schedule_excel_path, sheet_name="İZİN GÜNLERİ", header=None)
    
    header_idx_inst = 0
    for i, row in df_inst_raw.iterrows():
        if any('UNVAN' in str(val).upper() for val in row.values):
            header_idx_inst = i
            break
            
    df_inst_raw.columns = [str(c).strip() for c in df_inst_raw.iloc[header_idx_inst].values]
    df_inst = df_inst_raw.iloc[header_idx_inst + 1:]
    
    instructor_meta = {} # Temporary storage for instructor attributes
    inst_name_to_id = {}
    inst_id_counter = 0

    for index, row in df_inst.iterrows():
        if 'UNVAN/ AD SOYAD' not in df_inst.columns:
            continue
            
        raw_name = str(row['UNVAN/ AD SOYAD']).strip()
        if pd.isna(raw_name) or raw_name == 'nan':
            continue
            
        is_phd = "AR. GÖR" in raw_name.upper()
        
        # Store metadata for later instantiation
        instructor_meta[inst_id_counter] = {"is_phd": is_phd, "name": raw_name}
        inst_name_to_id[raw_name] = inst_id_counter
        inst_id_counter += 1

    # ==========================================
    # STEP 3: Parse Exam Schedule & Timeslots
    # ==========================================
    df_exams_raw = pd.read_excel(schedule_excel_path, sheet_name=exams_sheet_name, header=None)
    
    header_idx_exams = 0
    for i, row in df_exams_raw.iterrows():
        if any('DERS KODU' in str(val).upper() for val in row.values):
            header_idx_exams = i
            break
            
    df_exams_raw.columns = [str(c).strip() for c in df_exams_raw.iloc[header_idx_exams].values]
    df_exams = df_exams_raw.iloc[header_idx_exams + 1:]
    
    timeslots = []
    exams_metadata = {} 
    timeslot_map = {} 
    ts_id_counter = 0
    valid_exam_codes = []

    for index, row in df_exams.iterrows():
        course_code = str(row.get('Ders Kodu', '')).strip()
        
        if pd.isna(course_code) or course_code == 'nan' or course_code == 'None' or course_code == '':
            continue
            
        valid_exam_codes.append(course_code)
            
        date_str = str(row.get('Gün', '')).strip()
        time_str = str(row.get('Saat', '')).strip()
        room_str = str(row.get('Derslik', '')).strip().upper()
        
        ts_key = f"{date_str}_{time_str}"
        if ts_key not in timeslot_map:
            ts_day = ts_id_counter // 5 
            ts_period = ts_id_counter % 5
            timeslots.append(TimeSlot(id=ts_id_counter, day=ts_day, period=ts_period))
            timeslot_map[ts_key] = ts_id_counter
            ts_id_counter += 1
            
        is_online = "ONLINE" in room_str or "ON LINE" in room_str
        
        lecturer_name = str(row.get('Öğretim Elemanı', '')).strip()
        lecturer_id = inst_name_to_id.get(lecturer_name, 0) 
        
        exams_metadata[course_code] = {
            "is_online": is_online,
            "lecturer_id": lecturer_id
        }

    # ==========================================
    # STEP 3.5: Instantiate Instructor Objects
    # ==========================================
    # Now that we have all timeslots, we can build the preferences dict without triggering domain ValueError.
    instructors = []
    for inst_id, meta in instructor_meta.items():
        # Default all timeslots to True (available)
        prefs = {ts.id: True for ts in timeslots}
        instructors.append(Instructor(id=inst_id, is_phd=meta["is_phd"], preferences=prefs))

    # ==========================================
    # STEP 4: Parse Students (Conflict Graph Base)
    # ==========================================
    df_students = pd.read_excel(student_excel_path)
    df_students.columns = [str(c).strip() for c in df_students.columns]
    
    exam_students_map = defaultdict(set)
    
    for index, row in df_students.iterrows():
        if 'Ders Kodu' not in df_students.columns or 'Öğrenci No' not in df_students.columns:
            continue
            
        course_code = str(row['Ders Kodu']).strip()
        raw_student_id = row['Öğrenci No']
        
        if course_code in valid_exam_codes and not pd.isna(raw_student_id):
            # ÇAP/Yandal gibi durumlardaki '-1' eklerini temizle ve ana ID'yi al
            clean_student_id = str(raw_student_id).split('-')[0].strip()
            
            # Harf vs. kalmış olma ihtimaline karşı sadece rakamları filtrele
            clean_student_id = ''.join(filter(str.isdigit, clean_student_id))
            
            if clean_student_id: # Eğer tamamen boş dönmediyse set'e ekle
                exam_students_map[course_code].add(int(clean_student_id))

    # ==========================================
    # STEP 5: Assemble Final Exam Objects
    # ==========================================
    exams = []
    exam_id_counter = 0
    
    for course_code in valid_exam_codes:
        students = exam_students_map.get(course_code, set())
        
        # YENİ MANTIK: Öğrencisi 0 olan sınavları programa HİÇ DAHİL ETME!
        # Dummy student eklemek yerine bu sınavı direkt atlıyoruz (Drop missing data).
        if len(students) == 0:
            continue 
            
        req_invig = max(1, len(students) // 40)
        meta = exams_metadata.get(course_code, {"is_online": False, "lecturer_id": 0})
        
        exam_obj = Exam(
            id=exam_id_counter,
            student_ids=students,
            lecturer_id=meta["lecturer_id"], 
            required_invigilators=req_invig,
            is_online=meta["is_online"]
        )
        exams.append(exam_obj)
        exam_id_counter += 1

    print(f"Parsing complete. Found {len(exams)} exams, {len(rooms)} rooms, {len(instructors)} instructors.")

    return ProblemInstance(
        exams=exams,
        timeslots=timeslots,
        rooms=rooms,
        instructors=instructors
    )