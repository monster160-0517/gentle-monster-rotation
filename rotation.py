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

st.title("GENTLE MONSTER 로테이션 시스템 v70.6")

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
        # 파일 로딩 시 에러 방지를 위해 문자열로 강제 로드
        df = pd.read_csv(url, skip_blank_lines=True, dtype=str)
        # 컬럼명 공백 제거
        df.columns = [str(c).strip() for c in df.columns]
        # NaN 및 소수점 처리
        df = df.fillna("").replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        st.error(f"시트 로딩 에러: {e}")
        return pd.DataFrame()

db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

# 데이터가 비어있을 경우 경고
if db_df.empty:
    st.error("⚠️ 인원 정보(db_df)가 비어있습니다. 구글 시트의 첫 번째 탭을 확인해주세요.")
    st.stop()

all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]

def format_time(val):
    if not val or str(val).strip() == "": return None
    nums = re.sub(r'[^0-9]', '', str(val))
    if nums:
        hour = int(nums[:2])
        return f"{hour:02d}:00"
    return None

# --- 데이터 파싱 (강화된 버전) ---
def get_staff_info(data):
    # 컬럼명을 유연하게 찾기 (구분, 이름 포함하는 열)
    type_col = next((c for c in data.columns if '구분' in c), None)
    name_col = next((c for c in data.columns if '이름' in c), None)
    
    if not type_col or not name_col:
        st.error(f"시트에서 '구분' 또는 '이름' 열을 찾을 수 없습니다. 현재 컬럼: {list(data.columns)}")
        return []

    res, seen = [], set()
    for _, row in data.iterrows():
        name = str(row[name_col]).strip()
        stype = str(row[type_col]).strip()
        
        # '정직' 또는 '파트'가 포함된 모든 행 가져오기 (매장명 필터 일시 해제)
        if name and name not in seen and (any(kw in stype for kw in ['정직', '파트'])):
            try: 
                s_val = str(row.get('출근시간', '11'))
                s_time = int(float(s_val)) if s_val else 11
                e_val = str(row.get('퇴근시간', '21'))
                e_time = int(float(e_val)) if e_val else 21
            except: s_time, e_time = 11, 21
            
            # 식사 시간 파싱
            meals = []
            if '정직' in stype:
                m1 = format_time(row.get('점심조', ''))
                m2 = format_time(row.get('저녁조', ''))
                if m1: meals.append(m1)
                if m2: meals.append(m2)
            else:
                pm = format_time(row.get('식사시간', ''))
                if pm: meals.append(pm)
                
            res.append({
                "name": name, 
                "is_morning": s_time < 12, 
                "type": '정직' if '정직' in stype else '파트',
                "default_meals": meals,
                "range": range(s_time, e_time),
                "can_counter": any(x in str(row.get('카운터여부', 'X')).lower() for x in ['o', 'y', '1', 'v', '예'])
            })
            seen.add(name)
    return res

all_staff_data = get_staff_info(db_df)

# --- 사이드바 ---
st.sidebar.header("🕹️ 인원 및 식사 관리")
ft_data = [s for s in all_staff_data if s['type'] == '정직']
pt_data = [s for s in all_staff_data if s['type'] == '파트']

selected_pt_names = st.sidebar.multiselect(
    "⏱️ 오늘 출근 파트타이머", 
    [s['name'] for s in pt_data], 
    default=[s['name'] for s in pt_data]
)

# 식사 시간 조정 패널
pt_meal_overrides = {}
if selected_pt_names:
    with st.sidebar.expander("🍴 파트타이머 식사 조정"):
        for name in selected_pt_names:
            p_info = next(s for s in pt_data if s['name'] == name)
            default_val = p_info['default_meals'][0] if p_info['default_meals'] else "15:00"
            try: d_idx = all_time_slots.index(default_val)
            except: d_idx = 4
            new_meal = st.selectbox(f"{name} 식사", all_time_slots, index=d_idx, key=f"pt_m_{name}")
            pt_meal_overrides[name] = [new_meal]

# 최종 근무 인원 확정
working_staff_info = []
for s in all_staff_data:
    if s['type'] == '정직' or s['name'] in selected_pt_names:
        s_copy = s.copy()
        if s['name'] in pt_meal_overrides:
            s_copy['meals'] = pt_meal_overrides[s['name']]
        else:
            s_copy['meals'] = s['default_meals']
        working_staff_info.append(s_copy)

working_staff_names = [s['name'] for s in working_staff_info]

# --- 생성 버튼 및 엔진 ---
if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    if not working_staff_names:
        st.error("근무할 인원이 없습니다.")
    else:
        # 로테이션 엔진 가동 (기존 v70.5 로직 유지)
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
                        if '-' in raw_to: mi, ma = map(int, raw_to.split('-'))
                        else: 
                            val = int(float(raw_to)) if raw_to and raw_to.replace('.','').isdigit() else 0
                            mi = ma = val
                        zone_cfg[z] = {"min": mi, "max": ma}

                    # 최소 TO 배정
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
                    # 최대 TO 배정
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

        st.session_state.result_df = run_rotation()

# --- 화면 출력 ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    st.write(f"### 📅 [{selected_store}] 로테이션 결과")
    edited = st.data_editor(res, use_container_width=True)
    
    # 📸 모바일용 (HTML)
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
