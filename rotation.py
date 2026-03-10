import streamlit as st
import pandas as pd
import random

# 1. 페이지 및 구글 시트 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v22.0)")

# 💡 관리자님의 구글 시트 ID를 여기에 입력하세요!
SHEET_ID = "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q" 
SHEET_NAME = "Sheet1" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url)
        # 열 이름 및 데이터의 앞뒤 공백 제거 (KeyError 방지)
        df.columns = [str(c).strip() for c in df.columns]
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"❌ 시트 로드 실패: {e}")
        return pd.DataFrame()

db_df = load_db()

if db_df.empty:
    st.error("❌ 데이터를 가져오지 못했습니다. [공유 설정: 링크가 있는 모든 사용자]를 확인하세요.")
    st.stop()

# ⭐ 강력 조치: 첫 번째 열을 강제로 '매장명'으로 인식
db_df.rename(columns={db_df.columns[0]: '매장명'}, inplace=True)

# 2. 매장 및 구역 자동 설정
store_list = sorted(db_df['매장명'].unique())
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", store_list)

store_data = db_df[db_df['매장명'] == selected_store]

# '운영구역' 열 자동 찾기
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
default_zones = str(store_data[zone_col].iloc[0]) if not store_data[zone_col].dropna().empty else "카운터, A, B, C"

st.sidebar.header("📍 구역 설정")
zone_input = st.sidebar.text_input("운영 구역", default_zones)
target_zones = [z.strip() for z in zone_input.split(",") if z.strip()]

# 3. 인원 선택 (정직원/파트타이머 분류)
# '구분' 열이 없으면 세 번째 열을 사용
type_col = '구분' if '구분' in store_data.columns else store_data.columns[2]
all_ft = store_data[store_data[type_col] == '정직원']['이름'].tolist()
all_pt = store_data[store_data[type_col] == '파트타이머']['이름'].tolist()

st.sidebar.divider()
working_ft = st.sidebar.multiselect("✅ 오늘 출근 정직원", all_ft, default=all_ft)
working_pt = st.sidebar.multiselect("✅ 오늘 출근 파트타이머", all_pt, default=all_pt)

# 정직원 조 설정
num_groups = st.sidebar.select_slider("식사 조 개수", options=[2, 3, 4], value=2)
group_labels = ["A", "B", "C", "D"][:num_groups]
group_configs = {}
for label in group_labels:
    with st.sidebar.expander(f"📅 {label}조 시간 설정"):
        s_t = st.number_input(f"{label}조 출근", 8, 12, 10, key=f"gs_{label}")
        e_t = st.number_input(f"{label}조 퇴근", 17, 22, 20, key=f"ge_{label}")
        m1 = st.selectbox(f"{label}조 식사1", [f"{h}:00" for h in range(s_t, e_t)], index=1, key=f"m1_{label}")
        m2 = st.selectbox(f"{label}조 식사2", [f"{h}:00" for h in range(s_t, e_t)], index=5, key=f"m2_{label}")
        group_configs[label] = {"start": s_t, "end": e_t, "meals": [m1, m2]}

ft_assignments = {}
for ft in working_ft:
    ft_assignments[ft] = st.sidebar.selectbox(f"{ft} 조", group_labels, key=f"assign_{ft}")

# 파트타이머 설정
pt_settings = {}
for pt in working_pt:
    with st.sidebar.expander(f"📌 {pt} 시간 및 권한"):
        ps_t = st.number_input(f"{pt} 출근", 10, 20, 10, key=f"{pt}_ps")
        pe_t = st.number_input(f"{pt} 퇴근", 11, 21, 20, key=f"{pt}_pe")
        pm_t = st.selectbox(f"{pt} 식사", [f"{h}:00" for h in range(ps_t+1, pe_t-1)], key=f"{pt}_pm")
        can_counter = st.checkbox(f"{pt} 카운터 가능", value=False, key=f"{pt}_counter")
        pt_settings[pt] = {"start": ps_t, "end": pe_t, "meal": pm_t, "can_counter": can_counter}

# 4. 로테이션 생성 로직
def generate_v22():
    all_starts = [conf["start"] for conf in group_configs.values()] + ([p["start"] for p in pt_settings.values()] if pt_settings else [10])
    all_ends = [conf["end"] for conf in group_configs.values()] + ([p["end"] for p in pt_settings.values()] if pt_settings else [20])
    time_slots = [f"{h}:00" for h in range(min(all_starts), max(all_ends))]
    
    final_rows = []
    zone_history = {z: [] for z in target_zones}

    for slot in time_slots:
        curr_h = int(slot.split(":")[0])
        row = {"시간": slot}
        ft_working = [ft for ft in working_ft if slot not in group_configs[ft_assignments[ft]]["meals"]]
        pt_working = [pt for pt in working_pt if slot != pt_settings[pt]["meal"] and pt_settings[pt]["start"] <= curr_h < pt_settings[pt]["end"]]
        
        counter_pool = ft_working + [pt for pt in pt_working if pt_settings[pt]["can_counter"]]
        random.shuffle(counter_pool)
        assign = {z: [] for z in target_zones}
        
        # 카운터 우선 배치
        primary_zone = target_zones[0]
        if counter_pool:
            chosen = counter_pool.pop(0)
            assign[primary_zone].append(chosen)
            if chosen in ft_working: ft_working.remove(chosen)
            else: pt_working.remove(chosen)
        else: assign[primary_zone].append("X")

        # 나머지 구역 배치
        remaining_pool = ft_working + pt_working
        random.shuffle(remaining_pool)
        for z in [z for z in target_zones if z != primary_zone]:
            if remaining_pool:
                valid = [p for p in remaining_pool if p not in zone_history[z]]
                chosen = random.choice(valid if valid else remaining_pool)
                assign[z].append(chosen)
                remaining_pool.remove(chosen)
            else: assign[z].append("X")

        while remaining_pool:
            z = target_zones[random.randint(0, len(target_zones)-1)]
            assign[z].append(remaining_pool.pop())

        for z in target_zones:
            row[z] = ", ".join(assign[z])
            zone_history[z] = (assign[z] + zone_history[z])[:2]
        final_rows.append(row)
    return pd.DataFrame(final_rows)

# 5. 실행
if st.sidebar.button("🚀 로테이션 생성"):
    st.session_state.df = generate_v22()

if 'df' in st.session_state:
    st.subheader(f"📊 {selected_store} 로테이션")
    st.data_editor(st.session_state.df, use_container_width=True)
