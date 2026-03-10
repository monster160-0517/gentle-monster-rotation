import streamlit as st
import pandas as pd
import random

# 1. 페이지 설정 및 데이터 로드
st.set_page_config(page_title="GM Manager Central", layout="wide")
st.title("🕶️ GENTLE MONSTER 전사 통합 로테이션 (v23.0)")

SHEET_ID = "여기에_실제_시트_ID_입력" 
SHEET_NAME = "Sheet1" 
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

@st.cache_data(ttl=1)
def load_db():
    try:
        df = pd.read_csv(url)
        df.columns = [str(c).strip() for c in df.columns]
        # 모든 데이터의 앞뒤 공백 제거
        return df.apply(lambda x: x.astype(str).str.strip() if x.dtype == "object" else x)
    except: return pd.DataFrame()

db_df = load_db()

if db_df.empty:
    st.error("❌ 데이터를 가져오지 못했습니다. 공유 설정을 확인하세요.")
    st.stop()

# ⭐ 강력 조치: '이름' 열이 비어있으면 옆 칸에서라도 이름을 찾아냅니다.
def get_clean_data(df):
    # 첫 번째 열을 매장명으로 고정
    df.rename(columns={df.columns[0]: '매장명'}, inplace=True)
    # 'nan' 문자열을 실제 빈값으로 변경
    df = df.replace('nan', None)
    return df

db_df = get_clean_data(db_df)

# 2. 매장 및 구역 설정
store_list = sorted(db_df['매장명'].unique())
selected_store = st.sidebar.selectbox("🏠 담당 매장 선택", store_list)
store_data = db_df[db_df['매장명'] == selected_store].copy()

# 구역 자동 로드
zone_col = '운영구역' if '운영구역' in store_data.columns else store_data.columns[-1]
default_zones = str(store_data[zone_col].iloc[0]) if not store_data[zone_col].dropna().empty else "카운터, A, B, C"
zone_input = st.sidebar.text_input("📍 운영 구역", default_zones)
target_zones = [z.strip() for z in zone_input.split(",") if z.strip()]

# 3. 이름 찾기 로직 (⭐ 핵심 업데이트)
def extract_names(data, category):
    # '구분' 열에서 카테고리(정직원/파트타이머)를 찾음
    type_col = '구분' if '구분' in data.columns else data.columns[2]
    filtered = data[data[type_col].str.contains(category, na=False)]
    
    names = []
    for _, row in filtered.iterrows():
        # '이름' 열이 비어있으면 행 전체에서 글자가 있는 칸을 탐색
        name = row.get('이름')
        if not name or str(name).lower() == 'none':
            # 행의 값들 중 매장명, 구분, 운영구역을 제외하고 남은 글자를 이름으로 간주
            potential_names = [str(v) for v in row.values if str(v) not in [selected_store, category, default_zones] and len(str(v)) > 0]
            name = potential_names[0] if potential_names else "이름없음"
        names.append(name)
    return [n for n in names if str(n).lower() != 'none']

all_ft = extract_names(store_data, '정직원')
all_pt = extract_names(store_data, '파트타이머')

# ... (이하 로테이션 생성 로직 v22.1과 동일)
# [페이지 하단에 working_ft, working_pt 멀티셀렉트와 generate 버튼 코드를 유지해 주세요]
