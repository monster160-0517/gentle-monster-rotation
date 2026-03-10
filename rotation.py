import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v61.0")

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
    st.warning("⚠️ 데이터를 불러올 수 없습니다.")
    st.stop()

db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", sorted(db_df['매장명'].unique()))
store_data = db_df[db_df['매장명'] == selected_store].copy()

# ---------------------------------------------------------
# 2. 구역 및 시간대별 카운터 TO 설정
# ---------------------------------------------------------
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 일반 구역 설정 (구역명(인원))", raw_zones)

# 일반 구역 정보 파싱
zone_to_map = {}
for z_info in zone_input.split(","):
    match = re.search(r"(.+)\((\d+)\)", z_info.strip())
    if match: zone_to_map[match.group(1).strip()] = int(match.group(2))
    else: zone_to_map[z_info.strip()] = 1

# 시간대별 '카운터' TO 설정 (별도 UI)
time_slots = [f"{h:02d}:00" for h in range(10, 22)]
if 'counter_to' not in st.session_state:
    # 기본값은 사이드바에서 설정한 카운터 인원수
    base_counter_limit = zone_to_map.get("카운터", 1)
    st.session_state.counter_to = pd.DataFrame({"카운터TO": [base_counter_limit]*len(time_slots)}, index=time_slots)

st.write("### ⏱️ 시간대별 카운터 필수 인원 설정")
counter_to_df = st.data_editor(st.session_state.counter_to, use_container_width=True)
st.session_state.counter_to = counter_to_df

# ---------------------------------------------------------
# 3. 인원 및 개인 스케줄 설정
# ---------------------------------------------------------
def extract_names(data, keyword):
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    if not type_col or not name_col: return []
    filtered = data[data[type_col].str.contains(keyword, na=False)]
    return [str(n).split('.')[0] for n in filtered[name_col].dropna().tolist() if n != '']

working_ft = st.sidebar.multiselect("정직원", extract_names(store_data, '정직'), default=extract_names(store_data, '정직'))
working_pt = st.sidebar.multiselect("파트타이머", extract_names(store_data, '파트'), default=extract_names(store_data, '파트'))

combined_settings = {}
st.sidebar.subheader("⏱️ 개인별 세부조정")
for name in working_ft + working_pt:
    match = store_data[store_data['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
    def_s = parse_time_value(r.get('출근시간', 11))
    def_e = parse_time_value(r.get('퇴근시간', 21))
    if 0 < def_e < 12 and def_e < def_s: def_e += 12
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y', 'TRUE', '1']
    
    with st.sidebar.expander(f"{name}"):
        s_time = st.number_input(f"출근", 8, 22, def_s, key=f"s_{name}")
        e_time = st.number_input(f"퇴근", 8, 23, def_e, key=f"e_{name}")
        c_auth = st.checkbox("카운터 가능", value=is_c, key=f"auth_{name}")
        # 식사 시간은 예시로 13:00, 18:00 고정 (필요시 조정)
        combined_settings[name] = {
            "range": range(int(s_time), int(e_time)),
            "meals": ["13:00", "14:00", "18:00", "19:00"], # 시트 데이터에 맞춰 조정 필요
            "can_counter": c_auth
        }

# ---------------------------------------------------------
# 4. 로테이션 엔진
# ---------------------------------------------------------
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
                # 간단한 식사 체크 (필요시 상세화)
                available_pool.append(name)
            else:
                schedule_df.at[slot, name] = " "

        random.shuffle(available_pool)
        
        # 1. 카운터 배정 (시간대별 TO 반영)
        counter_needed = int(st.session_state.counter_to.at[slot, "카운터TO"])
        counter_assigned = 0
        eligible_counter = [n for n in available_pool if combined_settings[n]["can_counter"]]
        
        for name in eligible_counter:
            if counter_assigned < counter_needed:
                schedule_df.at[slot, name] = "카운터"
                last_positions[name] = "카운터"
                available_pool.remove(name)
                counter_assigned += 1

        # 2. 기타 일반 구역 배정 (고정 TO)
        other_zones = [z for z in zone_to_map.keys() if z != "카운터"]
        for zone in other_zones:
            needed = zone_to_map[zone]
            assigned = 0
            for name in list(available_pool):
                if assigned < needed:
                    schedule_df.at[slot, name] = zone
                    last_positions[name] = zone
                    available_pool.remove(name)
                    assigned += 1

        # 3. 남은 인원 지원
        for name in available_pool:
            schedule_df.at[slot, name] = "📢지원"
            last_positions[name] = "📢지원"
            
    return schedule_df

if st.sidebar.button("🚀 로테이션 자동 생성"):
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    st.data_editor(st.session_state.result_df, use_container_width=True)
