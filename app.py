import streamlit as st
import yfinance as yf
import pandas as pd
import os
import time
import requests
import json
from datetime import datetime

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 기본 설정 및 데이터 로드
# ==========================================
DB_FILE = 'internal_memory.csv' 
MAX_TOTAL_UNITS = 10       
MAX_UNIT_PER_STOCK = 3     

@st.cache_data(ttl=86400) 
def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        html = requests.get(url, headers=headers).text
        table = pd.read_html(html)[0]
        tickers = table['Symbol'].tolist()
        return [ticker.replace('.', '-') for ticker in tickers]
    except Exception as e:
        st.error(f"⚠️ S&P 500 리스트 로드 실패. 비상용 10종목 대체. (사유: {e})")
        return ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B', 'JNJ', 'JPM']

TICKERS = get_sp500_tickers()

def load_data():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        positions = {}
        for _, row in df.iterrows():
            history = json.loads(row['History']) if pd.notna(row['History']) else []
            positions[row['Ticker']] = {
                'Units': row['Units'],
                'Highest': row['Highest'],
                'History': history
            }
        return positions
    return {}

def save_data(positions):
    if positions:
        rows = []
        for tkr, data in positions.items():
            rows.append({
                'Ticker': tkr,
                'Units': data['Units'],
                'Highest': data['Highest'],
                'History': json.dumps(data.get('History', []))
            })
        df = pd.DataFrame(rows)
        df.to_csv(DB_FILE, index=False)
    else:
        if os.path.exists(DB_FILE): os.remove(DB_FILE)

# ==========================================
# 2. 분석 엔진
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy['MA200'] = spy['Close'].rolling(200).mean()
        return spy['Close'].iloc[-1] > spy['MA200'].iloc[-1]
    except: return True

@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="6mo")
        if len(df) < 60: return None
        
        df['TR'] = df[['High', 'Low', 'Close']].apply(
            lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) 
            if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1
        )
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        return df 
    except: return None

# ==========================================
# 3. 앱 UI 및 메인 로직
# ==========================================
st.set_page_config(page_title="Turtle System Pro", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions = load_data()
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None 

# --- 사이드바 ---
st.sidebar.header("⚙️ 리스크 설정")
capital_manwon = st.sidebar.number_input("운용 시드머니 (만원 단위)", min_value=100, value=200, step=50)
total_capital = int(capital_manwon * 10000)
st.sidebar.markdown(f"### 💰 **₩ {total_capital:,}**")
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 감수율 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", min_value=1000, value=1350, step=10)

st.sidebar.divider()
st.sidebar.header("💾 데이터 복구 (업로드)")
uploaded_file = st.sidebar.file_uploader("백업 CSV 선택", type=['csv'])
if uploaded_file is not None:
    if st.sidebar.button("데이터 복구 실행", type="primary"):
        try:
            df = pd.read_csv(uploaded_file)
            restored = {}
            for _, row in df.iterrows():
                history = json.loads(row['History']) if pd.notna(row['History']) else []
                restored[row['Ticker']] = {'Units': row['Units'], 'Highest': row['Highest'], 'History': history}
            st.session_state.positions = restored
            save_data(st.session_state.positions)
            st.sidebar.success("✅ 복구 완료!")
            st.rerun()
        except: st.sidebar.error("❌ 복구 실패")

st.title("🐢 Turtle System Pro")

is_bull_market = check_market_filter()
if is_bull_market: st.success("🟢 **시장 필터 통과 (대세 상승장)**")
else: st.error("🔴 **시장 필터 경고 (대세 하락장)**")

current_total_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
col_u1, col_u2 = st.columns(2)
col_u1.metric("사용 중인 관리 유닛", f"{current_total_units} / {MAX_TOTAL_UNITS} U")
col_u2.metric("현재 계좌 위험도", f"{current_total_units * (risk_per_unit * 100):.1f}%")

st.divider()

tab1, tab2 = st.tabs(["🔭 1. S&P 500 돌파 스캐너", "📋 2. 포지션 관리 및 지표 차트"])

# ------------------------------------------
# 탭 1: 스캐너
# ------------------------------------------
with tab1:
    st.subheader("🔍 55일 신고가 돌파 종목 찾기")
    if st.button("🚀 스캐너 작동", type="primary"):
        my_bar = st.progress(0, text="분석 시작...")
        temp_results = []
        for i, tkr in enumerate(TICKERS):
            my_bar.progress((i + 1) / len(TICKERS), text=f"[{i+1}/{len(TICKERS)}] {tkr} 분석 중...")
            data = analyze_ticker(tkr)
            if data is not None:
                latest = data.iloc[-1]
                if latest['Close'] > latest['High55']:
                    n_val = latest['N']
                    unit_shares = int((total_capital * risk_per_unit) / (n_val * exchange_rate)) if n_val > 0 else 0
                    if unit_shares > 0:
                        temp_results.append({"Ticker": tkr, "Price": latest['Close'], "N": n_val, "Rec_Shares": unit_shares})
        my_bar.empty()
        st.session_state.scan_results = temp_results

    if st.session_state.scan_results:
        for stock in st.session_state.scan_results:
            tkr = stock['Ticker']
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 2, 2])
                c1.markdown(f"### {tkr}")
                c2.metric("현재가", f"${stock['Price']:.2f}")
                c3.metric("권장 매수량", f"{stock['Rec_Shares']} 주")
                if tkr not in st.session_state.positions:
                    if st.button(f"➕ 내 포지션에 등록", key=f"add_scan_{tkr}"):
                        st.session_state.positions[tkr] = {'Units': 1, 'Highest': stock['Price'], 'History': [{'price': stock['Price'], 'shares': stock['Rec_Shares']}]}
                        save_data(st.session_state.positions)
                        st.rerun()

# ------------------------------------------
# 탭 2: 매니저 및 직관적 입력 UI
# ------------------------------------------
with tab2:
    st.subheader("📋 내 보유 종목 현황")
    
    if not st.session_state.positions:
        st.info("보유 중인 매매 기록이 없습니다.")
    else:
        for tkr, pos in list(st.session_state.positions.items()):
            data = analyze_ticker(tkr)
            if data is None: continue
            
            latest = data.iloc[-1]
            curr_price = latest['Close']
            n_val = latest['N']
            history = pos.get('History', [])
            total_shares = sum(h['shares'] for h in history)
            avg_entry = sum(h['price'] * h['shares'] for h in history) / total_shares if total_shares > 0 else 0
            
            if curr_price > pos.get('Highest', avg_entry):
                pos['Highest'] = curr_price
                save_data(st.session_state.positions)
            highest = pos['Highest']
            
            stop_loss = avg_entry - (2 * n_val)
            trailing_stop = highest - (3 * n_val)
            donchian_exit = latest['Low20']
            next_add_price = avg_entry + (0.5 * n_val)

            with st.container(border=True):
                c_title, c_del = st.columns([4, 1])
                c_title.markdown(f"#### **{tkr}** (총 {total_shares}주)")
                if c_del.button("매매 종료", key=f"del_pos_{tkr}"):
                    del st.session_state.positions[tkr]
                    save_data(st.session_state.positions)
                    st.rerun()

                # 시나리오 알림
                if curr_price < stop_loss:
                    st.error(f"🛑 **[상황 A]** 초기 방어선(${stop_loss:.2f}) 이탈!")
                elif curr_price < trailing_stop:
                    st.error(f"💰 **[상황 C]** 익절선(${trailing_stop:.2f}) 이탈!")
                elif curr_price < donchian_exit:
                    st.error(f"⚠️ **[상황 D]** 20일 신저가(${donchian_exit:.2f}) 붕괴!")
                elif curr_price >= next_add_price and pos['Units'] < MAX_UNIT_PER_STOCK:
                    st.success(f"🚀 **[상황 B]** 불타기 목표가(${next_add_price:.2f}) 돌파!")
                else:
                    st.info(f"✅ **[순항 중]** 평단 ${avg_entry:.2f} | 수익률 {(curr_price/avg_entry)-1:.2%}")

                # 💡 직관적 수기 입력 섹션
                with st.expander("📝 매수 기록 직접 입력/수정"):
                    st.caption("실제 체결된 단가와 수량을 입력하세요.")
                    
                    # 1. 입력 폼 (가로 배치)
                    with st.container():
                        col_in1, col_in2 = st.columns(2)
                        in_p = col_in1.number_input("매수 단가 ($)", min_value=0.0, format="%.2f", key=f"p_{tkr}", value=curr_price)
                        in_s = col_in2.number_input("매수 수량 (주)", min_value=1, step=1, key=f"s_{tkr}")
                        
                        btn_c1, btn_c2 = st.columns(2)
                        if btn_c1.button("✅ 기록 추가", key=f"btn_add_{tkr}", use_container_width=True):
                            pos['History'].append({'price': in_p, 'shares': in_s})
                            pos['Units'] = min(MAX_UNIT_PER_STOCK, len(pos['History']))
                            save_data(st.session_state.positions)
                            st.rerun()
                            
                        if btn_c2.button("🔙 최근 기록 삭제", key=f"btn_undo_{tkr}", use_container_width=True, type="secondary"):
                            if len(pos['History']) > 1:
                                pos['History'].pop()
                                pos['Units'] = len(pos['History'])
                                save_data(st.session_state.positions)
                                st.rerun()
                            else:
                                st.warning("첫 번째 기록은 삭제할 수 없습니다. '매매 종료'를 이용하세요.")

                    st.divider()
                    # 2. 현재 내역 테이블
                    st.markdown("**현재 매수 내역**")
                    if history:
                        hist_df = pd.DataFrame(history)
                        hist_df.columns = ['단가 ($)', '수량 (주)']
                        st.table(hist_df.style.format({'단가 ($)': '{:.2f}'}))

                with st.expander("📊 지표 차트 확인"):
                    chart_df = data[['Close', 'Low20']].copy()
                    chart_df['초기방어선'] = stop_loss
                    chart_df['익절선'] = trailing_stop
                    chart_df['불타기선'] = next_add_price if pos['Units'] < MAX_UNIT_PER_STOCK else None
                    st.line_chart(chart_df)

        st.divider()
        if st.session_state.positions:
            today_str = datetime.now().strftime("%y%m%d")
            file_name = f"{today_str}_position.csv"
            csv_data = pd.DataFrame([{'Ticker': k, 'Units': v['Units'], 'Highest': v['Highest'], 'History': json.dumps(v['History'])} for k, v in st.session_state.positions.items()]).to_csv(index=False).encode('utf-8-sig')
            st.download_button(label=f"💾 기록 백업하기 ({file_name})", data=csv_data, file_name=file_name, mime="text/csv", use_container_width=True)
