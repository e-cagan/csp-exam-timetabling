"""
CP-SAT based solver for the University Exam Timetabling Problem.
(Upgraded to MULTI-ROOM / EXAM SPLITTING Architecture)
"""

from collections import defaultdict
from ortools.sat.python import cp_model

from src.utils.conflict_graph import build_conflict_graph
from src.models.domain import ProblemInstance
from src.models.solution import Solution


def solve(
    instance: ProblemInstance,
    w1: int = 1,
    w2: int = 5,
    w3: int = 2,
    w4: int = 3,
    enable_s3: bool = True,
    enable_s4: bool = True,
    time_limit: int = 120
) -> tuple[Solution | None, dict]:

    model = cp_model.CpModel()

    # ==================== Conflict Graph ====================
    conflict_graph = build_conflict_graph(exams=instance.exams)
    virtual_room_id = next((r.id for r in instance.rooms if r.capacity == 100000), -1)

    # ==================== Decision Variables ====================
    exam_times = {}
    room_used = {} # YENİ YAPI: room_used[exam_id][room_id] -> 0 veya 1

    for exam in instance.exams:
        exam_times[exam.id] = model.new_int_var(0, len(instance.timeslots) - 1, f"time_{exam.id}")
        
        room_used[exam.id] = {}
        for room in instance.rooms:
            room_used[exam.id][room.id] = model.new_bool_var(f"room_{exam.id}_{room.id}")

    invigilator = {}
    for exam in instance.exams:
        invigilator[exam.id] = {}
        for inst in instance.instructors:
            invigilator[exam.id][inst.id] = model.new_bool_var(f"invig_{exam.id}_{inst.id}")

    # ======================== HARD CONSTRAINTS ========================

    # ==================== H1: No Student Time Conflict ====================
    for exam_a, neighbors in conflict_graph.items():
        for exam_b in neighbors:
            if exam_a < exam_b:
                model.add(exam_times[exam_a] != exam_times[exam_b])

    # ==================== H2: Room Capacity (Multi-Room Logic) ====================
    overflow_penalties = [] # Taşma (Online'a zorlanma) cezalarını tutacak liste

    for exam in instance.exams:
        if exam.is_online:
            # Doğal online sınavlar sadece sanal odayı kullanır
            model.add(room_used[exam.id][virtual_room_id] == 1)
            for r in instance.rooms:
                if r.id != virtual_room_id:
                    model.add(room_used[exam.id][r.id] == 0)
        else:
            # FİZİKSEL SINAVLAR İÇİN EMNİYET SUBABI MANTIĞI:
            # is_overflow True ise, fiziksel oda yetmediği için mecburen sanal odaya atılmış demektir.
            is_overflow = room_used[exam.id][virtual_room_id]
            overflow_penalties.append(is_overflow)
            
            # Eğer taşma (overflow) YOKSA, seçilen fiziksel odaların toplamı öğrenci sayısına yetmelidir.
            model.add(
                sum(room_used[exam.id][r.id] * r.capacity for r in instance.rooms if r.id != virtual_room_id)
                >= len(exam.student_ids)
            ).only_enforce_if(is_overflow.negated())
            
            # Eğer taşma (overflow) VARSA, fiziksel oda kullanımını tamamen yasakla (Sadece Online yapılsın)
            for r in instance.rooms:
                if r.id != virtual_room_id:
                    model.add(room_used[exam.id][r.id] == 0).only_enforce_if(is_overflow)

    # ==================== H6: Minimum Invigilators Per Exam ====================
    for exam in instance.exams:
        model.add(
            sum(invigilator[exam.id][inst.id] for inst in instance.instructors) == exam.required_invigilators
        )

    # ==================== H4, H5 & H3: Conflicts and Room Clashes ====================
    for i in range(len(instance.exams)):
        for j in range(i + 1, len(instance.exams)):
            e_a = instance.exams[i].id
            e_b = instance.exams[j].id

            same_slot = model.new_bool_var(f"same_slot_{e_a}_{e_b}")
            model.add(exam_times[e_a] == exam_times[e_b]).only_enforce_if(same_slot)
            model.add(exam_times[e_a] != exam_times[e_b]).only_enforce_if(same_slot.negated())

            # YENİ H3 (Room Clash): Eğer iki sınav aynı saatteyse (same_slot=True), aynı fiziksel odayı paylaşamazlar!
            for r in instance.rooms:
                if r.id != virtual_room_id:
                    model.add(room_used[e_a][r.id] + room_used[e_b][r.id] <= 1).only_enforce_if(same_slot)

            # H5
            for inst in instance.instructors:
                model.add(
                    invigilator[e_a][inst.id] + invigilator[e_b][inst.id] <= 1
                ).only_enforce_if(same_slot)

            # H4
            lec_a = instance.exams[i].lecturer_id
            lec_b = instance.exams[j].lecturer_id
            model.add(invigilator[e_b][lec_a] == 0).only_enforce_if(same_slot)
            model.add(invigilator[e_a][lec_b] == 0).only_enforce_if(same_slot)


    # ======================== SOFT CONSTRAINTS ========================
    s1_cost = []
    for exam in instance.exams:
        for inst in instance.instructors:
            dislike = [0 if inst.preferences.get(t, True) else 1 for t in range(len(instance.timeslots))]
            if sum(dislike) == 0:
                continue

            slot_penalty = model.new_int_var(0, 1, f"s1_slot_{exam.id}_{inst.id}")
            model.add_element(exam_times[exam.id], dislike, slot_penalty)

            penalty_var = model.new_int_var(0, 1, f"s1_{exam.id}_{inst.id}")
            model.add_min_equality(penalty_var, [slot_penalty, invigilator[exam.id][inst.id]])
            s1_cost.append(penalty_var)

    # S2: Workload Fairness
    loads = []
    for inst in instance.instructors:
        load = model.new_int_var(0, len(instance.exams), f"load_{inst.id}")
        model.add(load == sum(invigilator[exam.id][inst.id] for exam in instance.exams))
        loads.append(load)

    max_load = model.new_int_var(0, len(instance.exams), "max_load")
    min_load = model.new_int_var(0, len(instance.exams), "min_load")
    model.add_max_equality(max_load, loads)
    model.add_min_equality(min_load, loads)

    s2_cost = model.new_int_var(0, len(instance.exams), "s2_cost")
    model.add(s2_cost == max_load - min_load)

    # S3: Avoid Consecutive Invigilation
    s3_cost = []
    if enable_s3:
        consecutive_pairs = []
        for t1 in instance.timeslots:
            for t2 in instance.timeslots:
                if t1.id < t2.id and t1.day == t2.day and abs(t1.period - t2.period) == 1:
                    consecutive_pairs.append((t1.id, t2.id))

        for inst in instance.instructors:
            for t_early, t_late in consecutive_pairs:
                active_early_list = []
                active_late_list = []

                for exam in instance.exams:
                    is_in_early = model.new_bool_var(f"s3_ie_{exam.id}_{inst.id}_{t_early}")
                    model.add(exam_times[exam.id] == t_early).only_enforce_if(is_in_early)
                    model.add(exam_times[exam.id] != t_early).only_enforce_if(is_in_early.negated())

                    both_early = model.new_bool_var(f"s3_be_{exam.id}_{inst.id}_{t_early}")
                    model.add_min_equality(both_early, [is_in_early, invigilator[exam.id][inst.id]])
                    active_early_list.append(both_early)

                    is_in_late = model.new_bool_var(f"s3_il_{exam.id}_{inst.id}_{t_late}")
                    model.add(exam_times[exam.id] == t_late).only_enforce_if(is_in_late)
                    model.add(exam_times[exam.id] != t_late).only_enforce_if(is_in_late.negated())

                    both_late = model.new_bool_var(f"s3_bl_{exam.id}_{inst.id}_{t_late}")
                    model.add_min_equality(both_late, [is_in_late, invigilator[exam.id][inst.id]])
                    active_late_list.append(both_late)

                active_in_early = model.new_bool_var(f"s3_ae_{inst.id}_{t_early}")
                model.add_max_equality(active_in_early, active_early_list)

                active_in_late = model.new_bool_var(f"s3_al_{inst.id}_{t_late}")
                model.add_max_equality(active_in_late, active_late_list)

                consec_penalty = model.new_bool_var(f"s3_{inst.id}_{t_early}_{t_late}")
                model.add_min_equality(consec_penalty, [active_in_early, active_in_late])
                s3_cost.append(consec_penalty)

    # S4: Student Consecutive Day Gap
    s4_cost = []
    if enable_s4:
        periods_per_day = max(t.period for t in instance.timeslots) + 1
        n_days = max(t.day for t in instance.timeslots) + 1

        exam_day = {}
        for exam in instance.exams:
            exam_day[exam.id] = model.new_int_var(0, n_days - 1, f"day_{exam.id}")
            model.add_division_equality(exam_day[exam.id], exam_times[exam.id], periods_per_day)

        student_exams = defaultdict(list)
        for exam in instance.exams:
            for sid in exam.student_ids:
                student_exams[sid].append(exam.id)

        for sid, eids in student_exams.items():
            if len(eids) < 2:
                continue

            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    e_a = eids[i]
                    e_b = eids[j]

                    diff = model.new_int_var(-(n_days - 1), n_days - 1, f"s4_diff_{sid}_{e_a}_{e_b}")
                    model.add(diff == exam_day[e_a] - exam_day[e_b])

                    abs_diff = model.new_int_var(0, n_days - 1, f"s4_abs_{sid}_{e_a}_{e_b}")
                    model.add_abs_equality(abs_diff, diff)

                    penalty = model.new_bool_var(f"s4_{sid}_{e_a}_{e_b}")
                    model.add(abs_diff <= 1).only_enforce_if(penalty)
                    model.add(abs_diff >= 2).only_enforce_if(penalty.negated())

                    s4_cost.append(penalty)

    # ==================== Objective Function ====================
    total_s3 = sum(s3_cost) if s3_cost else 0
    total_s4 = sum(s4_cost) if s4_cost else 0
    
    # S5: Anti-Fragmentation (Sınavların gereksiz yere parçalanmasını önler)
    total_rooms_used = sum(room_used[e.id][r.id] for e in instance.exams for r in instance.rooms if r.id != virtual_room_id)

    total_objective = model.new_int_var(0, 10000000, "total_objective")
    model.add(
        # YENİ: overflow_penalties * 5000 ekledik.
        # Bu devasa ceza sayesinde sistem mecbur kalmadıkça (bina dolmadıkça) hiçbir fiziksel sınavı online'a atmaz!
        total_objective == w1 * sum(s1_cost) + w2 * s2_cost + w3 * total_s3 + w4 * total_s4 + total_rooms_used + sum(overflow_penalties) * 5000
    )
    model.minimize(total_objective)

    # ==================== Solve ====================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit

    status = solver.solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        exam_time_result = {}
        exam_room_result = {} # Artık dict[int, list[int]] dönmeli

        for exam in instance.exams:
            exam_time_result[exam.id] = solver.value(exam_times[exam.id])
            
            # YENİ: Çözücünün seçtiği (değeri 1 olan) tüm odaları bir listeye topla
            assigned_rooms = [r.id for r in instance.rooms if solver.value(room_used[exam.id][r.id]) == 1]
            exam_room_result[exam.id] = assigned_rooms

        invig_result = {}
        for exam in instance.exams:
            assigned = set()
            for inst in instance.instructors:
                if solver.value(invigilator[exam.id][inst.id]) == 1:
                    assigned.add(inst.id)
            invig_result[exam.id] = assigned

        solution = Solution(
            exam_time=exam_time_result,
            exam_room=exam_room_result,
            assigned_invigilators=invig_result
        )

        stats = {
            "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            "objective": solver.objective_value,
            "s1_penalty": sum(solver.value(v) for v in s1_cost),
            "s2_penalty": solver.value(s2_cost),
            "s3_penalty": sum(solver.value(v) for v in s3_cost) if s3_cost else 0,
            "s4_penalty": sum(solver.value(v) for v in s4_cost) if s4_cost else 0,
            # YENİ EKLENEN METRİKLER (Hakemler ve analiz için)
            "total_rooms_used": solver.value(total_rooms_used),
            "overflow_count": sum(solver.value(v) for v in overflow_penalties),
            "wall_time": solver.wall_time,
            "max_load": solver.value(max_load),
            "min_load": solver.value(min_load),
        }

        return solution, stats

    return None, {"status": "INFEASIBLE", "wall_time": solver.wall_time}