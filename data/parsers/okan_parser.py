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
    exams_sheet_name: str = "FINAL(8-18 OCAK)",
    instructors_sheet_name: str = "İZİN GÜNLERİ",
    rooms_sheet_name: str = "DERSLİK KAPASİTE"
) -> tuple[ProblemInstance, list[str]]:
    """
    Returns: (ProblemInstance, list_of_real_course_codes)
    """

    print(f"Reading data from Excel files...")

    # ==========================================
    # STEP 1: Parse Rooms & Create Virtual Room
    # ==========================================
    df_rooms = pd.read_excel(schedule_excel_path, sheet_name=rooms_sheet_name)
    
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
            
        rooms.append(Room(id=room_id_counter, capacity=int(capacity), name=room_name))
        room_name_to_id[room_name] = room_id_counter
        room_id_counter += 1

    VIRTUAL_ROOM_ID = room_id_counter 
    rooms.append(Room(id=VIRTUAL_ROOM_ID, capacity=100000, name="ONLINE"))

    # ==========================================
    # STEP 2: Parse Instructors Metadata & OFF DAYS
    # ==========================================
    df_inst_raw = pd.read_excel(schedule_excel_path, sheet_name=instructors_sheet_name, header=None)
    header_idx_inst = 0
    for i, row in df_inst_raw.iterrows():
        if any('UNVAN' in str(val).upper() for val in row.values):
            header_idx_inst = i
            break
            
    df_inst_raw.columns = [str(c).strip() for c in df_inst_raw.iloc[header_idx_inst].values]
    df_inst = df_inst_raw.iloc[header_idx_inst + 1:]
    
    instructor_meta = {} 
    inst_name_to_id = {}
    inst_id_counter = 0

    for index, row in df_inst.iterrows():
        if 'UNVAN/ AD SOYAD' not in df_inst.columns:
            continue
            
        raw_name = str(row['UNVAN/ AD SOYAD']).strip()
        if pd.isna(raw_name) or raw_name == 'nan':
            continue
            
        is_phd = "AR. GÖR" in raw_name.upper()
        
        # HOCANIN İZİN GÜNLERİNİ BİRLEŞTİR VE KAYDET
        off_days = str(row.get('İZİN GÜNÜ -1', '')) + " " + str(row.get('İZİN GÜNÜ-2', '')) + " " + str(row.get('İZİN GÜNÜ-3', ''))
        
        instructor_meta[inst_id_counter] = {"is_phd": is_phd, "name": raw_name, "off_days": off_days.upper()}
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
    ts_id_to_day_name = {} # Hangi timeslot hangi güne (Pazartesi, Cuma vb.) denk geliyor?
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
            ts_id_to_day_name[ts_id_counter] = date_str.upper() # Günü kaydet
            ts_id_counter += 1
            
        is_weekend = "CUMARTESİ" in date_str.upper() or "PAZAR" in date_str.upper()
        is_online = "ONLINE" in room_str or "ON LINE" in room_str or is_weekend
        
        lecturer_name = str(row.get('Öğretim Elemanı', '')).strip()
        lecturer_id = inst_name_to_id.get(lecturer_name, 0) 
        
        exams_metadata[course_code] = {"is_online": is_online, "lecturer_id": lecturer_id}

    # ==========================================
    # STEP 3.5: Instantiate Instructor Objects with REAL PREFERENCES
    # ==========================================
    DAY_NAMES = ["PAZARTESİ", "SALI", "ÇARŞAMBA", "PERŞEMBE", "CUMA", "CUMARTESİ", "PAZAR"]
    instructors = []
    
    for inst_id, meta in instructor_meta.items():
        prefs = {}
        off_days_str = meta["off_days"]
        
        for ts in timeslots:
            ts_day_name = ts_id_to_day_name[ts.id]
            # Eğer timeslot'un günü, hocanın izinli olduğu günlerden biriyse -> Müsait Değil (False)
            is_off = any(day in ts_day_name and day in off_days_str for day in DAY_NAMES)
            prefs[ts.id] = not is_off
            
        instructors.append(Instructor(id=inst_id, is_phd=meta["is_phd"], preferences=prefs))

    # ==========================================
    # STEP 4 & 5: Parse Students and Assemble Exams
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
            clean_student_id = str(raw_student_id).split('-')[0].strip()
            clean_student_id = ''.join(filter(str.isdigit, clean_student_id))
            if clean_student_id: 
                exam_students_map[course_code].add(int(clean_student_id))

    exams = []
    exam_id_counter = 0
    for course_code in valid_exam_codes:
        students = exam_students_map.get(course_code, set())
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

    # ARTIK GERÇEK DERS KODLARINI DA DÖNÜYORUZ!
    return ProblemInstance(exams=exams, timeslots=timeslots, rooms=rooms, instructors=instructors), valid_exam_codes