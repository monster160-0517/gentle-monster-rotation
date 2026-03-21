import streamlit as st
import pandas as pd
import random
import re
import json

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

def get_hour_from_time(val, default=None):
    clean = get_clean_time(val)
    if not clean:
        return default
    return int(clean.split(":")[0])

def build_work_range(in_val, out_val, default_in=11, default_out=21):
    in_hr = get_hour_from_time(in_val, default_in)
    out_hr = get_hour_from_time(out_val, default_out)
    if in_hr is None or out_hr is None:
        return None, None, None
    if out_hr <= in_hr:
        return None, in_hr, out_hr
    return range(in_hr, out_hr), in_hr, out_hr

def is_counter_zone(zone_name):
    zone = str(zone_name).upper()
    return "카운터" in zone or "COUNTER" in zone or "1F-C" in zone

def is_support_zone(zone_name):
    zone = str(zone_name)
    return "지원" in zone

def get_zone_category(zone_name):
    zone = str(zone_name).upper()
    if is_counter_zone(zone_name):
        return "counter"
    if "2F" in zone or "2층" in zone:
        return "2f"
    if "1F" in zone or "1층" in zone:
        return "1f"
    return "other"

def get_zone_priority(zone_name):
    if is_counter_zone(zone_name):
        return 0
    if is_support_zone(zone_name):
        return 2
    return 1

def pick_best_staff(zone_name, pool, staff_lookup, zone_category_counts, previous_assignments):
    if not pool:
        return None

    random.shuffle(pool)
    category = get_zone_category(zone_name)

    non_consecutive = [
        name for name in pool if previous_assignments.get(name) != zone_name
    ]
    candidates = non_consecutive if non_consecutive else list(pool)

    candidates.sort(
        key=lambda name: (
            zone_category_counts[name].get(category, 0),
            sum(zone_category_counts[name].values()),
            name,
        )
    )

    return candidates[0] if candidates else None

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
    work_range, in_hr, out_hr = build_work_range(s['in'], s['out'])
    if work_range is None:
        continue
    tag = "(A조)" if in_hr <= 10 else "(B조)"
    s['display_name'] = f"{s['original_name']}{tag}"
    s['meals'] = list(set([m for m in [s['meal1'], s['meal2']] if m]))
    s['work_range'] = work_range
    s['in'] = f"{in_hr:02d}:00"
    s['out'] = f"{out_hr:02d}:00"
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
            work_range, in_hr, out_hr = build_work_range(new_in, new_out)

            if work_range is None:
                st.warning(f"{pt_name}: 출근/퇴근 시간을 다시 확인해 주세요.")
                continue

            pt_copy['display_name'] = pt_name # 조 태그 없음
            pt_copy['in'] = f"{in_hr:02d}:00"
            pt_copy['out'] = f"{out_hr:02d}:00"
            pt_copy['meal_p'] = get_clean_time(new_meal)
            pt_copy['meals'] = [pt_copy['meal_p']] if pt_copy['meal_p'] else []
            pt_copy['work_range'] = work_range
            final_staff_configs.append(pt_copy)

config_signature = json.dumps(
    {
        "store": selected_store,
        "staff": [
            {
                "name": s["display_name"],
                "type": s["type"],
                "in": s.get("in"),
                "out": s.get("out"),
                "meals": s.get("meals", []),
                "can_counter": s.get("can_counter", False),
            }
            for s in final_staff_configs
        ],
    },
    ensure_ascii=False,
    sort_keys=True,
)

if st.session_state.get("config_signature") != config_signature:
    st.session_state.pop("result_df", None)
    st.session_state["config_signature"] = config_signature

# --- 로테이션 엔진 ---
def run_rotation():
    working_names = [s['display_name'] for s in final_staff_configs]
    all_time_slots = [f"{h:02d}:00" for h in range(11, 21)]
    schedule_df = pd.DataFrame(index=all_time_slots, columns=working_names).fillna("-")
    all_zones = [c for c in to_df.columns if c != to_df.columns[0]]
    
    f1_zones = [z for z in all_zones if any(kw in z for kw in ['1F', '1층'])]
    f2_zones = [z for z in all_zones if any(kw in z for kw in ['2F', '2층'])]
    
    staff_lookup = {s['display_name']: s for s in final_staff_configs}
    zone_category_counts = {
        n: {"counter": 0, "1f": 0, "2f": 0, "other": 0}
        for n in working_names
    }
    previous_assignments = {n: None for n in working_names}

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
            sorted_active_zones = sorted(active_zones, key=lambda z: (get_zone_priority(z), all_zones.index(z)))

            for z in sorted_active_zones:
                raw = str(to_row[z].iloc[0]).strip()
                mi = int(raw.split('-')[0]) if '-' in raw else int(float(raw or 0))
                assigned = 0
                while assigned < mi:
                    eligible = [
                        n for n in pool
                        if not (is_counter_zone(z) and not staff_lookup[n]["can_counter"])
                    ]
                    chosen = pick_best_staff(
                        z,
                        eligible,
                        staff_lookup,
                        zone_category_counts,
                        previous_assignments,
                    )
                    if not chosen:
                        break

                    schedule_df.at[slot, chosen] = z
                    zone_category_counts[chosen][get_zone_category(z)] += 1
                    previous_assignments[chosen] = z
                    assigned += 1
                    pool.remove(chosen)

            for n in list(pool): # 층별 균등 지원 배정
                current_assignments = [
                    val for val in schedule_df.loc[slot].tolist()
                    if str(val).strip() not in ["-", "", " ", "식사"]
                ]
                f1_cnt = sum(1 for val in current_assignments if get_zone_category(val) == "1f")
                f2_cnt = sum(1 for val in current_assignments if get_zone_category(val) == "2f")
                support_zone = "1층 지원" if f1_cnt <= f2_cnt else "2층 지원"

                if previous_assignments.get(n) == support_zone:
                    support_zone = "2층 지원" if support_zone == "1층 지원" else "1층 지원"

                schedule_df.at[slot, n] = support_zone
                zone_category_counts[n][get_zone_category(support_zone)] += 1
                previous_assignments[n] = support_zone
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
