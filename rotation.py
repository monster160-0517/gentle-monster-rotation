import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정 및 데이터 로딩
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v30.0)")

# 💡 관리자님의 실제 시트 ID 입력
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

# 2. 구역 및 TO 설정
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data[zone_col].dropna().empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 운영 구역 및 TO", raw_zones)

zone_to_map = {}
for z_info in zone_input.split(","):
    z_info = z_info.strip()
    match = re.search(r"(.+)\((\d+)\)", z_info)
    if match: zone_to_map[match.group(1).strip()] = int(match.group(2))
    else: zone_to_map[z_info] = 1
target_zones = list(zone_to_map.keys())

# 3. 인원 추출
def extract_names(data, keyword):
    type_col = '구분' if '구분' in data.columns else data.columns[2]
    name_col = '이름' if '이름' in data.columns else data.columns[1]
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [n.replace('.0', '') if n.endswith('.0') else n for n in filtered[name_col].dropna().tolist() if n != 'None']

all_ft = extract_names(store_data, '정직'); all_pt = extract_names(store_data, '파트')
working_ft = st.sidebar.multiselect("✅ 오늘 출근 정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("✅ 오늘 출근 파트타이머", all_pt, default=all_pt)

# 4. [업데이트] 식사 조별 시간 설정 (A~E)
st.sidebar.header("🍴 식사 조별 시간 고정 (A~E)")
group_labels = ["A", "B", "C", "D", "E"] # ⭐ 조 편성 확장
lunch_configs = {}
dinner_configs = {}

with st.sidebar.expander("🕛 점심 조별 시간 (11시~15시)"):
    for label in group_labels:
        lunch_configs[label] = st.selectbox(f"점심 {label}조", [f"{h}:00" for h in range(11, 16)], 
                                            index=min(group_labels.index(label), 4), key=f"L_{label}")

with st.sidebar.expander("🌆 저녁 조별 시간 (17시~21시)"):
    for label in group_labels:
        dinner_configs[label] = st.selectbox(f"저녁 {label}조", [f"{h}:00" for h in range(17, 22)], 
                                             index=min(group_labels.index(label), 4), key=f"D_{label}")

# 5. 인원별 상세 스케줄 로드
ft_settings = {}
for i, ft in enumerate(working_ft):
    row = store_data[store_data['이름'] == ft].iloc[0]
    with st.sidebar.expander(f"👤 {ft} (정직원)"):
        s_val = int(float(row.get('출근시간', 10)))
        e_val = int(float(row.get('퇴근시간', 20)))
        l_group = str(row.get('점심조', 'A')).upper()
        d_group = str(row.get('저녁조', 'A')).upper()
        
        fs_t = st.number_input(f"{ft} 출근", 8, 22, s_val, key=f"fs_{ft}_{i}")
        fe_t = st.number_input(f"{ft} 퇴근", 9, 23, e_val, key=f"fe_{ft}_{i}")
        f_lunch = st.selectbox(f"{ft} 점심조", group_labels, index=group_labels.index(l_group) if l_group in group_labels else 0, key=f"fl_{ft}_{i}")
        f_dinner = st.selectbox(f"{ft} 저녁조", group_labels, index=group_labels.index(d_group) if d_group in group_labels else 0, key=f"fd_{ft}_{i}")
        
        ft_settings[ft] = {
            "start": fs_t, "end": fe_t, 
            "meals": [lunch_configs[f_lunch], dinner_configs[f_dinner]]
        }

pt_settings = {}
for i, pt in enumerate(working_pt):
    row = store_data[store_data['이름'] == pt].iloc[0]
    with st.sidebar.expander(f"📌 {pt} (파트타이머)"):
        ps_t = st.number_input(f"{pt} 출근", 8, 22, int(float(row.get('출근시간', 10))), key=f"ps_{pt}_{i}")
        pe_t = st.number_input(f"{pt} 퇴근", 9, 23, int(float(row.get('퇴근시간', 20))), key=f"pe_{pt}_{i}")
        time_list = [f"{h}:00" for h in range(8, 23)]
        m_val = str(row.get('식사시간', '13:00'))
        pm_t = st.selectbox(f"{pt} 식사", time_list, index=time_list.index(m_val) if m_val in time_list else 5, key=f"pm_{pt}_{i}")
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=str(row.get('카운터여부', 'X')).upper() in ['O', 'Y'], key=f"pc_{pt}_{i}")
        pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t, "can_counter": can_counter}

# 6. 로테이션 알고리즘 (동일)
def generate_v30():
    time_slots = [f"{h}:00" for h in range(8, 23)]
    final_rows = []; zone_history = {z: [] for z in target_zones}
    
    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        ft_working = [f for f in working_ft if ft_settings[f]["start"] <= curr_h < ft_settings[f]["end"] and slot not in ft_settings[f]["meals"]]
        pt_working = [p for p in working_pt if pt_settings[p]["start"] <= curr_h < pt_settings[p]["end"] and slot != pt_settings[p]["meal"]]
        
        if not ft_working and not pt_working: continue
        
        row = {"시간": slot}
        counter_pool = ft_working + [p for p in pt_working if pt_settings[p]["can_counter"]]
        random.shuffle(counter_pool); pool = ft_working + pt_working; random.shuffle(pool)
        assign = {z: [] for z in target_zones}
        
        for z in target_zones:
            to = zone_to_map[z]
            for _ in range(to):
                if z == target_zones[0]:
                    if counter_pool:
                        p = counter_pool.pop(0); assign[z].append(p)
                        if p in pool: pool.remove(p)
                    else: assign[z].append("X")
                else:
                    if pool:
                        valid = [p for p in pool if p not in zone_history[z]]
                        chosen = random.choice(valid if valid else pool)
                        assign[z].append(chosen); pool.remove(chosen)
                    else: assign[z].append("X")
        for z in target_zones:
            row[z] = ", ".join(assign[z]); zone_history[z] = (assign[z] + zone_history[z])[:to*2]
        final_rows.append(row)
    return pd.DataFrame(final_rows)

if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df = generate_v30()

if 'df' in st.session_state:
    st.subheader(f"📊 {selected_store} 로테이션 결과")
    st.data_editor(st.session_state.df, use_container_width=True)
