import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 로테이션 시스템 v68.1")

# 🔗 [핵심] 매장별 구글 시트 ID 딕셔너리
# 매장이 추가되면 아래에 "매장명": "시트ID" 형식으로 추가하세요.
STORES = {
    "하우스 도산": "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q",
    "신사 플래그십": "1nqSbhCPnO1o_vRSubJCuLjbbZxmtRMjioTtA_ZzzNLc"
}

# 모든 매장 시트에서 '시간대별TO' 탭의 gid (사본 만들기를 했다면 동일함)
TO_SHEET_GID = "2126973547"

# --- 사이드바: 매장 선택 및 인원 설정 ---
st.sidebar.header("🕹️ 컨트롤 패널")
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", list(STORES.keys()))
SHEET_ID = STORES[selected_store]

@st.cache_data(ttl=1)
def load_sheet_data(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        df = pd.read_csv(url, skip_blank_lines=True)
        if df.empty: return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        # 데이터 클리닝: 소수점 제거 및 빈값 처리
        df = df.astype(str).replace(r'\.0$', '', regex=True).replace(['nan', 'None', 'nan.0'], '')
        return df
    except:
        return pd.DataFrame()

def parse_time_value(val):
    try:
        if not val or val == '': return 0
        if '-' in str(val): return int(float(str(val).split('-')[0]))
        return int(float(str(val)))
    except: return 0

# 데이터 로드
db_df = load_sheet_data("0")          # 인원 정보
to_df = load_sheet_data(TO_SHEET_GID) # 시간대별 TO

if db_df.empty or to_df.empty:
    st.warning(f"⚠️ [{selected_store}] 데이터를 불러오지 못했습니다. 구글 시트의 [공유] 설정(링크가 있는 모든 사용자-뷰어)을 확인해주세요.")
    st.stop()

# 인원 추출 함수
def extract_names(data, keyword):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    filtered = data[data[type_col].str.contains(keyword, na=False, case=False)]
    return [str(n).strip() for n in filtered[name_col].dropna().tolist() if n != '']

working_ft = st.sidebar.multiselect("👤 정직원", extract_names(db_df, '정직'), default=extract_names(db_df, '정직'))
working_pt = st.sidebar.multiselect("⏱️ 파트타이머", extract_names(db_df, '파트'), default=extract_names(db_df, '파트'))

# 식사 시간 설정
time_options = [f"{h:02d}:00" for h in range(11, 22)]
group_labels = ["A", "B", "C", "D", "E"]
lunch_slots, dinner_slots = {}, {}
with st.sidebar.expander("🍴 조별 식사 시간 설정"):
    for label in group_labels:
        c1, c2 = st.columns(2)
        with c1: lunch_slots[label] = st.selectbox(f"점심 {label}", time_options, index=group_labels.index(label)%len(time_options), key=f"L_{label}")
        with c2: dinner_slots[label] = st.selectbox(f"저녁 {label}", time_options, index=(group_labels.index(label)+5)%len(time_options), key=f"D_{label}")

# 개인별 근무/식사/권한 설정 세팅
combined_settings = {}
all_staff_selected = list(dict.fromkeys([n for n in (working_ft + working_pt) if n.strip() != ""]))

for name in all_staff_selected:
    match = db_df[db_df['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
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

# --- 로테이션 엔진 (카운터 평준화 로직 포함) ---
def run_rotation():
    display_times = [f"{h:02d}:00" for h in range(10, 22)]
    schedule_df = pd.DataFrame(index=display_times, columns=all_staff_selected).fillna("-")
    last_positions = {name: "" for name in all_staff_selected}
    counter_counts = {name: 0 for name in all_staff_selected} # 카운터 횟수 카운트
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    for slot in display_times:
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
            # 카운터 우선 순위 배정
            sorted_zones = sorted(all_zones, key=lambda x: "카운터" not in x)
            for zone in sorted_zones:
                try: needed = int(float(current_to_row[zone].iloc[0]))
                except: needed = 0
                assigned = 0
                
                # 카운터 권한 필터링
                eligible = [n for n in available_pool if not ("카운터" in zone and not combined_settings[n]["can_counter"])]
                
                # 평준화 정렬: 1순위 카운터 적게 본 사람, 2순위 직전 구역 회피
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
    
    # 엑셀 다운로드 버튼
    csv = st.session_state.result_df.to_csv(index=True).encode('utf-8-sig')
    st.download_button("📥 엑셀(CSV) 다운로드", csv, f"rotation_{selected_store}.csv", "text/csv", use_container_width=True)

    # 메인 결과 표 (수정 가능)
    edited_df = st.data_editor(st.session_state.result_df, use_container_width=True, height=500)
    
    # 하단 현황 보드 (구역=행, 시간=열) - 캡처용
    st.write("---")
    st.write("### 📍 구역별 배치 현황 (캡처용)")
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    display_zones = all_zones + ["📢 지원", "🍴 식사"]
    status_board = pd.DataFrame(index=display_zones, columns=edited_df.index).fillna("")

    for slot in edited_df.index:
        current_to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        for zone in display_zones:
            staff_list = edited_df.columns[edited_df.loc[slot] == zone].tolist()
            staff_str = ", ".join(staff_list) if staff_list else "-"
            if zone in all_zones:
                try: limit = int(float(current_to_row[zone].iloc[0]))
                except: limit = 0
                icon = "✅" if len(staff_list) >= limit else "❌"
                status_board.at[zone, slot] = f"[{len(staff_list)}/{limit}] {icon} | {staff_str}"
            else:
                status_board.at[zone, slot] = staff_str
    
    st.dataframe(status_board, use_container_width=True)

    # 카운터 평준화 데이터 확인용 요약
    with st.expander("📊 직원별 카운터 누적 횟수 (균등 배분 체크)"):
        summary = [{"이름": name, "카운터 횟수": (edited_df[name] == "카운터").sum()} for name in edited_df.columns]
        st.table(pd.DataFrame(summary))
