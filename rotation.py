import streamlit as st
import pandas as pd
import random
import re

# 1. 페이지 설정
st.set_page_config(page_title="GM Manager Central", layout="wide")

st.markdown("""
    <style>
    .meal-bg { background-color: #ffff00 !important; color: black !important; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("GENTLE MONSTER 로테이션 시스템 v70.5")

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

def format_time(val):
    """'13', '13:00' 등을 '13:00'으로 통일"""
    nums = re.sub(r'[^0-9]', '', str(val))
    if nums:
        hour = int(nums[:2])
        return f"{hour:02d}:00"
    return None

def get_staff_info(data):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    res, seen = [], set()
    for _, row in data.iterrows():
        name = str(row[name_col]).strip()
        stype = str(row[type_col]).strip()
        if name and name not in seen and (stype in ['정직', '파트']):
            try: is_morning = int(float(row.get('출근시간', 11))) < 12
            except: is_morning = True
            
            # 식사 시간 파싱
            meals = []
            if '정직' in stype:
                m1 = format_time(row.get('점심조', ''))
                m2 = format_time(row.get('저녁조', ''))
                if m1: meals.append(m1)
                if m2: meals.append(m2)
            else: # 파트
                pm = format_time(row.get('식사시간', ''))
                if pm: meals.append(pm)
                
            res.append({
                "name": name, 
                "is_morning": is_morning, 
                "type": stype,
                "default_meals": meals,
                "range": range(int(float(row.get('출근시간', 11))), int(float(row.get('퇴근시간', 21)))),
                "can_counter": any(x in str(row.get('카운터여부', 'X')).lower() for x in ['o', 'y', '1', 'v', '예'])
            })
            seen.add(name)
    return res

all_staff_data = get_staff_info(db_df)

# --- 사이드바 ---
st.sidebar.header("🕹️ 인원 및 식사 관리")
ft_data = [s for s in all_staff_data if '정직' in s['type']]
pt_data = [s for s in all_staff_data if '파트' in s['type']]

# 1. 파트타이머 출근 선택
selected_pt_names = st.sidebar.multiselect("⏱️ 오늘 출근 파트타이머", [s['name'] for s in pt_data], default=[s['name'] for s in pt_data])

# 2. 파트타이머 식사 시간 조정 (선택된 인원만 표시)
pt_meal_overrides = {}
if selected_pt_names:
    with st.sidebar.expander("🍴 파트타이머 식사 조정"):
        for name in selected_pt_names:
            p_info = next(s for s in pt_data if s['name'] == name)
            default_val = p_info['default_meals'][0] if p_info['default_meals'] else all_time_slots[2]
            # 인덱스 안전 처리
            try: d_idx = all_time_slots.index(default_val)
            except: d_idx = 2
            new_meal = st.selectbox(f"{name} 식사", all_time_slots, index=d_idx, key=f"pt_meal_{name}")
            pt_meal_overrides[name] = [new_meal]

# 최종 근무 인원 세팅
working_staff_info = []
for s in all_staff_data:
    if '정직' in s['type'] or s['name'] in selected_pt_names:
        if s['name'] in pt_meal_overrides:
            s['meals'] = pt_meal_overrides[s['name']]
        else:
            s['meals'] = s['default_meals']
        working_staff_info.append(s)

working_staff_names = [s['name'] for s in working_staff_info]

# --- 로테이션 엔진 ---
def run_rotation():
    schedule_df = pd.DataFrame(index=all_time_slots, columns=working_staff_names).fillna("-")
    counter_counts = {n: 0 for n in working_staff_names}
    last_pos = {n: "" for n in working_staff_names}
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    for slot in all_time_slots:
        hr = int(slot.split(":")[0])
        pool = []
        for s in working_staff_info:
            if hr in s["range"]:
                if slot in s["meals"]: schedule_df.at[slot, s['name']] = "식사"
                else: pool.append(s['name'])
            else: schedule_df.at[slot, s['name']] = " "
        
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
                eligible = [n for n in pool if not ("카운터" in z and not next(s for s in working_staff_info if s['name']==n)["can_counter"])]
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
                eligible = [n for n in pool if not ("카운터" in z and not next(s for s in working_staff_info if s['name']==n)["can_counter"])]
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

# --- 화면 출력 (현황판 + TO 준수 대시보드) ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    edited = st.data_editor(res, use_container_width=True)
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    html = "<table style='width:100%; border-collapse: collapse; text-align: center; border: 1px solid #ddd;'>"
    html += "<tr style='background-color: #f8f9fa;'><th style='border: 1px solid #ddd; padding: 10px;'>시간</th>"
    for name in edited.columns:
        s_info = next(s for s in working_staff_info if s['name'] == name)
        color = "#007bff" if s_info["is_morning"] else "#e83e8c"
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
