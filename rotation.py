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

st.title("GENTLE MONSTER 로테이션 시스템 v71.2")

# 🔗 매장 및 시트 설정
STORES = {
    "하우스 도산": {"ID": "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q", "TO_GID": "2126973547"},
    "하우스 서울": {"ID": "1nqSbhCPnO1o_vRSubJCuLjbbZxmtRMjioTtA_ZzzNLc", "TO_GID": "2126973547"},
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
        st.error(f"시트 로딩 실패 (공유 설정 확인): {e}")
        return pd.DataFrame()

db_df = load_sheet_data("0")
to_df = load_sheet_data(TO_SHEET_GID)

if db_df.empty: st.stop()

all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]

def get_clean_time(val):
    val = str(val).strip()
    if not val: return None
    nums = re.findall(r'\d+', val)
    return f"{int(nums[0]):02d}:00" if nums else None

# --- 데이터 파싱 (조 구분 추가) ---
def get_staff_info(data):
    type_col = next((c for c in data.columns if '구분' in c), '구분')
    name_col = next((c for c in data.columns if '이름' in c), '이름')
    res, seen = [], set()
    
    for _, row in data.iterrows():
        name = str(row.get(name_col, "")).strip()
        stype = str(row.get(type_col, "")).strip()
        
        if name and name not in seen and any(kw in stype for kw in ['정직', '파트']):
            s_val = get_clean_time(row.get('출근시간', '11'))
            s_hr = int(s_val.split(':')[0]) if s_val else 11
            e_val = get_clean_time(row.get('퇴근시간', '21'))
            e_hr = int(e_val.split(':')[0]) if e_val else 21
            
            # 조 구분 태그 생성
            group_tag = ""
            if s_hr <= 10: group_tag = "(A조)"
            elif s_hr == 11: group_tag = "(B조)"
            
            display_name = f"{name}{group_tag}"
            meals = [get_clean_time(row.get(c, '')) for c in ['점심', '저녁', '식사시간']]
            
            res.append({
                "original_name": name,
                "name": display_name, 
                "is_morning": s_hr < 12,
                "meals": list(set([m for m in meals if m])), 
                "range": range(s_hr, e_hr),
                "can_counter": any(x in str(row.get('카운터여부', 'X')).lower() for x in ['o', 'y', '1', 'v', '예'])
            })
            seen.add(name)
    return res

all_staff_data = get_staff_info(db_df)

# --- 사이드바 ---
st.sidebar.header("🕹️ 인원 관리")
working_staff_info = [s for s in all_staff_data] # 테스트를 위해 전체 포함 로직 유지
working_staff_names = [s['name'] for s in working_staff_info]

# --- 로테이션 엔진 (층별 균등 배분 최적화) ---
def run_rotation():
    schedule_df = pd.DataFrame(index=all_time_slots, columns=working_staff_names).fillna("-")
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    # 층 구분 로직 (구역 이름에 '1F' 또는 '1층' 포함 여부)
    f1_zones = [z for z in all_zones if '1F' in z or '1층' in z]
    f2_zones = [z for z in all_zones if '2F' in z or '2층' in z]
    
    counter_counts = {n: 0 for n in working_staff_names}
    
    for slot in all_time_slots:
        hr = int(slot.split(":")[0])
        pool = []
        for s in working_staff_info:
            if slot in s["meals"]: schedule_df.at[slot, s['name']] = "식사"
            elif hr in s["range"]: pool.append(s['name'])
            else: schedule_df.at[slot, s['name']] = " "
        
        random.shuffle(pool)
        to_row = to_df[to_df[to_df.columns[0]].str.contains(slot, na=False)]
        
        if not to_row.empty:
            # 1단계: 최소 TO 배정 (층 균등 고려 위해 순서 섞음)
            active_zones = [z for z in all_zones if str(to_row[z].iloc[0]).strip() != "0"]
            for z in active_zones:
                raw = str(to_row[z].iloc[0]).strip()
                mi = int(raw.split('-')[0]) if '-' in raw else int(float(raw or 0))
                
                assigned = 0
                eligible = [n for n in pool if not ("카운터" in z and not next(s for s in working_staff_info if s['name']==n)["can_counter"])]
                for n in eligible:
                    if assigned < mi:
                        schedule_df.at[slot, n] = z
                        if "카운터" in z: counter_counts[n] += 1
                        pool.remove(n)
                        assigned += 1

            # 2단계: 남은 인원(지원) 층별 균등 배분
            for n in list(pool):
                f1_count = (schedule_df.loc[slot] == "1층 지원").sum() + sum([1 for z in f1_zones if schedule_df.at[slot, n] == z])
                f2_count = (schedule_df.loc[slot] == "2층 지원").sum() + sum([1 for z in f2_zones if schedule_df.at[slot, n] == z])
                
                if f1_count <= f2_count:
                    schedule_df.at[slot, n] = "1층 지원"
                else:
                    schedule_df.at[slot, n] = "2층 지원"
                pool.remove(n)
                
    return schedule_df

if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    st.session_state.result_df = run_rotation()

# --- 화면 출력 ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    st.write(f"### 📅 [{selected_store}] 로테이션 결과 (A/B조 자동구분)")
    edited_df = st.data_editor(res, use_container_width=True, height=450)
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    
    html = "<table style='width:100%; border-collapse: collapse; text-align: center; border: 1px solid #ddd;'>"
    html += "<tr style='background-color: #f8f9fa;'><th style='border: 1px solid #ddd; padding: 10px;'>시간</th>"
    for name in edited_df.columns:
        s_info = next((s for s in working_staff_info if s['name'] == name), None)
        color = "#007bff" if s_info and s_info["is_morning"] else "#e83e8c"
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
