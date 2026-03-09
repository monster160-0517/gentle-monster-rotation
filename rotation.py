import streamlit as st
import pandas as pd
import random

# 1. 페이지 설정
st.set_page_config(page_title="GM Master Dashboard", layout="wide")
st.title("🕶️ GENTLE MONSTER 통합 관제 대시보드 (v16.2)")

# 2. 사이드바 설정 (인원 DB 및 멀티셀렉트)
st.sidebar.header("👥 인력 풀 관리 (DB)")
ft_db = st.sidebar.text_area("전체 정직원 명단", "정민, 기남, 영준, 혜인, 수정", help="쉼표로 구분")
pt_db = st.sidebar.text_area("전체 파트타이머 명단", "예리, 강욱, 찬웅, 현우, 허규", help="쉼표로 구분")

all_ft = [s.strip() for s in ft_db.split(",") if s.strip()]
all_pt = [s.strip() for s in pt_db.split(",") if s.strip()]

st.sidebar.divider()
st.sidebar.header("✅ 오늘 출근 인원 확정")
working_ft = st.sidebar.multiselect("출근 정직원 선택", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("출근 파트타이머 선택", all_pt, default=all_pt)

# 3. 정직원 조별 상세 설정
st.sidebar.divider()
st.sidebar.header("🍱 정직원 조별 상세 설정")
num_groups = st.sidebar.select_slider("식사 조 개수", options=[2, 3, 4], value=2)

group_configs = {}
group_labels = ["A", "B", "C", "D"][:num_groups]

for label in group_labels:
    with st.sidebar.expander(f"📅 {label}조 시간 설정"):
        s_t = st.number_input(f"{label}조 출근", 8, 12, 10, key=f"gs_{label}")
        e_t = st.number_input(f"{label}조 퇴근", 17, 22, 20, key=f"ge_{label}")
        m1 = st.selectbox(f"{label}조 식사1", [f"{h}:00" for h in range(s_t, e_t)], index=1, key=f"m1_{label}")
        m2 = st.selectbox(f"{label}조 식사2", [f"{h}:00" for h in range(s_t, e_t)], index=5, key=f"m2_{label}")
        group_configs[label] = {"start": s_t, "end": e_t, "meals": [m1, m2]}

# [핵심 업데이트] 직원별 조 지정 (순서 상관 없이 선택 가능)
ft_assignments = {}
if working_ft:
    st.sidebar.subheader("👤 직원별 조 지정")
    # 출근한 직원을 세로 리스트로 보여주며 조를 선택하게 함
    for ft in working_ft:
        ft_assignments[ft] = st.sidebar.selectbox(f"{ft} 님", group_labels, key=f"assign_{ft}")

# 파트타이머 상세 설정
pt_settings = {}
if working_pt:
    st.sidebar.header("🕒 파트타이머 상세 설정")
    for pt in working_pt:
        with st.sidebar.expander(f"📌 {pt} 시간 설정"):
            ps_t = st.number_input(f"{pt} 출근", 10, 20, 10, key=f"{pt}_ps")
            pe_t = st.number_input(f"{pt} 퇴근", 11, 21, 20, key=f"{pt}_pe")
            pm_t = st.selectbox(f"{pt} 식사", [f"{h}:00" for h in range(ps_t+1, pe_t-1)], key=f"{pt}_pm")
            pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t}

st.sidebar.header("📍 구역 설정")
zone_input = st.sidebar.text_input("운영 구역", "카운터, A, B, C, D, E")
target_zones = [z.strip() for z in zone_input.split(",") if z.strip()]

# 4. 로직 함수
def generate_v16_2():
    # 출퇴근 시간에 따른 동적 타임라인 생성
    all_starts = [conf["start"] for conf in group_configs.values()] + ([p["start"] for p in pt_settings.values()] if pt_settings else [10])
    all_ends = [conf["end"] for conf in group_configs.values()] + ([p["end"] for p in pt_settings.values()] if pt_settings else [20])
    
    time_slots = [f"{h}:00" for h in range(min(all_starts), max(all_ends))]
    final_rows = []
    zone_history = {z: [] for z in target_zones}

    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        row = {"시간": slot}
        
        ft_off, ft_working_now = [], []
        for ft in working_ft:
            # 관리자님이 지정한 조의 설정을 가져옴
            group_label = ft_assignments[ft]
            conf = group_configs[group_label]
            if conf["start"] <= curr_h < conf["end"]:
                if slot in conf["meals"]: ft_off.append(ft)
                else: ft_working_now.append(ft)
        
        pt_off, pt_working_now = [], []
        for pt in working_pt:
            conf = pt_settings[pt]
            if conf["start"] <= curr_h < conf["end"]:
                if slot == conf["meal"]: pt_off.append(pt)
                else: pt_working_now.append(pt)
        
        row["부재(정)"] = ", ".join(ft_off)
        row["부재(파)"] = ", ".join(pt_off)
        pool = ft_working_now + pt_working_now
        random.shuffle(pool)
        
        assign = {z: [] for z in target_zones}
        for z in target_zones:
            if pool:
                excluded = zone_history[z]
                valid = [p for p in pool if p not in excluded]
                chosen = random.choice(valid if valid else pool)
                assign[z].append(chosen)
                pool.remove(chosen)
            else: assign[z].append("X")

        idx = 0
        while pool:
            z = target_zones[idx % len(target_zones)]
            p = pool.pop()
            if assign[z][0] == "X": assign[z] = [p]
            else: assign[z].append(p)
            idx += 1

        for z in target_zones:
            row[z] = ", ".join(assign[z])
            zone_history[z] = (assign[z] + zone_history[z])[:2]
        final_rows.append(row)
    return pd.DataFrame(final_rows)

# 5. 실행 및 출력
if st.sidebar.button("🚀 멀티 조 로테이션 생성"):
    if not working_ft and not working_pt:
        st.error("출근 인원을 선택해주세요!")
    else:
        st.session_state.df = generate_v16_2()

if 'df' in st.session_state:
    st.subheader("📊 오늘의 매장 통합 로테이션 (v16.2)")
    edited_df = st.data_editor(st.session_state.df, use_container_width=True)
    
    st.divider()
    st.subheader("📈 인원별 실근무 시간 요약 (식사 제외)")
    summary_data = []
    for ft in working_ft:
        group_label = ft_assignments[ft]
        conf = group_configs[group_label]
        summary_data.append({"이름": ft, "구분": f"정직원({group_label}조)", "실근무": f"{conf['end']-conf['start']-2}시간"})
    for pt in working_pt:
        summary_data.append({"이름": pt, "구분": "파트타이머", "실근무": f"{pt_settings[pt]['end']-pt_settings[pt]['start']-1}시간"})
    st.table(pd.DataFrame(summary_data))
    
    st.download_button("📥 최종 결과 엑셀 저장", edited_df.to_csv(index=False).encode('utf-8-sig'), "gm_v16_2.csv", "text/csv")