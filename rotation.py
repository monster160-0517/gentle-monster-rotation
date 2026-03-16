import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v67.1")

# 💡 구글 시트 정보 (공개 설정 필수)
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q"
# [중요] '시간대별TO' 시트의 gid 숫자를 확인하여 여기에 넣으세요.
TO_SHEET_GID = "2126973547" 

@st.cache_data(ttl=1)
def load_sheet_data(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        if df.empty: return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        df = df.astype(str).replace(r'\.0$', '', regex=True).replace(['nan', 'None', 'nan.0'], '')
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패 (GID: {gid}): {e}")
        return pd.DataFrame()

def parse_time_value(val):
    try:
        if not val or val == '': return 0
        if '-' in str(val): return int(float(str(val).split('-')[0]))
        return int(float(str(val)))
    except: return 0

# 데이터 로드
db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty or to_df.empty:
    st.warning("⚠️ 시트 데이터를 불러오는 중입니다. GID와 공유 설정을 확인해주세요.")
    st.stop()

# --- 사이드바 설정 ---
st.sidebar.header("🕹️ 컨트롤 패널")
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", sorted(db_df['매장명'].unique()))
store_data = db_df[db_df['매장명'] == selected_store].copy()

# 조별 식사 시간 설정
time_options = [f"{h:02d}:00" for h in range(11, 22)]
group_labels = ["A", "B", "C", "D", "E"]
lunch_slots, dinner_slots = {}, {}

with st.sidebar.expander("🍴 조별 식사 시간 설정"):
    for label in group_labels:
        col1, col2 = st.columns(2)
        with col1: lunch_slots[label] = st.selectbox(f"점심 {label}", time_options, index=group_labels.index(label)%len(time_options), key=f"L_{label}")
        with col2: dinner_slots[label] = st.selectbox(f"저녁 {label}", time_options, index=(group_labels.index(label)+5)%len(time_options), key=f"D_{label}")

# 인원 선택
def extract_names(data, keyword):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [str(n).strip() for n in filtered[name_col].dropna().tolist() if n != '']

working_ft = st.sidebar.multiselect("👤 정직원", extract_names(store_data, '정직'), default=extract_names(store_data, '정직'))
working_pt = st.sidebar.multiselect("⏱️ 파트타이머", extract_names(store_data, '파트'), default=extract_names(store_data, '파트'))

# --- 데이터 전처리 ---
combined_settings = {}
for name in working_ft + working_pt:
    r = store_data[store_data['이름'] == name].iloc[0] if not store_data[store_data['이름'] == name].empty else {}
    s_time = parse_time_value(r.get('출근시간', 11))
    e_time = parse_time_value(r.get('퇴근시간', 21))
    if 0 < e_time < 12 and e_time < s_time: e_time += 12
    l_grp, d_grp = str(r.get('점심조', 'A')).strip().upper(), str(r.get('저녁조', 'A')).strip().upper()
    c_raw = str(r.get('카운터여부', 'X')).strip().lower()
    is_c = any(x in c_raw for x in ['o', 'y', '1', 'v', 'true', '예', 'ok'])
    
    combined_settings[name] = {
        "range": range(int(s_time), int(e_time)),
        "meals": [lunch_slots.get(l_grp), dinner_slots.get(d_grp)],
        "can_counter": is_c
    }

generate_btn = st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True)

# 3. 로테이션 엔진
def run_rotation():
    display_times = [f"{h:02d}:00" for h in range(10, 22)]
    all_staff = list(dict.fromkeys([n for n in (working_ft + working_pt) if n.strip() != ""]))
    if not all_staff: return pd.DataFrame()

    schedule_df = pd.DataFrame(index=display_times, columns=all_staff).fillna("-")
    last_positions = {name: "" for name in all_staff}
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    for slot in display_times:
        hour = int(slot.split(":")[0])
        available_pool = []
        for name in all_staff:
            s = combined_settings.get(name)
            if s and hour in s["range"]:
                if slot in s["meals"]: schedule_df.at[slot, name] = "🍴 식사"
                else: available_pool.append(name)
            else: schedule_df.at[slot, name] = " "

        random.shuffle(available_pool)
        current_to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        
        if not current_to_row.empty:
            sorted_zones = sorted(all_zones, key=lambda x: "카운터" not in x)
            for zone in sorted_zones:
                try: needed = int(float(current_to_row[zone].iloc[0]))
                except: needed = 0
                assigned = 0
                eligible = [n for n in available_pool if not ("카운터" in zone and not combined_settings[n]["can_counter"])]
                eligible.sort(key=lambda x: last_positions[name] == zone if name in last_positions else False) # 수정

                for name in eligible:
                    if assigned < needed:
                        schedule_df.at[slot, name] = zone
                        last_positions[name] = zone
                        if name in available_pool: available_pool.remove(name)
                        assigned += 1
        
        for name in available_pool:
            schedule_df.at[slot, name] = "📢 지원"
            last_positions[name] = "📢 지원"
            
    return schedule_df

if generate_btn:
    result = run_rotation()
    if not result.empty: st.session_state.result_df = result

if 'result_df' in st.session_state and not st.session_state.result_df.empty:
    st.write(f"### 📅 [{selected_store}] 로테이션 결과")
    display_df = st.session_state.result_df.copy()
    edited_df = st.data_editor(display_df, use_container_width=True, height=600)
    
    with st.expander("📊 배정 인원 체크"):
        summary = []
        all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
        for slot in edited_df.index:
            row = {"시간": slot}
            current_to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
            for zone in all_zones:
                try: limit = int(float(current_to_row[zone].iloc[0]))
                except: limit = 0
                count = (edited_df.loc[slot] == zone).sum()
                status = f"{count}/{limit}"
                if count < limit: status = f"❌ {status}"
                row[zone] = status
            summary.append(row)
        st.table(pd.DataFrame(summary))
