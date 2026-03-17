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

st.title("GENTLE MONSTER 로테이션 시스템 v70.8")

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
        df = pd.read_csv(url, skip_blank_lines=True, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.fillna("").replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        st.error(f"시트 로딩 에러: {e}")
        return pd.DataFrame()

db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty:
    st.error("⚠️ 인원 정보 데이터를 불러오지 못했습니다.")
    st.stop()

all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]

# --- 시간 형식 통일 함수 ---
def get_clean_time(val):
    val = str(val).strip()
    if not val or val == "": return None
    # 숫자만 추출 (예: "11:00" -> 11, "13" -> 13)
    nums = re.findall(r'\d+', val)
    if nums:
        hr = int(nums[0])
        return f"{hr:02d}:00"
    return None

# --- 데이터 파싱 (이미지 컬럼명 기준) ---
def get_staff_info(data):
    # 컬럼 존재 여부와 관계없이 유연하게 매칭
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    
    res, seen = [], set()
    for _, row in data.iterrows():
        name = str(row.get(name_col, "")).strip()
        stype = str(row.get(type_col, "")).strip()
        
        if name and name not in seen and (any(kw in stype for kw in ['정직', '파트'])):
            # 출퇴근 시간
            try:
                s_val = get_clean_time(row.get('출근시간', '11'))
                s_hr = int(s_val.split(':')[0]) if s_val else 11
                e_val = get_clean_time(row.get('퇴근시간', '21'))
                e_hr = int(e_val.split(':')[0]) if e_val else 21
            except: s_hr, e_hr = 11, 21
            
            # 식사 시간 (이미지 기준: 점심, 저녁, 식사시간)
            staff_meals = []
            m1 = get_clean_time(row.get('점심', ''))
            m2 = get_clean_time(row.get('저녁', ''))
            m_fixed = get_clean_time(row.get('식사시간', ''))
            
            if m1: staff_meals.append(m1)
            if m2: staff_meals.append(m2)
            if m_fixed: staff_meals.append(m_fixed)
                
            res.append({
                "name": name, 
                "is_morning": s_hr < 12, 
                "type": '정직' if '정직' in stype else '파트',
                "meals": list(set(staff_meals)), 
                "range": range(s_hr, e_hr),
                "can_counter": any(x in str(row.get('카운터여부', 'X')).lower() for x in ['o', 'y', '1', 'v', '예'])
            })
            seen.add(name)
    return res

all_staff_data = get_staff_info(db_df)

# --- 사이드바 ---
st.sidebar.header("🕹️ 인원 관리")
pt_data = [s for s in all_staff_data if s['type'] == '파트']
selected_pt_names = st.sidebar.multiselect("⏱️ 오늘 출근 파트타이머", [s['name'] for s in pt_data], default=[s['name'] for s in pt_data])

working_staff_info = [s for s in all_staff_data if s['type'] == '정직' or s['name'] in selected_pt_names]
working_staff_names = [s['name'] for s in working_staff_info]

# --- 생성 버튼 및 엔진 ---
if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    if not working_staff_names:
        st.error("근무할 인원이 없습니다.")
    else:
        def run_rotation():
            schedule_df = pd.DataFrame(index=all_time_slots, columns=working_staff_names).fillna("-")
            counter_counts = {n: 0 for n in working_staff_names}
            last_pos = {n: "" for n in working_staff_names}
            all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
            
            for slot in all_time_slots:
                hr = int(slot.split(":")[0])
                pool = []
                for s in working_staff_info:
                    if slot in s["meals"]:
                        schedule_df.at[slot, s['name']] = "식사"
                    elif hr in s["range"]:
                        pool.append(s['name'])
                    else:
                        schedule_df.at[slot, s['name']] = " "
                
                random.shuffle(pool)
                to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
                
                if not to_row.empty:
                    zone_cfg = {}
                    for z in all_zones:
                        raw = str(to_row[z].iloc[0]).strip()
                        if '-' in raw:
                            mi, ma = map(int, raw.split('-'))
                        else:
                            val = int(float(raw)) if raw and raw.replace('.','').isdigit() else 0
                            mi = ma = val
                        zone_cfg[z] = {"min": mi, "max": ma}

                    # 최소 배정 -> 최대 배정 순 (생략 없이 v70.7 로직 유지)
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
                        current = (schedule_df.loc[slot] == z).sum()
                        needed_extra = zone_cfg[z]["max"] - current
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

        st.session_state.result_df = run_rotation()

# --- 화면 출력 ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    st.write(f"### 📅 로테이션 결과")
    edited = st.data_editor(res, use_container_width=True)
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    html = "<table style='width:100%; border-collapse: collapse; text-align: center; border: 1px solid #ddd;'>"
    html += "<tr style='background-color: #f8f9fa;'><th style='border: 1px solid #ddd; padding: 10px;'>시간</th>"
    for name in edited.columns:
        s_info = next((s for s in working_staff_info if s['name'] == name), None)
        color = "#007bff" if s_info and s_info["is_morning"] else "#e83e8c"
        html += f"<th style='border: 1px solid #ddd; padding: 10px; color: {color}; font-weight: bold;'>{name}</th>"
    html += "</tr>"
    for slot, row in edited.iterrows():
        html += f"<tr><td style='border: 1px solid #ddd; padding: 8px; font-weight: bold;'>{slot}</td>"
        for val in row:
            bg = "background-color: #ffff00;" if val == "식사" else ""
            html += f"<td style='border: 1px solid #ddd; padding: 8px; {bg}'>{val}</td>"
        html += "</tr>"
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)
