import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v58.0")

# 💡 실시간 구글 시트 데이터 로드
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        if df.empty: return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        # 모든 데이터를 문자열로 변환 후 공백 제거
        df = df.astype(str).replace(['nan', 'None', 'nan.0'], '')
        return df
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame()

# 시간 변환 함수: "12-17" 또는 "12" 등 다양한 형식 대응
def parse_time_value(val):
    try:
        if not val or val == '': return 0
        # "12-17" 형태인 경우 앞의 숫자만 추출 (출근시간용)
        if '-' in str(val):
            return int(float(str(val).split('-')[0]))
        # 일반적인 숫자 형태
        return int(float(str(val).replace('.0', '')))
    except:
        return 0

db_df = load_db()
if db_df.empty:
    st.warning("⚠️ 데이터를 불러올 수 없습니다.")
    st.stop()

# 2. 매장 및 구역 설정
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
store_list = sorted([s for s in db_df['매장명'].unique() if s and s != ''])
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", store_list)
store_data = db_df[db_df['매장명'] == selected_store].copy()

zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 구역 설정 (구역명(인원))", raw_zones)

zone_to_map = {}
for z_info in zone_input.split(","):
    z_info = z_info.strip()
    match = re.search(r"(.+)\((\d+)\)", z_info)
    if match: 
        zone_to_map[match.group(1).strip()] = int(match.group(2))
    else: 
        zone_to_map[z_info] = 1
target_zones = list(zone_to_map.keys())

# 3. 인원 추출
def extract_names(data, keyword):
    if data.empty: return []
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    if not type_col or not name_col: return []
    filtered = data[data[type_col].str.contains(keyword, na=False)]
    return [str(n).split('.')[0] for n in filtered[name_col].dropna().tolist() if n != '']

all_ft = extract_names(store_data, '정직')
all_pt = extract_names(store_data, '파트')

st.sidebar.subheader("👥 인원 선택")
working_ft = st.sidebar.multiselect("정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("파트타이머", all_pt, default=all_pt)

# 4. 공통 식사 시간 및 개인별 세부 설정
all_time_slots = [f"{h:02d}:00" for h in range(10, 23)]
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}
dinner_configs = {}

with st.sidebar.expander("🍴 공통 식사 시간대 설정"):
    for label in group_labels:
        col_l, col_r = st.columns(2)
        with col_l: lunch_configs[label] = st.selectbox(f"점심 {label}", all_time_slots, index=3, key=f"L_cfg_{label}")
        with col_r: dinner_configs[label] = st.selectbox(f"저녁 {label}", all_time_slots, index=8, key=f"D_cfg_{label}")

combined_settings = {}
st.sidebar.subheader("⏱️ 개인별 스케줄 세부조정")

for name in working_ft + working_pt:
    is_ft = name in working_ft
    name_col = next((c for c in store_data.columns if '이름' in c), '이름')
    match = store_data[store_data[name_col] == name]
    r = match.iloc[0] if not match.empty else {}
    
    # 시간 파싱 로직 (시트 데이터 기반)
    # 파트타이머의 경우 '출근시간' 열에 '13-21' 이런 식으로 적혀있을 가능성 대비
    raw_start = r.get('출근시간', '11')
    raw_end = r.get('퇴근시간', '21')
    
    # 만약 한 컬럼에 "13-21" 처럼 되어 있다면 분리
    if '-' in str(raw_start):
        parts = str(raw_start).split('-')
        def_s = parse_time_value(parts[0])
        def_e = parse_time_value(parts[1])
    else:
        def_s = parse_time_value(raw_start)
        def_e = parse_time_value(raw_end)

    # 오후 시간 보정 (8, 9시 등을 20, 21시로)
    if def_e > 0 and def_e < 12 and def_e < def_s: def_e += 12

    l_grp = str(r.get('점심조', 'A')).strip().upper()
    d_grp = str(r.get('저녁조', 'A')).upper()
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y', 'TRUE']
    fixed_meal = str(r.get('식사시간', '')).strip()

    with st.sidebar.expander(f"{'👤' if is_ft else '⏱️'} {name}"):
        col1, col2 = st.columns(2)
        with col1: s_time = st.number_input(f"출근", 8, 22, def_s, key=f"s_in_{name}")
        with col2: e_time = st.number_input(f"퇴근", 9, 23, def_e, key=f"e_in_{name}")
        
        l_choice = st.selectbox(f"점심조", group_labels, index=group_labels.index(l_grp) if l_grp in group_labels else 0, key=f"lc_{name}")
        d_choice = st.selectbox(f"저녁조", group_labels, index=group_labels.index(d_grp) if d_grp in group_labels else 0, key=f"dc_{name}")
        c_auth = st.checkbox("카운터 가능", value=is_c, key=f"auth_{name}")
        
        my_meals = [lunch_configs[l_choice], dinner_configs[d_choice]]
        if not is_ft and ":" in fixed_meal: # 파트타이머 전용 식사시간 처리
            my_meals = [fixed_meal]

        combined_settings[name] = {
            "range": range(int(s_time), int(e_time)),
            "meals": my_meals,
            "can_counter": c_auth
        }

# 5. 로테이션 생성 엔진
def run_rotation():
    display_times = [f"{h:02d}:00" for h in range(10, 22)] 
    all_staff = working_ft + working_pt
    schedule_df = pd.DataFrame(index=display_times, columns=all_staff)
    schedule_df.fillna("-", inplace=True)
    last_positions = {name: "" for name in all_staff}
    
    for slot in display_times:
        hour = int(slot.split(":")[0])
        available_pool = []
        
        for name in all_staff:
            s = combined_settings[name]
            if hour in s["range"]:
                if slot in s["meals"]:
                    schedule_df.at[slot, name] = "🍴식사"
                else:
                    available_now = True
                    available_pool.append(name)
            else:
                schedule_df.at[slot, name] = " "

        random.shuffle(available_pool)
        
        # 구역 배정
        for zone in target_zones:
            needed = zone_to_map[zone]
            assigned_count = 0
            
            eligible = [n for n in available_pool if not ("카운터" in zone and not combined_settings[n]["can_counter"])]
            eligible.sort(key=lambda x: last_positions[x] == zone)

            for name in eligible:
                if assigned_count < needed:
                    schedule_df.at[slot, name] = zone
                    last_positions[name] = zone
                    if name in available_pool: available_pool.remove(name)
                    assigned_count += 1
                else: break
        
        # 남은 모든 인원은 "📢지원"으로 배정
        for name in available_pool:
            schedule_df.at[slot, name] = "📢지원"
            last_positions[name] = "📢지원"
            
    return schedule_df

# 메인 버튼
if st.sidebar.button("🚀 로테이션 자동 생성"):
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    edited_result = st.data_editor(st.session_state.result_df, use_container_width=True, height=550)
    
    with st.expander("📊 실시간 구역별 인원 배치 현황"):
        summary_list = []
        for slot in edited_result.index:
            row_sum = {"시간": slot}
            for zone in target_zones:
                count = (edited_result.loc[slot] == zone).sum()
                limit = zone_to_map[zone]
                label_val = f"{count}/{limit}"
                if count > limit: label_val += " ⚠️"
                elif count < limit: label_val += " ❗"
                else: label_val += " ✅"
                row_sum[zone] = label_val
            summary_list.append(row_sum)
        st.table(pd.DataFrame(summary_list))

    csv = edited_result.to_csv().encode('utf-8-sig')
    st.download_button("📥 CSV 다운로드", csv, 'schedule.csv', 'text/csv')
