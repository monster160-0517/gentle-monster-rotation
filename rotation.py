# ... (상단 설정 부분 동일)

# 4. 파트타이머 설정 (카운터 가능 여부 추가)
pt_settings = {}
for pt in working_pt:
    with st.sidebar.expander(f"📌 {pt} 시간 및 권한"):
        ps_t = st.number_input(f"{pt} 출근", 10, 20, 10, key=f"{pt}_ps")
        pe_t = st.number_input(f"{pt} 퇴근", 11, 21, 20, key=f"{pt}_pe")
        pm_t = st.selectbox(f"{pt} 식사", [f"{h}:00" for h in range(ps_t+1, pe_t-1)], key=f"{pt}_pm")
        # ⭐ [신규] 카운터 가능 여부 체크박스
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=False, key=f"{pt}_counter")
        pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t, "can_counter": can_counter}

# 5. 로직 함수 (권한 기반 배치)
def generate_v19():
    # ... (시간 슬롯 계산 동일)
    
    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        row = {"시간": slot}
        
        # 현재 근무 가능한 인원 분류
        ft_working = [ft for ft in working_ft if slot not in group_configs[ft_assignments[ft]]["meals"]]
        pt_working = [pt for pt in working_pt if slot != pt_settings[pt]["meal"] and pt_settings[pt]["start"] <= curr_h < pt_settings[pt]["end"]]
        
        # ⭐ [로직 업데이트] 카운터 가능 인원 추출 (정직원 전원 + 체크된 파트타이머)
        counter_pool = ft_working + [pt for pt in pt_working if pt_settings[pt]["can_counter"]]
        random.shuffle(counter_pool)
        
        assign = {z: [] for z in target_zones}
        
        # 1. 카운터(또는 A구역) 배치
        primary_zone = "카운터" if "카운터" in target_zones else target_zones[0]
        if counter_pool:
            chosen = counter_pool.pop(0)
            assign[primary_zone].append(chosen)
            # 사용한 인원은 전체 풀에서도 제거
            if chosen in ft_working: ft_working.remove(chosen)
            else: pt_working.remove(chosen)
        else:
            assign[primary_zone].append("X")

        # 2. 나머지 구역 배치 (남은 인원들 무작위)
        remaining_pool = ft_working + pt_working
        random.shuffle(remaining_pool)
        
        other_zones = [z for z in target_zones if z != primary_zone]
        for z in other_zones:
            if remaining_pool:
                valid = [p for p in remaining_pool if p not in zone_history[z]]
                chosen = random.choice(valid if valid else remaining_pool)
                assign[z].append(chosen)
                remaining_pool.remove(chosen)
            else:
                assign[z].append("X")

        # ... (인원 남을 시 분산 배치 및 이력 저장 동일)
