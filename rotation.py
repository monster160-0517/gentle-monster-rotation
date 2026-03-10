import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v62.0")

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

# --- 사이드바 설정 시작 ---
st.sidebar.header("🕹️ 컨트롤 패널")

# 매장 선택
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", sorted(db_df['매장명'].unique()))
store_data = db_df[db_df['매장명'] == selected_store].copy()

# 일반 구역 설정
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 일반 구역 설정 (구역명(인원))", raw_zones)

zone_to_map = {}
for z_info in zone_input.split(","):
    match = re.search(r"(.+)\((\d+)\)", z_info.strip())
    if match: zone_to_map[match.group(1).strip()] = int(match.group(2))
    else: zone_to_map[z_info.strip()] = 1

# 🕒 시간대별 카운터 TO 설정 (사이드바로 이동)
time_slots = [f"{h:02d}:00" for h in range(10, 22)]
with st.sidebar.expander("⏱️ 시간대별 카운터 TO 설정"):
    if 'counter_to' not in st.session_state:
        base_counter_limit = zone_to_map.get("카운터", 1)
        st.session_state.counter_to = pd.DataFrame({"카운터TO": [base_counter_limit]*len(time_slots)}, index=time_slots)
    
    counter_to_df = st.data_editor(st.session_state.counter_to, use_container_width=True)
    st.session_state.counter_to = counter_to_df

# 인원 선택
def extract_names(data, keyword):
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    if not type_col or not name_col: return []
    filtered = data[data[type_col].str.contains(keyword, na=False)]
    return [str(n).split('.')[0] for n in filtered[name_col].dropna().tolist() if n != '']

working_ft = st.sidebar.multiselect("👤 정직원 선택", extract_names(store_data, '정직'), default=extract_names(store_data, '정직'))
working_pt = st.sidebar.multiselect("⏱️ 파트타이머 선택", extract_names(store_data, '파트'), default=extract_names(store_data, '파트'))

# 개인별 세부조정
combined_settings = {}
st.sidebar.subheader("⚙️ 개인별 스케줄 조정")
for name in working_ft + working_pt:
    match = store_data[store_data[next((c for c in store_data.columns if '이름' in c), '이름')] == name]
    r = match.iloc[0] if not match.empty else {}
    def_s = parse_time_value(r.get('출근시간', 11))
    def_e = parse_time_value(r.get('퇴근시간', 21))
    if 0 < def_e < 12 and def_e < def_s: def_e += 12
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y', 'TRUE', '1']
    
    with st.sidebar.expander(f"{name}"):
        col1, col2 = st.columns(2)
        with col1: s_time = st.number_input(f"출근", 8, 22, def_s, key=f"s_{name}")
        with col2: e_time = st.number_input(f"퇴근", 8, 23, def_e, key=f"e_{name}")
        c_auth = st.checkbox("카운터 가능", value=is_c, key=f"auth_{name}")
        
        combined_settings[name] = {
            "range": range(int(s_time), int(e_time)),
            "meals": ["13:00", "14:00", "18:00", "19:00"], 
            "can_counter": c_auth
        }

# 생성 버튼
generate_btn = st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True)
# --- 사이드바 설정 끝 ---

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
                available_pool.append(name)
            else:
                schedule_df.at[slot, name] = " "

        random.shuffle(available_pool)
        
        # 1. 카운터 배정 (시간대별 가변 TO 반영)
        counter_needed = int(st.session_state.counter_to.at[slot, "카운터TO"])
        counter_assigned = 0
        eligible_counter = [n for n in available_pool if combined_settings[n]["can_counter"]]
        
        for name in eligible_counter:
            if counter_assigned < counter_needed:
                schedule_df.at[slot, name] = "카운터"
                last_positions[name] = "카운터"
                available_pool.remove(name)
                counter_assigned += 1

        # 2. 기타 일반 구역 배정
        other_zones = [z for z in zone_to_map.keys() if z != "카운터"]
        for zone in other_zones:
            needed = zone_to_map[zone]
            assigned = 0
            # 직전 구역이 아닌 사람 우선 배정
            available_pool.sort(key=lambda x: last_positions[x] == zone)
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

if generate_btn:
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    st.info("💡 표의 셀을 더블클릭하여 내용을 직접 수정할 수 있습니다.")
    edited_df = st.data_editor(st.session_state.result_df, use_container_width=True, height=600)
    
    # 배정 현황 확인용 (하단)
    with st.expander("📊 실시간 배정 인원 체크"):
        summary_list = []
        for slot in edited_df.index:
            row_sum = {"시간": slot}
            for zone in list(zone_to_map.keys()):
                count = (edited_df.loc[slot] == zone).sum()
                limit = int(st.session_state.counter_to.at[slot, "카운터TO"]) if zone == "카운터" else zone_to_map[zone]
                row_sum[zone] = f"{count}/{limit}"
            summary_list.append(row_sum)
        st.table(pd.DataFrame(summary_list))
