import streamlit as st
import yfinance as yf
import pandas as pd
import os
import time
import requests
import json
import altair as alt
from datetime import datetime

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 데이터 입출력 엔진 (통합 관리형)
# ==========================================
DB_FILE = 'internal_memory.csv' 
MAX_TOTAL_UNITS = 10       
MAX_UNIT_PER_STOCK = 3     

def load_data():
    """CSV에서 전략 태그를 포함한 전체 포지션 로드"""
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            positions = {}
            for _, row in df.iterrows():
                # 이전 버전 파일과의 호환성을 위해 기본값(Strategy) 처리
                history = json.loads(row['History']) if pd.notna(row['History']) else []
                positions[row['Ticker']] = {
                    'Units': int(row['Units']),
                    'Highest': float(row['Highest']),
                    'History': history,
                    'Strategy': row['Strategy'] if 'Strategy' in df.columns else '🚀 터틀-상승'
                }
            return positions
        except: return {}
    return {}

def save_data(positions):
    """전략 태그를 포함하여 CSV 저장"""
    if positions:
        rows = []
        for tkr, data in positions.items():
            rows.append({
                'Ticker': tkr,
                'Units': data['Units'],
                'Highest': data['Highest'],
                'History': json.dumps(data['History']),
                'Strategy': data.get('Strategy', '🚀 터틀-상승')
            })
        pd.DataFrame(rows).to_csv(DB_FILE, index=False)
    elif os.path.exists(DB_FILE):
        os.remove(DB_FILE)

@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="6mo")
        if len(df) < 60: return None
        # 통합 지표 계산 (터틀 + 하락장 공용)
        df['N'] = df[['High', 'Low', 'Close']].diff().abs().max(axis=1).rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        df['MA5'] = df['Close'].rolling(5).mean()
        df['BB_Lower'] = df['Close'].rolling(20).mean() - (df['Close'].rolling(20).std() * 2)
        return df
    except: return None

# ==========================================
# 2. 앱 레이아웃 및 설정
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.4", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions = load_data()

# 사이드바 설정
st.sidebar.header("⚙️ 리스크 및 데이터")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", min_value=100, value=200, step=50)
total_capital = int(cap_manwon * 10000)
st.sidebar.markdown(f"### 💰 **₩ {total_capital:,}**")

# 📉 하락장 모드 스위치
st.sidebar.divider()
bear_mode = st.sidebar.toggle("📉 하락장(낙폭과대) 스캐너 활성")

# 데이터 업로드 (통합 복구)
uploaded_file = st.sidebar.file_uploader("📂 백업 CSV 업로드", type=['csv'])
if uploaded_file is not None:
    if st.sidebar.button("데이터 즉시 복구", type="primary"):
        try:
            df = pd.read_csv(uploaded_file)
            restored = {}
            for _, row in df.iterrows():
                restored[row['Ticker']] = {
                    'Units': int(row['Units']),
                    'Highest': float(row['Highest']),
                    'History': json.loads(row['History']),
                    'Strategy': row['Strategy']
                }
            st.session_state.positions = restored
            save_data(restored)
            st.sidebar.success("✅ 전체 종목 복구 완료!")
            st.rerun()
        except: st.sidebar.error("❌ 파일 형식이 맞지 않습니다.")

st.title("🐢 Turtle System Pro V7.4")

tab1, tab2 = st.tabs(["🔭 1. 전략 스캐너", "📋 2. 통합 매니저"])

# ------------------------------------------
# 탭 1: 스캐너 (모드별 진입 전략 기록)
# ------------------------------------------
with tab1:
    st.subheader("🔭 시장 스캔")
    # ... (스캐너 로직 생략 - V7.3과 동일하게 Strategy 저장 로직 포함)
    # [이전 스캐너 코드와 동일하게 유지하되 등록 시 Strategy 기록]
    if st.button("🚀 분석 시작", type="primary", use_container_width=True):
        # (생략된 스캐너 작동부)
        st.write("분석 중...") 
        # 실제 적용 시 V7.3의 스캐너 루프를 여기에 넣으시면 됩니다.

# ------------------------------------------
# 탭 2: 통합 매니저 (전략별 맞춤형 시각화)
# ------------------------------------------
with tab2:
    if not st.session_state.positions:
        st.info("관리 중인 종목이 없습니다. 스캐너에서 종목을 추가하세요.")
    else:
        for tkr, pos in list(st.session_state.positions.items()):
            data = analyze_ticker(tkr)
            if data is None: continue
            
            latest = data.iloc[-1]
            curr_price = latest['Close']
            strat = pos.get('Strategy', '🚀 터틀-상승')
            history = pos['History']
            total_shares = sum(h['shares'] for h in history)
            avg_entry = sum(h['price'] * h['shares'] for h in history) / total_shares if total_shares > 0 else 0
            
            with st.container(border=True):
                # 전략별 색상 뱃지
                st.markdown(f"#### **{tkr}** {':blue' if '터틀' in strat else ':red'}[({strat})]")
                
                # 1. 하락장 전용 로직 (5% 익절 / -3% 손절)
                if "낙폭" in strat:
                    profit_pct = (curr_price / avg_entry) - 1
                    if profit_pct >= 0.05: st.success("💰 **[수익실현]** +5% 목표 달성!")
                    elif profit_pct <= -0.03: st.error("🛑 **[즉시손절]** -3% 라인 붕괴!")
                    
                    # 하락장 전용 지표 차트 (5%, 10%, -3% 선)
                    chart_data = data.reset_index()[['Date', 'Close']].tail(40)
                    base = alt.Chart(chart_data).encode(x='Date:T')
                    line = base.mark_line().encode(y=alt.Y('Close:Q', scale=alt.Scale(zero=False)))
                    
                    levels = [
                        {'val': avg_entry * 1.05, 'name': '5% Profit', 'col': 'green'},
                        {'val': avg_entry * 1.10, 'name': '10% Goal', 'col': 'blue'},
                        {'val': avg_entry * 0.97, 'name': '3% Stop', 'col': 'red'}
                    ]
                    
                    chart_layers = [line]
                    for lv in levels:
                        rule = alt.Chart(pd.DataFrame({'y': [lv['val']]})).mark_rule(strokeDash=[5,5], color=lv['col']).encode(y='y:Q')
                        label = alt.Chart(pd.DataFrame({'Date': [chart_data['Date'].max()], 'y': [lv['val']], 't': [f"{lv['name']}: ${lv['val']:.2f}"]})).mark_text(align='left', dx=5, dy=-5, color=lv['col']).encode(x='Date:T', y='y:Q', text='t:N')
                        chart_layers.extend([rule, label])
                    st.altair_chart(alt.layer(*chart_layers).properties(height=300), use_container_width=True)

                # 2. 터틀 전용 로직 (기존 2N/3N/Low20)
                else:
                    stop_loss = avg_entry - (2 * latest['N'])
                    trailing = pos['Highest'] - (3 * latest['N'])
                    donchian = latest['Low20']
                    
                    # 터틀 전용 차트
                    chart_df = data[['Close', 'Low20']].tail(40).copy()
                    chart_df['Stop(-2N)'] = stop_loss
                    chart_df['Trailing(-3N)'] = trailing
                    st.line_chart(chart_df)
                    st.caption(f"현재: ${curr_price:.2f} | 손절: ${stop_loss:.2f} | 익절: ${trailing:.2f}")

                if st.button("매매 종료", key=f"ex_{tkr}", use_container_width=True):
                    del st.session_state.positions[tkr]; save_data(st.session_state.positions); st.rerun()

        # 💡 통합 백업 버튼 (전체 종목을 하나의 CSV로 출력)
        st.divider()
        if st.session_state.positions:
            today = datetime.now().strftime("%y%m%d")
            file_name = f"{today}_position.csv"
            # 현재 메모리의 모든 포지션을 Strategy 포함하여 내보내기
            csv_df = pd.DataFrame([{'Ticker': k, 'Units': v['Units'], 'Highest': v['Highest'], 'History': json.dumps(v['History']), 'Strategy': v.get('Strategy', '🚀 터틀-상승')} for k, v in st.session_state.positions.items()])
            st.download_button(
                label=f"💾 전체 종목 통합 백업 ({file_name})",
                data=csv_df.to_csv(index=False).encode('utf-8-sig'),
                file_name=file_name,
                mime="text/csv",
                use_container_width=True
            )
