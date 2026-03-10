import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템")

# 💡 실시간 구글 시트 데이터 로드
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        if df.empty: return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        # 데이터 클리닝
        for col in df.columns:
            df[col] = df[col].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        return pd.DataFrame()

db_df = load_db()
if db_df.empty:
    st.warning("⚠️ 데이터를 불러올 수 없습니다. 구글 시트의 [공유] 설정이 '링크가 있는 모든 사용자'로 되어 있는지 확인해주세요.")
    st.stop()

# 컬럼명 표준화
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
store_list = sorted([s for s in db_df['매장명'].unique() if s and s.lower() != 'none'])
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", store_list)
store_data = db_df[db_df['매장명'] == selected_store].copy()

# 2. 구역 및 TO 설정
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
raw_zones = str(store_data[zone_col].iloc[0]) if not store_data.empty else "카운터(1), A(1)"
zone_input = st.sidebar.text_input("📍 구역 설정 (형식: 구역명(인원))", raw_zones)

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
    return [str(n).split('.')[0] for n in filtered[name_col].dropna().tolist() if str(n) != 'None']

all_ft = extract_names(store_data, '정직')
all_pt = extract_names(store_data, '파트')

st.sidebar.subheader("👥 인원 선택")
working_ft = st.sidebar.multiselect("정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("파트타이머", all_pt, default=all_pt)

# 4. 상세 시간 설정
all_time_slots = [f"{h:02d}:00" for h in range(8, 24)]
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}
dinner_configs = {}

with st.sidebar.expander("🍴 공통 식사 시간대 설정"):
    for label in group_labels:
        col_l, col_r = st.columns(2)
        with col_l:
            lunch_configs[label] = st.selectbox(f"점심 {label}", all_time_slots, index=4, key=f"L_cfg_{label}")
        with col_r:
            dinner_configs[label] = st.selectbox(f"저녁 {label}조", all_time_slots, index=10, key=f"D_cfg_{label}")

# 인원별 세부 세팅 수집
combined_settings = {}
st.sidebar.subheader("⏱️ 개인별 스케줄 세부조정")
all_selected_staff = working_ft + working_pt

for name in all_selected_staff:
    is_ft = name in working_ft
    name_col = next((c for c in store_data.columns if '이름' in c), '이름')
    match = store_data[store_data[name_col] == name]
    r = match.iloc[0] if not match.empty else {}
    
    # 시간 데이터 수치화 (매우 중요)
    try:
        def_s = int(float(str(r.get('출근시간', 11))))
        def_e = int(float(r.get('퇴근시간', 21)))
    except:
        def_s, def_e = 11, 21

    def_s = max(8, min(22, def_s))
    def_e = max(8, min(23, def_e))

    l_grp = str(r.get('점심조', 'A')).upper()
    d_grp = str(r.get('저녁조', 'A')).upper()
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y', 'TRUE']

    with st.sidebar.expander(f"{'👤' if is_ft else '⏱️'} {name}"):
        col1, col2 = st.columns(2)
        with col1:
            s_time = st.number_input(f"출근", 8, 22, def_s, key=f"s_in_{name}")
        with col2:
            e_time = st.number_input(f"퇴근", 8, 23, e_time if 'e_time' in locals() and e_time > s_time else def_e, key=f"e_in_{name}")
        
        l_choice = st.selectbox(f"점심조", group_labels, index=group_labels.index(l_grp) if l_grp in group_labels else 0, key=f"lc_{name}")
        d_choice = st.selectbox(f"저녁조", group_labels, index=group_labels.index(d_grp) if d_grp in group_labels else 0, key=f"dc_{name}")
        c_auth = st.checkbox("카운터 가능", value=is_c, key=f"auth_{name}")
        
        combined_settings[name] = {
            "range": range(s_time, e_time),
            "meals": [lunch_configs[l_choice], dinner_configs[d_choice]],
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
        
        # 1. 해당 시간에 근무 중인 모든 인원 모집
        for name in all_staff:
            setting = combined_settings[name]
            if hour in setting["range"]:
                if slot in setting["meals"]:
                    schedule_df.at[slot, name] = "🍴식사"
                else:
                    available_pool.append(name)
            else:
                schedule_df.at[slot, name] = " "

        # 섞기 (공정성)
        random.shuffle(available_pool)
        
        # 2. 구역별 배정
        for zone in target_zones:
            needed = zone_to_map[zone]
            assigned_count = 0
            
            # 자격이 되는 사람 후보 (카운터 체크)
            eligible = []
            for name in available_pool:
                if "카운터" in zone and not combined_settings[name]["can_counter"]:
                    continue
                eligible.append(name)

            # 직전 구역 회피 정렬
            eligible.sort(key=lambda x: last_positions[x] == zone)

            for name in eligible:
                if assigned_count < needed:
                    schedule_df.at[slot, name] = zone
                    last_positions[name] = zone
                    if name in available_pool: available_pool.remove(name)
                    assigned_count += 1
                else:
                    break
        
        # 3. 남은 인원 처리 (무조건 배정)
        for name in available_pool:
            schedule_df.at[slot, name] = "📢지원"
            last_positions[name] = "📢지원"
            
    return schedule_df

# 메인 화면 실행
if st.sidebar.button("🚀 로테이션 자동 생성"):
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    
    # 데이터 에디터 출력
    edited_result = st.data_editor(
        st.session_state.result_df,
        use_container_width=True,
        height=550
    )
    
    # 현황 요약 (TO 대비 실제 배치 인원)
    with st.expander("📊 실시간 구역별 인원 배치 현황"):
        summary_data = []
        for slot in edited_result.index:
            row_summary = {"시간": slot}
            for zone in target_zones:
                count = (edited_result.loc[slot] == zone).sum()
                limit = zone_to_map[zone]
                status = f"{count}/{limit}"
                if count > limit:
                    status = f"⚠️ {count}/{limit}"
                elif count < limit:
                    status = f"❗ {count}/{limit}"
                row_summary[zone] = status
            summary_data.append(row_summary)
        
        st.table(pd.DataFrame(summary_data))

    # 다운로드
    csv = edited_result.to_csv().encode('utf-8-sig')
    st.download_button(
        label="📥 현재 스케줄 CSV로 다운로드",
        data=csv,
        file_name=f'rotation_{selected_store}.csv',
        mime='text/csv',
    )
