import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")

st.markdown("""
    <style>
    .meal-bg { background-color: #ffff00 !important; color: black !important; font-weight: bold; }
    .status-ok { color: #28a745; font-weight: bold; }
    .status-warn { color: #dc3545; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("GENTLE MONSTER 로테이션 시스템 v70.4")

# 🔗 매장 및 시트 설정
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
        df = df.fillna("").astype(str).replace(r'\.0$', '', regex=True)
        return df
    except: return pd.DataFrame()

db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty or to_df.empty:
    st.warning("⚠️ 데이터를 불러오지 못했습니다.")
    st.stop()

all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]

# 인원 정보 파싱 함수
def get_staff_info(data, types):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    res, seen = [], set()
    for t in types:
        filtered = data[data[type_col].str.contains(t, na=False, case=False)]
        for _, row in filtered.iterrows():
            name = str(row[name_col]).strip()
            if name and name not in seen:
                try: is_morning = int(float(row.get('출근시간', 11))) < 12
                except: is_morning = True
                res.append({"name": name, "is_morning": is_morning, "type": t})
                seen.add(name)
    return res

# 전체 인원 데이터 로드
all_staff_data = get_staff_info(db_df, ['정직', '파트'])

# --- 사이드바: 파트타이머만 선택 ---
st.sidebar.header("🕹️ 인원 관리")
ft_names = [s['name'] for s in all_staff_data if '정직' in s['type']]
pt_names = [s['name'] for s in all_staff_data if '파트' in s['type']]

selected_pt = st.sidebar.multiselect("⏱️ 오늘 출근 파트타이머", pt_names, default=pt_names)

# 최종 근무 인원 확정 (정직원 전원 + 선택된 파트타이머)
working_staff_names = ft_names + selected_pt
working_staff_info = [s for s in all_staff_data if s['name'] in working_staff_names]

# 조별 식사 설정
group_labels = ["A", "B", "C", "D", "E"]
lunch_slots, dinner_slots = {}, {}
with st.sidebar.expander("🍴 정직원 조별 식사 설정"):
    for label in group_labels:
        c1, c2 = st.columns(2)
        with c1: lunch_slots[label] = st.selectbox(f"점심 {label}", all_time_slots, index=group_labels.index(label)%len(all_time_slots), key=f"L_{label}")
        with c2: dinner_slots[label] = st.selectbox(f"저녁 {label}", all_time_slots, index=(group_labels.index(label)+4)%len(all_time_slots), key=f"D_{label}")

# 개인별 세팅 구축
combined_settings = {}
for s_info in working_staff_info:
    name = s_info['name']
    match = db_df[db_df['이름'] == name]
    r = match.iloc[0] if not match.empty else {}
    
    try: s_t, e_t = int(float(str(r.get('출근시간', 11)))), int(float(str(r.get('퇴근시간', 21))))
    except: s_t, e_t = 11, 21
    
    # 식사 시간 (H열 '식사시간' 우선, 없으면 조별 설정)
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

# --- 로테이션 엔진 (v70.3과 동일) ---
def run_rotation():
    schedule_df = pd.DataFrame(index=all_time_slots, columns=working_staff_names).fillna("-")
    counter_counts = {n: 0 for n in working_staff_names}
    last_pos = {n: "" for n in working_staff_names}
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    for slot in all_time_slots:
        hr = int(slot.split(":")[0])
        pool = []
        for n in working_staff_names:
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
                mi, ma = (map(int, raw_to.split('-')) if '-' in raw_to else (int(float(raw_to or 0)), int(float(raw_to or 0))))
                zone_cfg[z] = {"min": mi, "max": ma}

            for z in all_zones:
                needed = zone_cfg[z]["min"]
                assigned = 0
                eligible = [n for n in pool if not ("카운터" in z and not combined_settings[n]["can_counter"])]
                eligible.sort(key=lambda x: (counter_counts[x] if "카운터" in z else 0, last_pos[x] == z))
                for n in eligible:
                    if assigned < needed:
                        schedule_df.at[slot, n] = z
                        last_pos[n] = z
                        if "카운터" in z: counter_counts[n] += 1
                        if n in pool: pool.remove(n)
                        assigned += 1
            for z in all_zones:
                current_cnt = (schedule_df.loc[slot] == z).sum()
                needed_extra = zone_cfg[z]["max"] - current_cnt
                assigned_extra = 0
                eligible = [n for n in pool if not ("카운터" in z and not combined_settings[n]["can_counter"])]
                for n in eligible:
                    if assigned_extra < max(0, needed_extra):
                        schedule_df.at[slot, n] = z
                        last_pos[n] = z
                        if n in pool: pool.remove(n)
                        assigned_extra += 1
        for n in pool: schedule_df.at[slot, n] = "지원"
    return schedule_df

if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    st.session_state.result_df = run_rotation()

# --- 결과 출력 ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    edited = st.data_editor(res, use_container_width=True)
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    html = "<table style='width:100%; border-collapse: collapse; text-align: center; border: 1px solid #ddd;'>"
    html += "<tr style='background-color: #f8f9fa;'><th style='border: 1px solid #ddd; padding: 10px;'>시간</th>"
    for name in edited.columns:
        color = "#007bff" if combined_settings[name]["is_morning"] else "#e83e8c"
        html += f"<th style='border: 1px solid #ddd; padding: 10px; color: {color};'>{name}</th>"
    html += "</tr>"
    for slot, row in edited.iterrows():
        html += f"<tr><td style='border: 1px solid #ddd; padding: 8px; font-weight: bold;'>{slot}</td>"
        for val in row:
            bg = "background-color: #ffff00;" if val == "식사" else ""
            html += f"<td style='border: 1px solid #ddd; padding: 8px; {bg}'>{val}</td>"
        html += "</tr>"
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)

    # 📊 구역별 TO 준수 현황
    st.write("---")
    st.markdown("### 📊 구역별 TO 준수 현황")
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    check_data = []
    for slot in all_time_slots:
        row_data = {"시간": slot}
        to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        for z in all_zones:
            current = (edited.loc[slot] == z).sum()
            raw_to = str(to_row[z].iloc[0]).split('-')[0] if not to_row.empty else "0"
            try: mi = int(float(raw_to))
            except: mi = 0
            status = "✅" if current >= mi else "⚠️"
            row_data[z] = f"{status} {current}/{mi}"
        check_data.append(row_data)
    st.dataframe(pd.DataFrame(check_data).set_index("시간"), use_container_width=True)
