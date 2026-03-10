import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v41.0)")

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

# 3. 인원 추출 및 선택
def extract_names(data, keyword):
    type_col = '구분' if '구분' in data.columns else data.columns[2]
    name_col = '이름' if '이름' in data.columns else data.columns[1]
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [n.replace('.0', '') if n.endswith('.0') else n for n in filtered[name_col].dropna().tolist() if n != 'None']

all_ft = extract_names(store_data, '정직'); all_pt = extract_names(store_data, '파트')
working_ft = st.sidebar.multiselect("✅ 오늘 출근 정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("✅ 오늘 출근 파트타이머", all_pt, default=all_pt)

# 4. 식사 및 개인 설정 (사이드바 메뉴 유지)
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}; dinner_configs = {}
with st.sidebar.expander("🕛 식사 조별 시간 설정"):
    for label in group_labels:
        lunch_configs[label] = st.selectbox(f"점심 {label}조", [f"{h}:00" for h in range(11, 17)], index=group_labels.index(label), key=f"L_{label}")
        dinner_configs[label] = st.selectbox(f"저녁 {label}조", [f"{h}:00" for h in range(17, 22)], index=group_labels.index(label), key=f"D_{label}")

ft_settings = {}
for i, ft in enumerate(working_ft):
    row = store_data[store_data['이름'] == ft].iloc[0] if not store_data[store_data['이름'] == ft].empty else {}
    l_grp = str(row.get('점심조', 'A')).upper() if row.get('점심조') else 'A'
    d_grp = str(row.get('저녁조', 'A')).upper() if row.get('저녁조') else 'A'
    with st.sidebar.expander(f"💼 {ft} (정직원)"):
        fs_t = st.number_input(f"{ft} 출근", 8, 22, int(float(row.get('출근시간', 10))), key=f"fs_{ft}")
        fe_t = st.number_input(f"{ft} 퇴근", 9, 23, int(float(row.get('퇴근시간', 20))), key=f"fe_{ft}")
        f_lunch = st.selectbox(f"{ft} 점심조", group_labels, index=group_labels.index(l_grp) if l_grp in group_labels else 0, key=f"fl_{ft}")
        f_dinner = st.selectbox(f"{ft} 저녁조", group_labels, index=group_labels.index(d_group) if d_group in group_labels else 0, key=f"fd_{ft}")
        ft_settings[ft] = {"start": fs_t, "end": fe_t, "meals": [lunch_configs[f_lunch], dinner_configs[f_dinner]]}

pt_settings = {}
for i, pt in enumerate(working_pt):
    row = store_data[store_data['이름'] == pt].iloc[0] if not store_data[store_data['이름'] == pt].empty else {}
    with st.sidebar.expander(f"📌 {pt} (파트타이머)"):
        ps_t = st.number_input(f"{pt} 출근", 8, 22, int(float(row.get('출근시간', 10))), key=f"ps_{pt}")
        pe_t = st.number_input(f"{pt} 퇴근", 9, 23, int(float(row.get('퇴근시간', 20))), key=f"pe_{pt}")
        time_list = [f"{h}:00" for h in range(8, 23)]
        pm_t = st.selectbox(f"{pt} 식사", time_list, index=time_list.index(str(row.get('식사시간', '13:00'))) if str(row.get('식사시간', '13:00')) in time_list else 5, key=f"pm_{pt}")
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=str(row.get('카운터여부','X')).upper() in ['O', 'Y'], key=f"pc_{pt}")
        pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t, "can_counter": can_counter}

# 5. [강화] 로테이션 알고리즘 (2시간 연속 금지 철저 적용)
def generate_v41():
    time_slots = [f"{h}:00" for h in range(8, 23)]
    manager_names = working_ft + working_pt
    matrix = {name: {slot: "-" for slot in time_slots} for name in manager_names}
    
    # 각 매니저별 직전 시간 구역 기록 (2시간 연속 방지용)
    last_zone_map = {name: None for name in manager_names}

    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        ft_working = [f for f in working_ft if ft_settings[f]["start"] <= curr_h < ft_settings[f]["end"]]
        pt_working = [p for p in working_pt if pt_settings[p]["start"] <= curr_h < pt_settings[p]["end"]]
        
        # 1. 식사 상태 업데이트
        for f in ft_working:
            if slot in ft_settings[f]["meals"]: matrix[f][slot] = "🍴식사"
        for p in pt_working:
            if slot == pt_settings[p]["meal"]: matrix[p][slot] = "🍴식사"
            
        # 2. 가용 인원 확보
        pool = [p for p in manager_names if matrix[p][slot] == "-"] # 아직 배정 안 된 사람
        random.shuffle(pool)
        
        # 3. 구역별 배정 (우선순위 순서대로)
        for z in target_zones:
            max_to = zone_to_map[z]
            for _ in range(max_to):
                if not pool: break
                
                # ⭐ 연속 근무 방지 로직: 직전 구역과 다른 사람 중에서 선택
                candidates = [p for p in pool if last_zone_map[p] != z]
                
                # 만약 모두가 직전 구역이었다면(극히 드문 경우) 어쩔 수 없이 전체 풀에서 선택
                final_choice = random.choice(candidates if candidates else pool)
                
                # 첫 구역(카운터) 숙련도 고려 (가능한 사람이 있을 때만)
                if z == target_zones[0]:
                    skilled = [p for p in candidates if p in working_ft or pt_settings[p]["can_counter"]]
                    if skilled: final_choice = random.choice(skilled)

                matrix[final_choice][slot] = z
                pool.remove(final_choice)
        
        # 4. 남은 인원 지원/휴식
        for p in pool:
            matrix[p][slot] = "📢지원"
            
        # 5. [중요] 다음 타임을 위해 직전 구역 기록 업데이트
        for name in manager_names:
            last_zone_map[name] = matrix[name][slot]

    final_df = pd.DataFrame.from_dict(matrix, orient='index')
    return final_df.loc[:, (final_df != "-").any(axis=0)]

if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df_v41 = generate_v41()

if 'df_v41' in st.session_state:
    st.subheader(f"📊 {selected_store} 매니저별 스케줄")
    st.data_editor(st.session_state.df_v41, use_container_width=True, height=600)
