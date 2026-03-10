import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정 및 데이터 로딩
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v35.0)")

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

# 4. 식사 시간 설정 (v34.0과 동일)
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}; dinner_configs = {}
with st.sidebar.expander("🕛 식사 조별 시간 설정"):
    for label in group_labels:
        lunch_configs[label] = st.selectbox(f"점심 {label}조", [f"{h}:00" for h in range(11, 17)], index=group_labels.index(label), key=f"L_{label}")
        dinner_configs[label] = st.selectbox(f"저녁 {label}조", [f"{h}:00" for h in range(17, 22)], index=group_labels.index(label), key=f"D_{label}")

# 5. 개인별 스케줄 로드
ft_settings = {}
for i, ft in enumerate(working_ft):
    row = store_data[store_data['이름'] == ft].iloc[0] if not store_data[store_data['이름'] == ft].empty else {}
    l_grp = str(row.get('점심조', 'A')).upper() if row.get('점심조') else 'A'
    d_grp = str(row.get('저녁조', 'A')).upper() if row.get('저녁조') else 'A'
    ft_settings[ft] = {
        "start": int(float(row.get('출근시간', 10))) if row.get('출근시간') else 10,
        "end": int(float(row.get('퇴근시간', 20))) if row.get('퇴근시간') else 20,
        "meals": [lunch_configs.get(l_grp, "12:00"), dinner_configs.get(d_grp, "18:00")]
    }

pt_settings = {}
for i, pt in enumerate(working_pt):
    row = store_data[store_data['이름'] == pt].iloc[0] if not store_data[store_data['이름'] == pt].empty else {}
    pt_settings[pt] = {
        "start": int(float(row.get('출근시간', 10))) if row.get('출근시간') else 10,
        "end": int(float(row.get('퇴근시간', 20))) if row.get('퇴근시간') else 20,
        "meal": str(row.get('식사시간', '13:00')),
        "can_counter": str(row.get('카운터여부', 'X')).upper() in ['O', 'Y']
    }

# 6. [업데이트] X방지 최우선 알고리즘
def generate_v35():
    time_slots = [f"{h}:00" for h in range(8, 23)]
    final_rows = []; zone_history = {z: [] for z in target_zones}
    
    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        eating = [f for f in working_ft if slot in ft_settings[f]["meals"]] + [p for p in working_pt if slot == pt_settings[p]["meal"]]
        ft_working = [f for f in working_ft if ft_settings[f]["start"] <= curr_h < ft_settings[f]["end"] and slot not in ft_settings[f]["meals"]]
        pt_working = [p for p in working_pt if pt_settings[p]["start"] <= curr_h < pt_settings[p]["end"] and slot != pt_settings[p]["meal"]]
        
        if not ft_working and not pt_working and not eating: continue
        
        row = {"시간": slot, "🍴 식사중": ", ".join(eating) if eating else "-"}
        pool = ft_working + pt_working; random.shuffle(pool)
        
        # 카운터 우선 풀
        counter_pool = [p for p in pool if p in ft_working or pt_settings.get(p, {}).get("can_counter", False)]
        
        assign = {z: [] for z in target_zones}

        # [1단계] 모든 구역에 최소 1명씩 배정 (X 방지)
        for z in target_zones:
            if not pool: break
            chosen = None
            if z == target_zones[0] and counter_pool:
                chosen = counter_pool.pop(0)
            else:
                valid = [p for p in pool if p not in zone_history[z]]
                chosen = random.choice(valid if valid else pool)
            
            if chosen:
                assign[z].append(chosen)
                pool.remove(chosen)
                if chosen in counter_pool: counter_pool.remove(chosen)

        # [2단계] 남은 인원을 TO 숫자에 맞춰 추가 배정
        for z in target_zones:
            max_to = zone_to_map[z]
            while len(assign[z]) < max_to and pool:
                valid = [p for p in pool if p not in zone_history[z]]
                chosen = random.choice(valid if valid else pool)
                assign[z].append(chosen)
                pool.remove(chosen)

        # [3단계] 여전히 남은 인원은 지원/휴식
        row["📢 지원/휴식"] = ", ".join(pool) if pool else "-"
        
        for z in target_zones:
            row[z] = ", ".join(assign[z]) if assign[z] else "X"
            zone_history[z] = (assign[z] + zone_history[z])[:5] # 최근 기록 업데이트
            
        final_rows.append(row)
    return pd.DataFrame(final_rows)

if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df = generate_v35()

if 'df' in st.session_state:
    st.subheader(f"📊 {selected_store} 로테이션 결과")
    cols = ["시간", "🍴 식사중", "📢 지원/휴식"] + target_zones
    st.data_editor(st.session_state.df[cols], use_container_width=True)
