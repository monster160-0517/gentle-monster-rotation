import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템")

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
        # 데이터 정리
        df = df.astype(str).replace(['nan', 'None', 'nan.0'], None).apply(lambda x: x.strip() if x else x)
        return df
    except: return pd.DataFrame()

db_df = load_db()
if db_df.empty:
    st.error("❌ 데이터를 불러올 수 없습니다. 시트 권한이나 URL을 확인하세요."); st.stop()

# 컬럼명 정리
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)
store_list = sorted([s for s in db_df['매장명'].unique() if s and str(s).lower() != 'none'])
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", store_list)
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
working_pt = st.sidebar.multiselect("파트타이머", working_pt if 'working_pt' in locals() else all_pt, default=all_pt)

# 4. 상세 시간 설정
all_time_slots = [f"{h:02d}:00" for h in range(8, 24)] # 08시부터 23시까지 선택폭 확장
group_labels = ["A", "B", "C", "D", "E"]
lunch_configs = {}
dinner_configs = {}

with st.sidebar.expander("🍴 공통 식사 시간대 설정"):
    for label in group_labels:
        col_l, col_r = st.columns(2)
        with col_l:
            lunch_configs[label] = st.selectbox(f"점심 {label}조", all_time_slots, index=4, key=f"L_cfg_{label}")
        with col_r:
            dinner_configs[label] = st.selectbox(f"저녁 {label}조", all_time_slots, index=10, key=f"D_cfg_{label}")

# 인원별 세부 세팅 수집
combined_settings = {}
st.sidebar.subheader("⏱️ 개인별 스케줄 세부조정")
for name in working_ft + working_pt:
    is_ft = name in working_ft
    match = store_data[store_data['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
    
    # 에러 방지를 위해 범위를 0~23으로 넓게 잡음
    try:
        def_s = int(float(r.get('출근시간', 11)))
        def_e = int(float(r.get('퇴근시간', 21)))
    except:
        def_s, def_e = 11, 21

    # 만약 시트 값이 0~23 범위를 벗어나면 강제 조정
    def_s = max(0, min(23, def_s))
    def_e = max(0, min(23, def_e))

    l_grp = str(r.get('점심조', 'A')).upper()
    d_grp = str(r.get('저녁조', 'A')).upper()
    is_c = str(r.get('카운터여부', 'X')).upper() in ['O', 'Y']

    with st.sidebar.expander(f"{'👤' if is_ft else '⏱️'} {name}"):
        col1, col2 = st.columns(2)
        with col1:
            s_input = st.number_input(f"출근", 0, 23, def_s, key=f"s_{name}")
        with col2:
            e_input = st.number_input(f"퇴근", 0, 23, def_e, key=f"e_{name}")
        
        l_choice = st.selectbox(f"점심조", group_labels, index=group_labels.index(l_grp) if l_grp in group_labels else 0, key=f"lc_{name}")
        d_choice = st.selectbox(f"저녁조", group_labels, index=group_labels.index(d_grp) if d_grp in group_labels else 0, key=f"dc_{name}")
        c_auth = st.checkbox("카운터 가능", value=is_c, key=f"auth_{name}")
        
        combined_settings[name] = {
            "range": range(s_input, e_input),
            "meals": [lunch_configs[l_choice], dinner_configs[d_choice]],
            "can_counter": c_auth,
            "is_ft": is_ft
        }

# 5. 로테이션 생성 엔진
def run_rotation():
    display_time_slots = [f"{h:02d}:00" for h in range(10, 22)] # 출력할 시간대 (10시~21시)
    all_staff = working_ft + working_pt
    
    schedule_df = pd.DataFrame(index=display_time_slots, columns=all_staff)
    schedule_df.fillna("-", inplace=True)
    
    last_positions = {name: "" for name in all_staff}
    
    for slot in display_time_slots:
        hour = int(slot.split(":")[0])
        available_pool = []
        
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

        random.shuffle(available_pool)
        
        for zone in target_zones:
            needed = zone_to_map[zone]
            assigned_count = 0
            
            eligible_candidates = []
            for name in available_pool:
                if "카운터" in zone and not combined_settings[name]["can_counter"]:
                    continue
                eligible_candidates.append(name)

            # 직전 구역 회피 로직
            eligible_candidates.sort(key=lambda x: last_positions[x] == zone)

            for name in list(eligible_candidates):
                if assigned_count < needed:
                    schedule_df.at[slot, name] = zone
                    last_positions[name] = zone
                    if name in available_pool: available_pool.remove(name)
                    assigned_count += 1
                else:
                    break
        
        # 남은 인원은 '📢지원'으로 배정
        for name in list(available_pool):
            schedule_df.at[slot, name] = "📢지원"
            last_positions[name] = "📢지원"
            
    return schedule_df

# 메인 화면 실행
if st.sidebar.button("🚀 로테이션 자동 생성"):
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    st.write("### 📅 생성된 로테이션 스케줄")
    st.info("💡 셀을 더블클릭하여 수정 가능합니다. (행: 시간 / 열: 이름)")
    
    # 데이터 에디터 출력
    edited_result = st.data_editor(
        st.session_state.result_df,
        use_container_width=True,
        height=550
    )
    
    # 현황 요약 (TO 대비 실제 배치 인원)
    with st.expander("📊 실시간 구역별 인원 배치 현황 (TO 체크)"):
        summary_data = []
        for slot in edited_result.index:
            row_summary = {"시간": slot}
            for zone in target_zones:
                count = (edited_result.loc[slot] == zone).sum()
                limit = zone_to_map[zone]
                status = f"{count}/{limit}"
                if count > limit:
                    status = f"⚠️ {count}/{limit} (초과)"
                elif count < limit:
                    status = f"❗ {count}/{limit} (부족)"
                row_summary[zone] = status
            summary_data.append(row_summary)
        
        st.table(pd.DataFrame(summary_data))

    # 엑셀 다운로드 (CSV)
    csv = edited_result.to_csv().encode('utf-8-sig')
    st.download_button(
        label="📥 현재 스케줄 CSV로 내보내기",
        data=csv,
        file_name='rotation_schedule.csv',
        mime='text/csv',
    )
