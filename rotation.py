import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v42.0)")

# 💡 관리자님의 실제 시트 ID 입력
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
SHEET_NAME = "Sheet1" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx:out:csv&sheet={SHEET_NAME}"

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
    st.error("❌ 시트 로드 실패 - ID 및 공유 설정을 확인하세요."); st.stop()

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

# 3. 인원 추출 및 선택
def extract_names(data, keyword):
    type_col = '구분' if '구분' in data.columns else data.columns[2]
    name_col = '이름' if '이름' in data.columns else data.columns[1]
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [n.replace('.0', '') if n.endswith('.0') else n for n in filtered[name_col].dropna().tolist() if n != 'None']

all_ft = extract_names(store_data, '정직'); all_pt = extract_names(store_data, '파트')
working_ft = st.sidebar.multiselect("✅ 오늘 출근 정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("✅ 오늘 출근 파트타이머", all_pt, default=all_pt)

# 4. 식사 조별 시간 설정
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}; dinner_configs = {}
with st.sidebar.expander("🕛 식사 조별 시간 설정"):
    for label in group_labels:
        lunch_configs[label] = st.selectbox(f"점심 {label}조", [f"{h}:00" for h in range(11, 17)], index=group_labels.index(label), key=f"L_{label}")
        dinner_configs[label] = st.selectbox(f"저녁 {label}조", [f"{h}:00" for h in range(17, 22)], index=group_labels.index(label), key=f"D_{label}")

# 5. 개인별 상세 설정 (⭐ NameError 원천 차단 로직)
ft_settings = {}
for i, ft in enumerate(working_ft):
    # 루프 시작 시 모든 변수 초기화 (에러 방지 핵심)
    l_group_val, d_group_val, s_time_val, e_time_val = "A", "A", 10, 20
    
    person_match = store_data[store_data['이름'] == ft]
    if not person_match.empty:
        r = person_match.iloc[0]
        l_group_val = str(r.get('점심조', 'A')).upper() if r.get('점심조') else 'A'
        d_group_val = str(r.get('저녁조', 'A')).upper() if r.get('저녁조') else 'A'
        try:
            s_time_val = int(float(r.get('출근시간', 10)))
            e_time_val = int(float(r.get('퇴근시간', 20)))
        except: pass

    with st.sidebar.expander(f"💼 {ft} (정직원)"):
        fs_t = st.number_input(f"{ft} 출근", 8, 22, s_time_val, key=f"fs_{ft}")
        fe_t = st.number_input(f"{ft} 퇴근", 9, 23, e_time_val, key=f"fe_{ft}")
        # ⭐ 에러가 났던 줄: 이제 무조건 선언된 변수만 사용함
        f_lunch = st.selectbox(f"{ft} 점심조", group_labels, index=group_labels.index(l_group_val) if l_group_val in group_labels else 0, key=f"fl_{ft}")
        f_dinner = st.selectbox(f"{ft} 저녁조", group_labels, index=group_labels.index(d_group_val) if d_group_val in group_labels else 0, key=f"fd_{ft}")
        ft_settings[ft] = {"start": fs_t, "end": fe_t, "meals": [lunch_configs[f_lunch], dinner_configs[f_dinner]]}

pt_settings = {}
for i, pt in enumerate(working_pt):
    ps_v, pe_v, pm_v, pc_v = 10, 20, '13:00', False
    person_match = store_data[store_data['이름'] == pt]
    if not person_match.empty:
        r = person_match.iloc[0]
        try:
            ps_v = int(float(r.get('출근시간', 10)))
            pe_v = int(float(r.get('퇴근시간', 20)))
        except: pass
        pm_v = str(r.get('식사시간', '13:00')) if r.get('식사시간') else '13:00'
        pc_v = str(r.get('카운터여부','X')).upper() in ['O', 'Y']
    with st.sidebar.expander(f"📌 {pt} (파트타이머)"):
        ps_t = st.number_input(f"{pt} 출근", 8, 22, ps_v, key=f"ps_{pt}")
        pe_t = st.number_input(f"{pt} 퇴근", 9, 23, pe_v, key=f"pe_{pt}")
        t_list = [f"{h}:00" for h in range(8, 23)]
        pm_t = st.selectbox(f"{pt} 식사", t_list, index=t_list.index(pm_v) if pm_v in t_list else 5, key=f"pm_{pt}")
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=pc_v, key=f"pc_{pt}")
        pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t, "can_counter": can_counter}

# 6. 로테이션 알고리즘 (2시간 연속 금지 철저 유지)
def generate_v42():
    time_slots = [f"{h}:00" for h in range(8, 23)]
    manager_names = working_ft + working_pt
    matrix = {name: {slot: "-" for slot in time_slots} for name in manager_names}
    last_zone_map = {name: None for name in manager_names}

    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        ft_w = [f for f in working_ft if ft_settings[f]["start"] <= curr_h < ft_settings[f]["end"]]
        pt_w = [p for p in working_pt if pt_settings[p]["start"] <= curr_h < pt_settings[p]["end"]]
        
        for f in ft_w:
            if slot in ft_settings[f]["meals"]: matrix[f][slot] = "🍴식사"
        for p in pt_w:
            if slot == pt_settings[p]["meal"]: matrix[p][slot] = "🍴식사"
            
        pool = [p for p in manager_names if matrix[p][slot] == "-"]
        random.shuffle(pool)
        
        for z in target_zones:
            max_to = zone_to_map[z]
            for _ in range(max_to):
                if not pool: break
                candidates = [p for p in pool if last_zone_map[p] != z]
                choice = random.choice(candidates if candidates else pool)
                if z == target_zones[0]:
                    skilled = [p for p in (candidates if candidates else pool) if p in working_ft or pt_settings[p]["can_counter"]]
                    if skilled: choice = random.choice(skilled)

                matrix[choice][slot] = z
                pool.remove(choice)
                last_zone_map[choice] = z
        
        for p in pool: 
            matrix[p][slot] = "📢지원"
            last_zone_map[p] = "📢지원"

    final_df = pd.DataFrame.from_dict(matrix, orient='index')
    return final_df.loc[:, (final_df != "-").any(axis=0)]

if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df_v42 = generate_v42()

if 'df_v42' in st.session_state:
    st.subheader(f"📊 {selected_store} 스케줄표 (가로형)")
    st.data_editor(st.session_state.df_v42, use_container_width=True, height=600)
