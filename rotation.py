import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")

# 스타일 적용 (식사 노란색, 이름 색상 등)
st.markdown("""
    <style>
    .meal-bg { background-color: #ffff00 !important; color: black !important; font-weight: bold; }
    .morning-staff { color: #007bff !important; font-weight: bold; }
    .afternoon-staff { color: #e83e8c !important; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("GENTLE MONSTER 로테이션 시스템 v70.1")

# 🔗 매장별 구글 시트 ID 딕셔너리
STORES = {
    "하우스 서울": "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q",
    "하우스 도산": "1nqSbhCPnO1o_vRSubJCuLjbbZxmtRMjioTtA_ZzzNLc"
}
TO_SHEET_GID = "2126973547"

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

db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty or to_df.empty:
    st.warning("⚠️ 데이터를 불러오지 못했습니다. 시트 설정을 확인해주세요.")
    st.stop()

# ⏰ 시간 범위 (11:00 ~ 20:00)
all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]

def get_staff_info(data, types):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    res = []
    for t in types:
        filtered = data[data[type_col].str.contains(t, na=False, case=False)]
        for _, row in filtered.iterrows():
            name = str(row[name_col]).strip()
            if name:
                try: is_morning = int(float(row.get('출근시간', 11))) < 12
                except: is_morning = True
                res.append({"name": name, "is_morning": is_morning})
    return res

staff_info_list = get_staff_info(db_df, ['정직', '파트'])
all_staff_names = [s['name'] for s in staff_info_list]

working_staff = st.sidebar.multiselect("👤 근무 인원 선택", all_staff_names, default=all_staff_names)

# 조별 식사 설정
group_labels = ["A", "B", "C", "D", "E"]
lunch_slots, dinner_slots = {}, {}
with st.sidebar.expander("🍴 조별 식사 설정"):
    for label in group_labels:
        c1, c2 = st.columns(2)
        with c1: lunch_slots[label] = st.selectbox(f"점심 {label}", all_time_slots, index=group_labels.index(label)%len(all_time_slots), key=f"L_{label}")
        with c2: dinner_slots[label] = st.selectbox(f"저녁 {label}", all_time_slots, index=(group_labels.index(label)+4)%len(all_time_slots), key=f"D_{label}")

combined_settings = {}
for s_info in staff_info_list:
    name = s_info['name']
    if name not in working_staff: continue
    match = db_df[db_df['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
    
    try:
        s_t, e_t = int(float(str(r.get('출근시간', 11)))), int(float(str(r.get('퇴근시간', 21))))
    except: s_t, e_t = 11, 21
    
    # 식사 시간 파싱 (식사시간 열 우선)
    meal_val = str(r.get('식사시간', '')).strip()
    fixed_match = re.search(r'(\d{1,2})', meal_val)
    if fixed_match:
        my_meals = [f"{int(fixed_match.group(1)):02d}:00"]
    else:
        l_g, d_g = str(r.get('점심조', 'A')).strip().upper(), str(r.get('저녁조', 'A')).strip().upper()
        my_meals = [lunch_slots.get(l_g), dinner_slots.get(d_g)]
    
    combined_settings[name] = {
        "range": range(s_t, e_t),
        "meals": [m for m in my_meals if m],
        "is_morning": s_info['is_morning'],
        "can_counter": any(x in str(r.get('카운터여부', 'X')).lower() for x in ['o', 'y', '1', 'v', '예'])
    }

# --- 로테이션 엔진 ---
def run_rotation():
    schedule_df = pd.DataFrame(index=all_time_slots, columns=working_staff).fillna("-")
    counter_counts = {n: 0 for n in working_staff}
    last_pos = {n: "" for n in working_staff}
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    for slot in all_time_slots:
        hr = int(slot.split(":")[0])
        pool = []
        for n in working_staff:
            s = combined_settings.get(n)
            if s and hr in s["range"]:
                if slot in s["meals"]: schedule_df.at[slot, n] = "식사"
                else: pool.append(n)
            else: schedule_df.at[slot, n] = " "

        random.shuffle(pool)
        to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        
        if not to_row.empty:
            zone_cfg = {}
            for z in all_zones:
                raw_to = str(to_row[z].iloc[0]).strip()
                if '-' in raw_to:
                    try: mi, ma = map(int, raw_to.split('-'))
                    except: mi = ma = 0
                else:
                    try: mi = ma = int(float(raw_to)) if raw_to else 0
                    except: mi = ma = 0
                zone_cfg[z] = {"min": mi, "max": ma}

            # 1단계: 모든 구역 최소 TO 채우기
            for z in all_zones:
                needed = zone_cfg[z]["min"]
                assigned = 0
                eligible = [n for n in pool if not ("카운터" in z and not combined_settings[n]["can_counter"])]
                # 카운터 평준화 + 직전 구역 회피
                eligible.sort(key=lambda x: (counter_counts[x] if "카운터" in z else 0, last_pos[x] == z))
                
                for n in eligible:
                    if assigned < needed:
                        schedule_df.at[slot, n] = z
                        last_pos[n] = z
                        if "카운터" in z: counter_counts[n] += 1
                        if n in pool: pool.remove(n)
                        assigned += 1
            
            # 2단계: 최대 TO까지 왼쪽 구역부터 순서대로 추가 채우기
            for z in all_zones:
                current_cnt = (schedule_df.loc[slot] == z).sum()
                needed_extra = zone_cfg[z]["max"] - current_cnt
                assigned_extra = 0
                eligible = [n for n in pool if not ("카운터" in z and not combined_settings[n]["can_counter"])]
                
                for n in eligible:
                    if assigned_extra < max(0, needed_extra):
                        schedule_df.at[slot, n] = z
                        last_pos[n] = z
                        if "카운터" in z: counter_counts[n] += 1
                        if n in pool: pool.remove(n)
                        assigned_extra += 1

        for n in pool:
            schedule_df.at[slot, n] = "지원"
            last_pos[n] = "지원"
            
    return schedule_df

if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    st.session_state.result_df = run_rotation()

if 'result_df' in st.session_state:
    res = st.session_state.result_df
    edited = st.data_editor(res, use_container_width=True)
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    
    # HTML 렌더링 (디자인 요청 반영)
    html = "<table style='width:100%; border-collapse: collapse; text-align: center;'>"
    # Header
    html += "<tr><th style='border: 1px solid #ddd; padding: 10px; background: #f4f4f4;'>시간</th>"
    for name in edited.columns:
        color = "#007bff" if combined_settings[name]["is_morning"] else "#e83e8c"
        html += f"<th style='border: 1px solid #ddd; padding: 10px; color: {color};'>{name}</th>"
    html += "</tr>"
    
    # Body
    for slot, row in edited.iterrows():
        html += f"<tr><td style='border: 1px solid #ddd; padding: 10px; font-weight: bold;'>{slot}</td>"
        for val in row:
            bg = "background-color: #ffff00; font-weight: bold;" if val == "식사" else ""
            color = "color: #adb5bd;" if val == "지원" else "color: black;"
            html += f"<td style='border: 1px solid #ddd; padding: 10px; {bg} {color}'>{val}</td>"
        html += "</tr>"
    html += "</table>"
    
    st.markdown(html, unsafe_allow_html=True)
    
    st.markdown("<p style='font-size: 0.8em; color: gray;'>* 파란색: 오전 출근자 | 분홍색: 오후 출근자</p>", unsafe_allow_html=True)
