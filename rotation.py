import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정 및 데이터 로드
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v26.0)")

# 💡 관리자님의 실제 시트 ID를 여기에 입력하세요!
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
SHEET_NAME = "Sheet1" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.astype(str).replace(['nan', 'None', 'nan.0'], None).apply(lambda x: x.str.strip() if hasattr(x, "str") else x)
        return df
    except: return pd.DataFrame()

db_df = load_db()
if db_df.empty:
    st.error("❌ 시트 로드 실패"); st.stop()

db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
store_list = sorted([s for s in db_df['매장명'].unique() if s and str(s).lower() != 'none'])
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", store_list)
store_data = db_df[db_df['매장명'] == selected_store].copy()

# 2. 구역 및 TO 설정 (시트의 '운영구역' 열 데이터 활용)
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data[zone_col].dropna().empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 운영 구역 및 TO", raw_zones)

zone_to_map = {}
for z_info in zone_input.split(","):
    z_info = z_info.strip()
    match = re.search(r"(.+)\((\d+)\)", z_info)
    if match:
        zone_to_map[match.group(1).strip()] = int(match.group(2))
    else:
        zone_to_map[z_info] = 1
target_zones = list(zone_to_map.keys())

# 3. 이름 추출 및 인원 선택
def extract_names(data, keyword):
    type_col = '구분' if '구분' in data.columns else data.columns[2]
    name_col = '이름' if '이름' in data.columns else data.columns[1]
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [n.replace('.0', '') if n.endswith('.0') else n for n in filtered[name_col].dropna().tolist() if n != 'None']

all_ft = extract_names(store_data, '정직'); all_pt = extract_names(store_data, '파트')
working_ft = st.sidebar.multiselect("✅ 오늘 정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("✅ 오늘 파트타이머", all_pt, default=all_pt)

# 4. 상세 시간 및 식사조 설정
group_configs = {}
num_groups = st.sidebar.select_slider("식사 조 개수", options=[2, 3, 4], value=2)
group_labels = ["A", "B", "C", "D"][:num_groups]

for label in group_labels:
    with st.sidebar.expander(f"📅 {label}조 시간 설정"):
        s_t = st.number_input(f"{label}조 출근", 8, 12, 10, key=f"gs_{label}")
        e_t = st.number_input(f"{label}조 퇴근", 17, 22, 20, key=f"ge_{label}")
        m1 = st.selectbox(f"{label}조 식사1", [f"{h}:00" for h in range(s_t, e_t)], index=1, key=f"m1_{label}")
        m2 = st.selectbox(f"{label}조 식사2", [f"{h}:00" for h in range(s_t, e_t)], index=5, key=f"m2_{label}")
        group_configs[label] = {"start": s_t, "end": e_t, "meals": [m1, m2]}

ft_assignments = {}
for i, ft in enumerate(working_ft):
    ft_assignments[ft] = st.sidebar.selectbox(f"{ft} 조", group_labels, key=f"assign_{ft}_{i}")

pt_settings = {}
for i, pt in enumerate(working_pt):
    pt_row = store_data[store_data['이름'] == pt].iloc[0] if pt in store_data['이름'].values else {}
    with st.sidebar.expander(f"📌 {pt} 설정"):
        ps_t = st.number_input(f"{pt} 출근", 8, 20, int(pt_row.get('출근시간', 10)) if pt_row.get('출근시간') else 10, key=f"{pt}_ps_{i}")
        pe_t = st.number_input(f"{pt} 퇴근", 10, 23, int(pt_row.get('퇴근시간', 20)) if pt_row.get('퇴근시간') else 20, key=f"{pt}_pe_{i}")
        pm_t = st.selectbox(f"{pt} 식사", [f"{h}:00" for h in range(8, 23)], index=5, key=f"{pt}_pm_{i}")
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=str(pt_row.get('카운터여부', 'X')).upper() in ['O', 'Y'], key=f"{pt}_counter_{i}")
        pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t, "can_counter": can_counter}

# 5. 로테이션 알고리즘 (TO 및 2시간 연속 금지 반영)
def generate_v26():
    all_starts = [conf["start"] for conf in group_configs.values()] + ([p["start"] for p in pt_settings.values()] if pt_settings else [10])
    all_ends = [conf["end"] for conf in group_configs.values()] + ([p["end"] for p in pt_settings.values()] if pt_settings else [20])
    time_slots = [f"{h}:00" for h in range(min(all_starts), max(all_ends))]
    
    final_rows = []; zone_history = {z: [] for z in target_zones}
    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        row = {"시간": slot}
        ft_working = [ft for ft in working_ft if slot not in group_configs[ft_assignments[ft]]["meals"]]
        pt_working = [pt for pt in working_pt if slot != pt_settings[pt].get("meal") and pt_settings[pt]["start"] <= curr_h < pt_settings[pt]["end"]]
        
        counter_pool = ft_working + [pt for pt in pt_working if pt_settings[pt]["can_counter"]]
        random.shuffle(counter_pool)
        
        pool = ft_working + pt_working
        random.shuffle(pool)
        assign = {z: [] for z in target_zones}
        
        for z in target_zones:
            to = zone_to_map[z]
            for _ in range(to):
                if z == target_zones[0]: # 카운터 우선 배치
                    if counter_pool:
                        p = counter_pool.pop(0)
                        assign[z].append(p)
                        if p in pool: pool.remove(p)
                    else: assign[z].append("X")
                else:
                    if pool:
                        valid = [p for p in pool if p not in zone_history[z]]
                        chosen = random.choice(valid if valid else pool)
                        assign[z].append(chosen)
                        pool.remove(chosen)
                    else: assign[z].append("X")

        for z in target_zones:
            row[z] = ", ".join(assign[z])
            zone_history[z] = (assign[z] + zone_history[z])[:to*2]
        final_rows.append(row)
    return pd.DataFrame(final_rows)

# 6. 실행 및 출력
if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df = generate_v26()

if 'df' in st.session_state:
    st.subheader(f"📊 {selected_store} 로테이션 결과")
    st.data_editor(st.session_state.df, use_container_width=True)
