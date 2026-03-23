import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import random
import re
import json
from datetime import date
from io import BytesIO

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
    "하우스 서울": {
        "ID": "19CvEiqbhPqNpz2KzcBQh7vVaH40O_ZuR6MFYdw98c5Q",
        "DAY_TYPES": {
            "평일": {"DB_GID": "738722894", "TO_GID": "410487706"},
            "주말": {"DB_GID": "0", "TO_GID": "2126973547"},
        },
    },
    "하우스 도산": {
        "ID": "1nqSbhCPnO1o_vRSubJCuLjbbZxmtRMjioTtA_ZzzNLc",
        "DAY_TYPES": {
            "평일": {"DB_GID": "0", "TO_GID": "2126973547"},
            "주말": {"DB_GID": "0", "TO_GID": "2126973547"},
        },
    },
    "테스트": {
        "ID": "1qZp0-8sqjLN65gbLPObPDYVzNDuWZiPlik6FJAM3MWY",
        "DAY_TYPES": {
            "평일": {"DB_GID": "0", "TO_GID": "2126973547"},
            "주말": {"DB_GID": "0", "TO_GID": "2126973547"},
        },
    },
}

selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", list(STORES.keys()))
selected_day_type = st.sidebar.radio("📅 운영 구분", ["평일", "주말"], horizontal=True)

store_config = STORES[selected_store]
SHEET_ID = store_config["ID"]
day_type_config = store_config["DAY_TYPES"][selected_day_type]
DB_SHEET_GID = day_type_config["DB_GID"]
TO_SHEET_GID = day_type_config["TO_GID"]

@st.cache_data(ttl=1)
def load_sheet_data(sheet_id, gid):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    try:
        df = pd.read_csv(url, skip_blank_lines=True, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.fillna("").replace(r'\.0$', '', regex=True)
        return df
    except Exception as e:
        st.error(f"시트 로딩 실패: {e}")
        return pd.DataFrame()

db_df = load_sheet_data(SHEET_ID, DB_SHEET_GID)
to_df = load_sheet_data(SHEET_ID, TO_SHEET_GID)

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
    return "카운터" in zone or "COUNTER" in zone or "1F-C" in zone or "2F-C" in zone

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

def pick_best_staff(zone_name, pool, previous_assignments):
    if not pool:
        return None

    candidates = list(pool)
    random.shuffle(candidates)

    if is_support_zone(zone_name):
        non_support_last = [
            name for name in candidates
            if not is_support_zone(previous_assignments.get(name))
        ]
        if non_support_last:
            candidates = non_support_last
    else:
        from_support_last = [
            name for name in candidates
            if is_support_zone(previous_assignments.get(name))
        ]
        if from_support_last:
            candidates = from_support_last

    non_consecutive = [
        name for name in candidates if previous_assignments.get(name) != zone_name
    ]
    if non_consecutive:
        candidates = non_consecutive

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

pt_input_defaults = {
    s["original_name"]: {
        "in": s["in"] or "11:00",
        "out": s["out"] or "21:00",
        "meal": s["meal_p"] or "12:00",
    }
    for s in pt_list
}
pt_input_signature = json.dumps(
    {
        "store": selected_store,
        "day_type": selected_day_type,
        "defaults": pt_input_defaults,
    },
    ensure_ascii=False,
    sort_keys=True,
)

if st.session_state.get("pt_input_signature") != pt_input_signature:
    for pt_name, defaults in pt_input_defaults.items():
        st.session_state[f"in_{pt_name}"] = defaults["in"]
        st.session_state[f"out_{pt_name}"] = defaults["out"]
        st.session_state[f"meal_{pt_name}"] = defaults["meal"]
    st.session_state["pt_input_signature"] = pt_input_signature

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
            new_in = c1.text_input(f"출근", key=f"in_{pt_name}")
            new_out = c2.text_input(f"퇴근", key=f"out_{pt_name}")
            new_meal = st.text_input(f"식사", key=f"meal_{pt_name}")

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
        "day_type": selected_day_type,
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

    staff_lookup = {s['display_name']: s for s in final_staff_configs}
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
                        previous_assignments,
                    )
                    if not chosen:
                        break

                    schedule_df.at[slot, chosen] = z
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
                previous_assignments[n] = support_zone
                pool.remove(n)
    return schedule_df

if st.sidebar.button("🚀 로테이션 자동 생성", use_container_width=True):
    st.session_state.result_df = run_rotation()

# --- 화면 출력 ---
if 'result_df' in st.session_state:
    res = st.session_state.result_df
    st.write(f"### 📅 [{selected_store} / {selected_day_type}] 로테이션")
    display_df = res.transpose()
    display_df.index.name = "직원명"
    display_df_with_name = display_df.copy()
    display_df_with_name["직원명"] = display_df_with_name.index
    zone_columns = [c for c in to_df.columns if c != to_df.columns[0]]
    zone_choices = set(zone_columns)
    zone_choices.update(str(val).strip() for val in display_df.values.flatten() if str(val).strip())
    zone_choices.update(["식사", "1층 지원", "2층 지원", "-", ""])
    zone_choices = sorted(zone_choices)
    column_settings = {
        col: (
            st.column_config.SelectboxColumn(options=zone_choices)
            if col != "직원명"
            else st.column_config.TextColumn(label="직원명", disabled=True)
        )
        for col in display_df_with_name.columns
    }
    edited_df = st.data_editor(display_df_with_name, use_container_width=True, height=450, column_config=column_settings)
    csv_bytes = display_df_with_name.to_csv(index=True).encode('utf-8')
    file_name = f"rotation_{selected_store}_{selected_day_type}_{date.today():%Y%m%d}"
    st.download_button("📥 현재 배정 다운로드 (CSV)", data=csv_bytes, file_name=f"{file_name}.csv", mime="text/csv")
    with BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            display_df_with_name.to_excel(writer, index=True, sheet_name="rotation")
        buf.seek(0)
        st.download_button(
            "📥 현재 배정 다운로드 (Excel)",
            data=buf.getvalue(),
            file_name=f"{file_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    
    st.write("---")
    st.markdown("### 📸 모바일 공유용 현황판")
    def get_staff_color(name):
        s_info = next((s for s in final_staff_configs if s['display_name'] == name), None)
        if not s_info:
            return "#111827"
        if "(A조)" in name:
            return "#f97316"
        if "(B조)" in name:
            return "#2563eb"
        if s_info["type"] == '정직':
            return "#1d4ed8"
        return "#059669"

    def get_zone_background(value):
        text = str(value)
        low = text.lower()
        if "카운터" in low or "counter" in low:
            return "#ede9fe"
        if "2층" in low or "2f" in low:
            return "#fee2e2"
        if "1층" in low or "1f" in low:
            return "#dbeafe"
        return ""

    def build_table(df):
        table_html = "<table style='width:100%; border-collapse: collapse; text-align: center; border: 1px solid #ddd;'>"
        table_html += "<tr style='background-color: #f8f9fa;'><th style='border: 1px solid #ddd; padding: 10px;'>직원</th>"
        for time in df.columns:
            table_html += f"<th style='border: 1px solid #ddd; padding: 10px; font-weight: bold;'>{time}</th>"
        table_html += "</tr>"
        for staff, row in df.iterrows():
            color = get_staff_color(staff)
            table_html += f"<tr><td style='border: 1px solid #ddd; padding: 8px; font-weight: bold; color: {color};'>{staff}</td>"
            for col, val in row.items():
                bg = ""
                if str(val) == "식사":
                    bg = "background-color: #fff5ba;"
                else:
                    zone_color = get_zone_background(val)
                    if zone_color:
                        bg = f"background-color: {zone_color};"
                extra_style = f" color: {color};" if col == "직원명" else ""
                table_html += f"<td style='border: 1px solid #ddd; padding: 8px; {bg}{extra_style}'>{val}</td>"
            table_html += "</tr>"
        table_html += "</table>"
        return table_html

    table_html = build_table(edited_df)
    page_html = "<!doctype html><html lang='ko'><head><meta charset='utf-8'/><title>모바일 공유 현황판</title>"
    page_html += (
        "<style>"
        "html,body{height:100%;margin:0;padding:0;background:#fff;font-family:'Pretendard','Noto Sans KR',sans-serif;}"
        ".page-wrap{display:flex;flex-direction:column;height:100%;padding:16px;box-sizing:border-box;}"
        "h1{margin:0 0 12px;font-size:1.4rem;}"
        ".table-container{flex:1;overflow:hidden;border:1px solid #ddd;border-radius:12px;}"
        "table{width:100%;height:100%;border-collapse:collapse;font-size:0.95rem;}"
        "th,td{border:1px solid #ddd;padding:6px;text-align:center;vertical-align:middle;}"
        "</style>"
    )
    page_html += "</head><body><div class='page-wrap'><h1>모바일 공유 현황판</h1><div class='table-container'>"
    page_html += table_html
    page_html += "</div></div></body></html>"

    widget_html = f"""
    <div style='margin-bottom:8px;'>
        <button style='border:0; padding:10px 16px; font-weight:600; background:#111827; color:#fff; border-radius:8px; cursor:pointer;'
                onclick='openLargeRotation()'>🖥️ 크게 보기</button>
    </div>
    <script>
    const largeRotationContent = {json.dumps(page_html)};
    function openLargeRotation() {{
        const win = window.open('', '_blank');
        if (!win) return;
        win.document.write(largeRotationContent);
        win.document.close();
    }}
    </script>
    """
    components.html(widget_html, height=110)
    st.markdown(table_html, unsafe_allow_html=True)
