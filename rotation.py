import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v53.0)")

# 💡 관리자님의 실제 시트 ID 입력
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
SHEET_NAME = "Sheet1" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        if df.empty: return pd.DataFrame()
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
zone_col = '운영구역' if '운영구역' in store_data.columns else (store_data.columns[-1] if len(store_data.columns) > 1 else '운영구역')
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty and zone_col in store_data.columns else "카운터(1), A(1)"
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
    if data.empty: return []
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    if not type_col or not name_col:
        try: name_col = data.columns[1]; type_col = data.columns[2]
        except: return []
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [n.replace('.0', '') for n in filtered[name_col].dropna().tolist() if n != 'None']

ft_names = extract_names(store_data, '정직'); pt_names = extract_names(store_data, '파트')
working_ft = st.sidebar.multiselect("✅ 오늘 출근 정직원", ft_names, default=ft_names)
working_pt = st.sidebar.multiselect("✅ 오늘 출근 파트타이머", pt_names, default=pt_names)

# 4. 상세 스케줄 설정
group_labels = ["A", "B", "C", "D", "E"]
all_time_slots = [f"{h}:00" for h in range(8, 23)]
lunch_configs = {}; dinner_configs = {}

with st.sidebar.expander("🍴 식사 조별 시간 설정"):
    for label in group_labels:
        lunch_configs[label] = st.selectbox(f"점심 {label}조", all_time_slots, index=4, key=f"L_{label}")
        dinner_configs[label] = st.selectbox(f"저녁 {label}조", all_time_slots, index=10, key=f"D_{label}")

ft_settings = {}
for ft in working_ft:
    match = store_data[store_data[next(c for c in store_data.columns if '이름' in c)] == ft]
    r = match.iloc[0] if not match.empty else {}
    l_v = str(r.get('점심조', 'A')).upper() if r.get('점심조') else 'A'
    d_v = str(r.get('저녁조', 'A')).upper() if r.get('저녁조') else 'A'
    with st.sidebar.expander(f"💼 {ft} (정직원)"):
        fs_t = st.number_input(f"{ft} 출근", 0, 23, int(float(r.get('출근시간', 10))), key=f"fs_{ft}")
        fe_t = st.number_input(f"{ft} 퇴근", 0, 23, int(float(r.get('퇴근시간', 20))), key=f"fe_{ft}")
        f_lunch = st.selectbox(f"{ft} 점심조", group_labels, index=group_labels.index(l_v) if l_v in group_labels else 0, key=f"fl_{ft}")
        f_dinner = st.selectbox(f"{ft} 저녁조", group_labels, index=group_labels.index(d_v) if d_v in group_labels else 0, key=f"fd_{ft}")
        ft_settings[ft] = {"start": fs_t, "end": fe_t, "meals": [lunch_configs[f_lunch], dinner_configs[f_dinner]]}

pt_settings = {}
for pt in working_pt:
    match = store_data[store_data[next(c for c in store_data.columns if '이름' in c)] == pt]
    r = match.iloc[0] if not match.empty else {}
    ps_v = int(float(r.get('출근시간', 10))) if r.get('출근시간') else 10
    pe_v = int(float(r.get('퇴근시간', 20))) if r.get('퇴근시간') else 20
    pm_v = str(r.get('식사시간', '13:00'))
    with st.sidebar.expander(f"📌 {pt} (파트타이머)"):
        ps_pt = st.number_input(f"{pt} 출근", 0, 23, ps_v, key=f"ps_val_{pt}")
        pe_pt = st.number_input(f"{pt} 퇴근", 0, 23, pe_v, key=f"pe_val_{pt}")
        pm_idx = all_time_slots.index(pm_v) if pm_v in all_time_slots else 5
        pm_pt = st.selectbox(f"{pt} 식사", all_time_slots, index=pm_idx, key=f"pm_val_{pt}")
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=str(r.get('카운터여부','X')).upper() in ['O', 'Y'], key=f"pc_val_{pt}")
        pt_settings[pt] = {"start": ps_pt, "end": pe_pt, "meal": pm_pt, "can_counter": can_counter}

# 5. 로테이션 알고리즘 (v52.0 유지)
def generate_v53():
    slots = [f"{h}:00" for h in range(8, 23)]
    names = working_ft + working_pt
    matrix = {n: {s: "-" for s in slots} for n in names}
    last_z = {n: None for n in names}

    for s in slots:
        curr_h = int(s.split(":")[0])
        active_now = []
        for n in names:
            if n in ft_settings:
                if ft_settings[n]["start"] <= curr_h < ft_settings[n]["end"]:
                    if s in ft_settings[n]["meals"]: matrix[n][s] = "🍴식사"
                    else: active_now.append(n)
            elif n in pt_settings:
                if pt_settings[n]["start"] <= curr_h < pt_settings[n]["end"]:
                    if s == pt_settings[n]["meal"]: matrix[n][s] = "🍴식사"
                    else: active_now.append(n)

        pool = active_now.copy()
        random.shuffle(pool)
        for z in target_zones:
            max_to = zone_to_map[z]
            for _ in range(max_to):
                if not pool: break
                cands = [m for m in pool if last_z[m] != z]
                choice = random.choice(cands if cands else pool)
                if z == target_zones[0]:
                    skilled = [m for m in (cands if cands else pool) if m in working_ft or pt_settings.get(m, {}).get("can_counter", False)]
                    if skilled: choice = random.choice(skilled)
                matrix[choice][s] = z
                pool.remove(choice); last_z[choice] = z
        for m in pool: 
            matrix[m][s] = "📢지원"; last_z[m] = "📢지원"

    return pd.DataFrame.from_dict(matrix, orient='index').loc[:, (pd.DataFrame.from_dict(matrix, orient='index') != "-").any(axis=0)]

# 6. 실행 및 결과 (수정 기능 복구)
if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df_v53 = generate_v53()

if 'df_v53' in st.session_state:
    st.subheader(f"📊 {selected_store} 스케줄 (칸을 더블클릭하여 수정 가능)")
    
    # ⭐ st.data_editor를 사용하여 수정 기능 복구
    # 스타일링(색상)은 데이터 에디터에서 직접 지원하지 않으므로, 
    # 가독성을 위해 '🍴식사' 등의 텍스트는 유지됩니다.
    edited_df = st.data_editor(
        st.session_state.df_v53, 
        use_container_width=True, 
        height=600
    )
    
    # (선택사항) 최종 확정된 표를 색상과 함께 보고 싶을 때를 위한 토글
    if st.checkbox("🎨 색상 강조 보기 (수정 불가 모드)"):
        def apply_styles(val):
            if val == "🍴식사": return 'background-color: #FFFF00; color: black; font-weight: bold'
            if val == "📢지원": return 'color: #00FF00; font-weight: bold'
            return ''
        def row_styles(row):
            if row.name in working_ft: return ['background-color: #1A1A1A; color: white'] * len(row)
            return [''] * len(row)
        
        st.table(edited_df.style.apply(row_styles, axis=1).applymap(apply_styles))
