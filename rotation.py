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

st.title("GENTLE MONSTER 로테이션 시스템 v71.4")

# 🔗 매장 및 시트 설정
STORES = {
    "하우스 서울": {"ID": "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q", "TO_GID": "2126973547"},
    "하우스 도산": {"ID": "1nqSbhCPnO1o_vRSubJCuLjbbZxmtRMjioTtA_ZzzNLc", "TO_GID": "2126973547"},
    "테스트": {"ID": "1qZp0-8sqjLN65gbLPObPDYVzNDuWZiPlik6FJAM3MWY", "TO_GID": "2126973547"}
}

selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", list(STORES.keys()))
SHEET_ID = STORES[selected_store]["ID"]
TO_SHEET_GID = STORES[selected_store]["TO_GID"]

@st.cache_data(ttl=1)
def load_sheet_data(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        df = pd.read_csv(url, skip_blank_lines=True, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.fillna("").replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        st.error(f"시트 로딩 실패: {e}")
        return pd.DataFrame()

db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty: st.stop()

def get_clean_time(val):
    val = str(val).strip()
    if not val: return None
    nums = re.findall(r'\d+', val)
    return f"{int(nums[0]):02d}:00" if nums else None

# --- 기본 데이터 파싱 ---
def get_initial_staff(data):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    res = []
    for _, row in data.iterrows():
        name = str(row.get(name_col, "")).strip()
        stype = str(row.get(type_col, "")).strip()
        if name and any(kw in stype for kw in ['정직', '파트']):
            res.append({
                "original_name": name,
                "type": '정직' if '정직' in stype else '파트',
                "in": get_clean_time(row.get('출근시간', '11')),
                "out": get_clean_time(row.get('퇴근시간', '21')),
                "meal1": get_clean_time(row.get('점심', '')),
                "meal2": get_clean_time(row.get('저녁', '')),
                "meal_p": get_clean_time(row.get('식사시간', '')),
                "can_counter": any(x in str(row.get('카운터여부', 'X')).lower() for x in ['o', 'y', '1', 'v', '예'])
            })
    return res

raw_staff = get_initial_staff(db_df)

# --- 사이드바: 파트타이머 상세 조정 ---
st.sidebar.header("🕹️ 인원 관리")
pt_list = [s for s in raw_staff if s['type'] == '파트']
selected_pt_names = st.sidebar.multiselect("⏱️ 출근 파트타이머 선택", [s['original_name'] for s in pt_list], default=[s['original_name'] for s in pt_list])

final_staff_configs = []

# 1. 정직원 처리 (조 이름 포함)
for s in [x for x in raw_staff if x['type'] == '정직']:
    in_hr = int(s['in'].split(':')[0]) if s['in'] else 11
    tag = "(A조)" if in_hr <= 10 else "(B조)"
    s['display_name'] = f"{s['original_name']}{tag}"
    s['meals'] = list(set([m for m in [s['meal1'], s['meal2']] if m]))
    s['work_range'] = range(in_hr, int(s['out'].split(':')[0]) if s['out'] else 21)
    final_staff_configs.append(s)

# 2. 파트타이머 처리 (조 이름 제외 + 사이드바 조정값 반영)
if selected_pt_names:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📋 파트타이머 시간 조정")
    for pt_name in selected_pt_names:
        pt_origin = next(s for s in pt_list if s['original_name'] == pt_name)
        with st.sidebar.expander(f"👤 {pt_name}"):
            c1, c2 = st.columns(2)
            new_in = c1.text_input(f"출근", value=pt_origin['in'] or "11:00", key=f"in_{pt_name}")
            new_out = c2.text_input(f"퇴근", value=pt_origin['out'] or "21:00", key=f"out_{pt_name}")
            new_meal = st.text_input(f"식사", value=pt_origin['meal_p'] or "12:00", key=f"meal_{pt_name}")
            
            pt_copy = pt_origin.copy()
            pt_copy['display_name'] = pt_name # 조 태그 없음
            pt_copy['meals'] = [get_clean_time(new_meal)] if get_clean_time(new_meal) else []
            pt_copy['work_range'] = range(int(get_clean_time(new_in).split(':')[0]), int(get_clean_time(new_out).split(':')[0]))
            final_staff_configs.append(pt_copy)

# --- 로테이션 엔진 ---
def run_rotation():
    working_names = [s['display_name'] for s in final_staff_configs]
    all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]
    schedule_df = pd.DataFrame(index=all_time_slots, columns=working_names).fillna("-")
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    f1_zones = [z for z in all_zones if any(kw in z for kw in ['1F', '1층'])]
    f2_zones = [z for z in all_zones if any(kw in z for kw in ['2F', '2층'])]
    
    counter_counts = {n: 0 for n in working_names}

    for slot in all_time_slots:
        hr = int(slot.split(":")[0])
        pool = []
        for s in final_staff_configs:
            if slot in s["meals"]: schedule_df.at[slot, s['display_name']] = "식사"
            elif hr in s["work_range"]: pool.append(s['display_name'])
            else: schedule_df.at[slot, s['display_name']] = " "
        
        random.shuffle(pool)
        to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        
        if not to_row.empty:
            active_zones = [z for z in all_zones if str(to_row[z].iloc[0]).strip() != "0"]
            for z in active_zones:
                raw = str(to_row[z].iloc[0]).strip()
                mi = int(raw.split('-')[0]) if '-' in raw else int(float(raw or 0))
                assigned = 0
                eligible = [n for n in pool if not ("카운터" in z and not next(s for s in final_staff_configs if s['display_name']==n)["can_counter"])]
                for n in eligible:
                    if assigned < mi:
                        schedule_df.at[slot, n], assigned = z, assigned + 1
                        if "카운터" in z: counter_counts[n] += 1
                        pool.remove(n)

            for n in list(pool): # 층별 균등 지원 배정
                f1_cnt = (schedule_df.loc[slot] == "1층 지원").sum() + sum([1 for z in f1_zones if schedule_df.at[slot, n] == z])
                f2_cnt = (schedule_df.loc[slot] == "2층 지원").sum() + sum([1 for z in f2_zones if schedule_df.at[slot, n] == z])
                schedule_df.at[slot, n] = "1층 지원" if f1_cnt <= f2_cnt else "2층 지원"
                pool.remove(n)
    return schedule_df

if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    st.session_state.result_df = run_rotation()

# --- 화면 출력 ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    st.write(f"### 📅 [{selected_store}] 로테이션")
    edited_df = st.data_editor(res, use_container_width=True, height=450)
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    html = "<table style='width:100%; border-collapse: collapse; text-align: center; border: 1px solid #ddd;'>"
    html += "<tr style='background-color: #f8f9fa;'><th style='border: 1px solid #ddd; padding: 10px;'>시간</th>"
    for name in edited_df.columns:
        s_info = next((s for s in final_staff_configs if s['display_name'] == name), None)
        color = "#007bff" if s_info and s_info["type"] == '정직' and s_info["in"] <= "10:00" else "#e83e8c"
        html += f"<th style='border: 1px solid #ddd; padding: 10px; color: {color}; font-weight: bold;'>{name}</th>"
    html += "</tr>"
    for slot, row in edited_df.iterrows():
        html += f"<tr><td style='border: 1px solid #ddd; padding: 8px; font-weight: bold;'>{slot}</td>"
        for val in row:
            bg = "background-color: #ffff00;" if val == "식사" else ""
            html += f"<td style='border: 1px solid #ddd; padding: 8px; {bg}'>{val}</td>"
        html += "</tr>"
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)
