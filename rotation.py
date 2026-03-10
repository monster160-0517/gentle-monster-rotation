import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v63.0")

# 💡 실시간 구글 시트 데이터 로드
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        if df.empty: return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        df = df.astype(str).replace(['nan', 'None', 'nan.0'], '')
        return df
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame()

def parse_time_value(val):
    try:
        if not val or val == '': return 0
        if '-' in str(val): return int(float(str(val).split('-')[0]))
        return int(float(str(val).replace('.0', '')))
    except: return 0

db_df = load_db()
if db_df.empty:
    st.stop()

# --- 사이드바 설정 ---
st.sidebar.header("🕹️ 컨트롤 패널")

# 1. 매장 및 구역 설정
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", sorted(db_df['매장명'].unique()))
store_data = db_df[db_df['매장명'] == selected_store].copy()

zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 일반 구역 설정 (구역명(인원))", raw_zones)

zone_to_map = {}
for z_info in zone_input.split(","):
    match = re.search(r"(.+)\((\d+)\)", z_info.strip())
    if match: zone_to_map[match.group(1).strip()] = int(match.group(2))
    else: zone_to_map[z_info.strip()] = 1

# 2. [복구] 조별 식사 시간 설정
st.sidebar.subheader("🍴 조별 식사 시간 설정")
time_options = [f"{h:02d}:00" for h in range(11, 22)]
group_labels = ["A", "B", "C", "D", "E"]
lunch_slots = {}
dinner_slots = {}

with st.sidebar.expander("🍔 점심/저녁 시간대 지정"):
    for label in group_labels:
        col1, col2 = st.columns(2)
        with col1:
            lunch_slots[label] = st.selectbox(f"점심 {label}", time_options, index=group_labels.index(label) if label in group_labels else 0)
        with col2:
            dinner_slots[label] = st.selectbox(f"저녁 {label}", time_options, index=group_labels.index(label)+5 if group_labels.index(label)+5 < len(time_options) else 0)

# 3. 시간대별 카운터 TO 설정
time_slots = [f"{h:02d}:00" for h in range(10, 22)]
with st.sidebar.expander("⏱️ 시간대별 카운터 TO 설정"):
    if 'counter_to' not in st.session_state:
        base_cnt = zone_to_map.get("카운터", 1)
        st.session_state.counter_to = pd.DataFrame({"카운터TO": [base_cnt]*len(time_slots)}, index=time_slots)
    st.session_state.counter_to = st.data_editor(st.session_state.counter_to, use_container_width=True)

# 4. 인원 선택
def extract_names(data, keyword):
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    if not type_col or not name_col: return []
    filtered = data[data[type_col].str.contains(keyword, na=False)]
    return [str(n).split('.')[0] for n in filtered[name_col].dropna().tolist() if n != '']

working_ft = st.sidebar.multiselect("👤 정직원", extract_names(store_data, '정직'), default=extract_names(store_data, '정직'))
working_pt = st.sidebar.multiselect("⏱️ 파트타이머", extract_names(store_data, '파트'), default=extract_names(store_data, '파트'))

# --- 로테이션 데이터 준비 (개인별 스케줄은 시트 데이터 기준 자동 연산) ---
combined_settings = {}
for name in working_ft + working_pt:
    match = store_data[store_data[next((c for c in store_data.columns if '이름' in c), '이름')] == name]
    r = match.iloc[0] if not match.empty else {}
    
    # 시트에서 직접 가져오는 값들
    s_time = parse_time_value(r.get('출근시간', 11))
    e_time = parse_time_value(r.get('퇴근시간', 21))
    if 0 < e_time < 12 and e_time < s_time: e_time += 12
    
    l_grp = str(r.get('점심조', 'A')).strip().upper()
    d_grp = str(r.get('저녁조', 'A')).strip().upper()
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y', 'TRUE', '1']
    
    combined_settings[name] = {
        "range": range(int(s_time), int(e_time)),
        "meals": [lunch_slots.get(l_grp, "13:00"), dinner_slots.get(d_grp, "18:00")],
        "can_counter": is_c
    }

generate_btn = st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True)

# 5. 로테이션 엔진
def run_rotation():
    all_staff = working_ft + working_pt
    schedule_df = pd.DataFrame(index=time_slots, columns=all_staff).fillna("-")
    last_positions = {name: "" for name in all_staff}
    
    for slot in time_slots:
        hour = int(slot.split(":")[0])
        available_pool = []
        
        for name in all_staff:
            s = combined_settings[name]
            if hour in s["range"]:
                if slot in s["meals"]:
                    schedule_df.at[slot, name] = "🍴식사"
                else:
                    available_pool.append(name)
            else:
                schedule_df.at[slot, name] = " "

        random.shuffle(available_pool)
        
        # 1. 카운터 우선 배정
        cnt_needed = int(st.session_state.counter_to.at[slot, "카운터TO"])
        cnt_assigned = 0
        eligible_cnt = [n for n in available_pool if combined_settings[n]["can_counter"]]
        
        for name in eligible_cnt:
            if cnt_assigned < cnt_needed:
                schedule_df.at[slot, name] = "카운터"
                last_positions[name] = "카운터"
                available_pool.remove(name)
                cnt_assigned += 1

        # 2. 일반 구역 배정
        other_zones = [z for z in zone_to_map.keys() if z != "카운터"]
        for zone in other_zones:
            needed = zone_to_map[zone]
            assigned = 0
            available_pool.sort(key=lambda x: last_positions[x] == zone)
            for name in list(available_pool):
                if assigned < needed:
                    schedule_df.at[slot, name] = zone
                    last_positions[name] = zone
                    available_pool.remove(name)
                    assigned += 1

        # 3. 지원 배정
        for name in available_pool:
            schedule_df.at[slot, name] = "📢지원"
            last_positions[name] = "📢지원"
            
    return schedule_df

if generate_btn:
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    st.data_editor(st.session_state.result_df, use_container_width=True, height=600)
    
    with st.expander("📊 배정 인원 실시간 체크"):
        summary = []
        for slot in st.session_state.result_df.index:
            row = {"시간": slot}
            for zone, limit in zone_to_map.items():
                cur_limit = int(st.session_state.counter_to.at[slot, "카운터TO"]) if zone == "카운터" else limit
                count = (st.session_state.result_df.loc[slot] == zone).sum()
                row[zone] = f"{count}/{cur_limit}"
            summary.append(row)
        st.table(pd.DataFrame(summary))
