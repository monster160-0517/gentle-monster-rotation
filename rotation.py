import streamlit as st
import pandas as pd
import random

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v69.1")

# 🔗 매장별 구글 시트 ID 딕셔너리
STORES = {
    "하우스 서울": "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q",
    "하우스 도산": "1nqSbhCPnO1o_vRSubJCuLjbbZxmtRMjioTtA_ZzzNLc"
}

TO_SHEET_GID = "2126973547"

# --- 사이드바 설정 ---
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", list(STORES.keys()))
SHEET_ID = STORES[selected_store]

@st.cache_data(ttl=1)
def load_sheet_data(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.astype(str).replace(r'\.0$', '', regex=True).replace(['nan', 'None', 'nan.0'], '')
        return df
    except: return pd.DataFrame()

# 데이터 로드
db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty or to_df.empty:
    st.warning("⚠️ 데이터를 불러오지 못했습니다. 시트 설정을 확인해주세요.")
    st.stop()

# ⏰ 시간 범위 고정 (11:00 ~ 20:00)
all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]

# 인원 선택
def extract_names(data, keyword):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [str(n).strip() for n in filtered[name_col].dropna().tolist() if n != '']

working_ft = st.sidebar.multiselect("👤 정직원", extract_names(db_df, '정직'), default=extract_names(db_df, '정직'))
working_pt = st.sidebar.multiselect("⏱️ 파트타이머", extract_names(db_df, '파트'), default=extract_names(db_df, '파트'))
all_staff_selected = list(dict.fromkeys([n for n in (working_ft + working_pt) if n.strip() != ""]))

# 식사 시간 설정 (범위 내에서 선택)
time_options = all_time_slots
group_labels = ["A", "B", "C", "D", "E"]
lunch_slots, dinner_slots = {}, {}
with st.sidebar.expander("🍴 조별 식사 시간 설정"):
    for label in group_labels:
        c1, c2 = st.columns(2)
        with c1: lunch_slots[label] = st.selectbox(f"점심 {label}", time_options, index=group_labels.index(label)%len(time_options), key=f"L_{label}")
        with c2: dinner_slots[label] = st.selectbox(f"저녁 {label}", time_options, index=(group_labels.index(label)+4)%len(time_options), key=f"D_{label}")

# 개인별 설정
combined_settings = {}
for name in all_staff_selected:
    match = db_df[db_df['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
    s_time = int(float(r.get('출근시간', 11)))
    e_time = int(float(r.get('퇴근시간', 21)))
    l_grp, d_grp = str(r.get('점심조', 'A')).strip().upper(), str(r.get('저녁조', 'A')).strip().upper()
    c_raw = str(r.get('카운터여부', 'X')).lower()
    is_c = any(x in c_raw for x in ['o', 'y', '1', 'v', 'true', '예', 'ok'])
    
    combined_settings[name] = {
        "range": range(s_time, e_time),
        "meals": [lunch_slots.get(l_grp), dinner_slots.get(d_grp)],
        "can_counter": is_c
    }

generate_btn = st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True)

# --- 로테이션 엔진 ---
def run_rotation():
    schedule_df = pd.DataFrame(index=all_time_slots, columns=all_staff_selected).fillna("-")
    last_positions = {name: "" for name in all_staff_selected}
    counter_counts = {name: 0 for name in all_staff_selected}
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    for slot in all_time_slots:
        hour = int(slot.split(":")[0])
        available_pool = []
        for name in all_staff_selected:
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
                
                if "카운터" in zone:
                    eligible.sort(key=lambda x: (counter_counts[x], last_positions[x] == zone))
                else:
                    eligible.sort(key=lambda x: last_positions[x] == zone)

                for name in eligible:
                    if assigned < needed:
                        schedule_df.at[slot, name] = zone
                        last_positions[name] = zone
                        if "카운터" in zone: counter_counts[name] += 1
                        if name in available_pool: available_pool.remove(name)
                        assigned += 1
        
        for name in available_pool:
            schedule_df.at[slot, name] = "📢 지원"
            last_positions[name] = "📢 지원"
            
    return schedule_df

# --- 결과 출력 ---
if generate_btn:
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state and not st.session_state.result_df.empty:
    st.write(f"### 📅 [{selected_store}] 로테이션 결과")
    
    # 1. 수정용 에디터 (행: 시간, 열: 이름)
    edited_df = st.data_editor(st.session_state.result_df, use_container_width=True, height=450)

    # 2. 📱 모바일 공유용 대시보드 (행: 구역, 열: 시간)
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판 (구역별)")
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    display_zones = all_zones + ["📢 지원", "🍴 식사"]
    capture_board = pd.DataFrame(index=display_zones, columns=edited_df.index).fillna("")

    for slot in edited_df.index:
        current_to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        for zone in display_zones:
            staff_list = edited_df.columns[edited_df.loc[slot] == zone].tolist()
            staff_str = ", ".join(staff_list) if staff_list else "-"
            
            if zone in all_zones:
                try: limit = int(float(current_to_row[zone].iloc[0]))
                except: limit = 0
                count = len(staff_list)
                icon = "✅" if count >= limit else "⚠️"
                capture_board.at[zone, slot] = f"{icon}({count}/{limit})\n{staff_str}"
            else:
                capture_board.at[zone, slot] = staff_str

    st.table(capture_board)
