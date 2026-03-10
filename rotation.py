import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v54.0")

# 💡 실시간 구글 시트 데이터 로드
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
    st.error("❌ 데이터를 불러올 수 없습니다. 시트 권한이나 URL을 확인하세요."); st.stop()

# 컬럼명 정리
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
store_list = sorted([s for s in db_df['매장명'].unique() if s and str(s).lower() != 'none'])
selected_store = st.sidebar.selectbox("🏠 매장 선택", store_list)
store_data = db_df[db_df['매장명'] == selected_store].copy()

# 2. 구역 및 TO 설정
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 구역 설정 (형식: 구역명(인원))", raw_zones)

# 구역 이름과 TO 매핑
zone_to_map = {}
for z_info in zone_input.split(","):
    z_info = z_info.strip()
    match = re.search(r"(.+)\((\d+)\)", z_info)
    if match: 
        zone_to_map[match.group(1).strip()] = int(match.group(2))
    else: 
        zone_to_map[z_info] = 1
target_zones = list(zone_to_map.keys())

# 3. 인원 추출 함수
def extract_names(data, keyword):
    if data.empty: return []
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    if not type_col or not name_col: return []
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [n.replace('.0', '') for n in filtered[name_col].dropna().tolist() if n != 'None']

all_ft = extract_names(store_data, '정직')
all_pt = extract_names(store_data, '파트')

st.sidebar.subheader("👥 인원 선택")
working_ft = st.sidebar.multiselect("정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("파트타이머", all_pt, default=all_pt)

# 4. 상세 시간 설정
all_time_slots = [f"{h:02d}:00" for h in range(10, 22)]
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}
dinner_configs = {}

with st.sidebar.expander("🍴 공통 식사 시간대 설정"):
    for label in group_labels:
        col_l, col_r = st.columns(2)
        with col_l:
            lunch_configs[label] = st.selectbox(f"점심 {label}조", all_time_slots, index=3, key=f"L_cfg_{label}")
        with col_r:
            dinner_configs[label] = st.selectbox(f"저녁 {label}조", all_time_slots, index=8, key=f"D_cfg_{label}")

combined_settings = {}
st.sidebar.subheader("⏱️ 개인별 스케줄 세부조정")
for name in working_ft + working_pt:
    is_ft = name in working_ft
    match = store_data[store_data['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
    
    # 기본값 로드
    def_s = int(float(r.get('출근시간', 11)))
    def_e = int(float(r.get('퇴근시간', 21)))
    l_grp = str(r.get('점심조', 'A')).upper()
    d_grp = str(r.get('저녁조', 'A')).upper()
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y']

    with st.sidebar.expander(f"{'👤' if is_ft else '⏱️'} {name}"):
        col1, col2 = st.columns(2)
        with col1:
            s_time = st.number_input(f"출근", 8, 22, def_s, key=f"s_{name}")
        with col2:
            e_time = st.number_input(f"퇴근", 9, 23, def_e, key=f"e_{name}")
        
        l_choice = st.selectbox(f"점심조", group_labels, index=group_labels.index(l_v) if l_v in group_labels else 0, key=f"lc_{name}")
        d_choice = st.selectbox(f"저녁조", group_labels, index=group_labels.index(d_v) if d_v in group_labels else 0, key=f"dc_{name}")
        c_auth = st.checkbox("카운터 가능", value=is_c, key=f"auth_{name}")
        
        combined_settings[name] = {
            "range": range(s_time, e_time),
            "meals": [lunch_configs[l_choice], dinner_configs[d_choice]],
            "can_counter": c_auth,
            "is_ft": is_ft
        }

# 5. 로테이션 생성 엔진
def run_rotation():
    all_staff = working_ft + working_pt
    schedule_df = pd.DataFrame(index=all_time_slots, columns=all_staff)
    last_positions = {name: "" for name in all_staff}
    
    for slot in all_time_slots:
        hour = int(slot.split(":")[0])
        available_pool = []
        
        # 1. 해당 시간에 근무 및 식사 여부 확인
        for name in all_staff:
            setting = combined_settings[name]
            if hour in setting["range"]:
                if slot in setting["meals"]:
                    schedule_df.at[slot, name] = "🍴식사"
                else:
                    available_now = True
                    available_pool.append(name)
            else:
                schedule_df.at[slot, name] = " "

        # 셔플하여 랜덤성 부여
        random.shuffle(available_pool)
        
        # 2. 구역별로 인원 배정 (설정된 TO만큼)
        for zone in target_zones:
            needed = zone_to_map[zone]
            assigned_count = 0
            
            # 이 구역에 들어갈 수 있는 후보 필터링
            eligible_candidates = []
            for name in available_pool:
                # 카운터 구역일 경우 권한 확인
                if "카운터" in zone and not combined_settings[name]["can_counter"]:
                    continue
                eligible_candidates.append(name)

            # 직전 구역과 다른 사람 우선순위 (가능한 경우)
            eligible_candidates.sort(key=lambda x: last_positions[x] == zone)

            for name in list(eligible_candidates):
                if assigned_count < needed:
                    schedule_df.at[slot, name] = zone
                    last_positions[name] = zone
                    available_pool.remove(name)
                    assigned_count += 1
                else:
                    break
        
        # 3. 남은 인원 '📢지원'으로 배정 (TO 초과분 수용)
        for name in list(available_pool):
            schedule_df.at[slot, name] = "📢지원"
            last_positions[name] = "📢지원"
            
    return schedule_df

# 메인 화면 실행
if st.sidebar.button("🚀 로테이션 자동 생성"):
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    st.info("💡 셀을 수정하려면 더블클릭하세요. 수정 후 하단에서 엑셀로 저장 가능합니다.")
    
    # 데이터 에디터 출력
    edited_result = st.data_editor(
        st.session_state.result_df,
        use_container_width=True,
        height=500
    )
    
    # 현황 요약 (TO 대비 실제 배치 인원)
    with st.expander("📊 구역별 인원 배치 현황 (TO 초과 체크)"):
        summary_data = []
        for slot in all_time_slots:
            row_summary = {"시간": slot}
            for zone in target_zones:
                count = (edited_result.loc[slot] == zone).sum()
                limit = zone_to_map[z_info.strip() if (z_info := zone) in zone_to_map else zone]
                status = f"{count}/{limit}"
                if count > limit:
                    status += " ⚠️초과"
                row_summary[zone] = status
            summary_data.append(row_summary)
        st.table(pd.DataFrame(summary_data))

    # 엑셀 다운로드
    csv = edited_result.to_csv().encode('utf-8-sig')
    st.download_button(
        label="📥 현재 스케줄 CSV로 내보내기",
        data=csv,
        file_name='rotation_schedule.csv',
        mime='text/csv',
    )
