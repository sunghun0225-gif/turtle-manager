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
# 1. 데이터 입출력 및 환경 설정
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
    except:
        return ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B', 'JNJ', 'JPM']

TICKERS = get_sp500_tickers()

def load_data():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        positions = {}
        for _, row in df.iterrows():
            history = json.loads(row['History']) if pd.notna(row['History']) else []
            positions[row['Ticker']] = {
                'Units': int(row['Units']),
                'Highest': float(row['Highest']),
                'History': history,
                'Strategy': row['Strategy'] if 'Strategy' in df.columns else '🚀 터틀-상승'
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
                'History': json.dumps(data.get('History', [])),
                'Strategy': data.get('Strategy', '🚀 터틀-상승')
            })
        pd.DataFrame(rows).to_csv(DB_FILE, index=False)
    elif os.path.exists(DB_FILE):
        os.remove(DB_FILE)

# ==========================================
# 2. 분석 엔진
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    """SPY 200일 이평선 기반 시장 필터"""
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy = spy['Close'].iloc[-1]
        ma200 = spy['MA200'].iloc[-1]
        return curr_spy > ma200, curr_spy, ma200
    except: return True, 0, 0

@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="6mo")
        if len(df) < 60: return None
        df['TR'] = df[['High', 'Low', 'Close']].apply(lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1)
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        df['MA20'] = df['Close'].rolling(20).mean()
        df['Std'] = df['Close'].rolling(20).std()
        df['BB_Lower'] = df['MA20'] - (df['Std'] * 2)
        df['MA5'] = df['Close'].rolling(5).mean()
        return df 
    except: return None

# ==========================================
# 3. 메인 UI 및 시장 지표 복구
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.7", layout="centered", page_icon="🐢")
if "positions" not in st.session_state: st.session_state.positions = load_data()

# --- 사이드바 ---
st.sidebar.header("⚙️ 리스크 및 백업")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", min_value=100, value=200, step=50)
total_capital = int(cap_manwon * 10000)
st.sidebar.markdown(f"### 💰 **₩ {total_capital:,}**")
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 감수율 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", min_value=1000, value=1350, step=10)

st.sidebar.divider()
uploaded_file = st.sidebar.file_uploader("📂 백업 CSV 업로드", type=['csv'])
if uploaded_file is not None:
    if st.sidebar.button("데이터 즉시 복구", type="primary"):
        try:
            df = pd.read_csv(uploaded_file)
            st.session_state.positions = {row['Ticker']: {'Units': int(row['Units']), 'Highest': float(row['Highest']), 'History': json.loads(row['History']), 'Strategy': row['Strategy']} for _, row in df.iterrows()}
            save_data(st.session_state.positions); st.sidebar.success("✅ 복구 완료!"); st.rerun()
        except: st.sidebar.error("❌ 파일 형식 오류")

# --- 메인 타이틀 및 시장 지표 가이드 ---
st.title("🐢 Turtle System Pro V7.7")

# 💡 시장 필터 가이드라인 복구
is_bull, spy_val, ma200_val = check_market_filter()
if is_bull:
    st.success(f"🟢 **시장 필터 통과 (대세 상승장)** | SPY(${spy_val:.2f}) > 200일선(${ma200_val:.2f})\n\n👉 **[1번 탭]** 터틀 스캐너를 통한 추세 추종 매매가 유리합니다.")
else:
    st.error(f"🔴 **시장 필터 경고 (대세 하락장)** | SPY(${spy_val:.2f}) < 200일선(${ma200_val:.2f})\n\n👉 **신규 매수 중단 권장.** 부득이한 경우 **[3번 탭]** 낙폭과대 스캔만 짧게 활용하세요.")

current_total_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
c_d1, c_d2 = st.columns(2); c_d1.metric("총 관리 유닛", f"{current_total_units}/{MAX_TOTAL_UNITS} U"); c_d2.metric("보유 종목", f"{len(st.session_state.positions)}개")

st.divider()
tab1, tab2, tab3 = st.tabs(["🚀 1. 터틀 스캐너", "📋 2. 포지션 매니저", "📉 3. 낙폭과대 스캐너"])

# --- 탭 1: 터틀 스캐너 ---
with tab1:
    st.subheader("🔍 55일 신고가 돌파 스캔")
    if st.button("🚀 터틀 분석 시작", type="primary", use_container_width=True):
        my_bar = st.progress(0, text="검색 중..."); results = []
        for i, tkr in enumerate(TICKERS):
            my_bar.progress((i+1)/len(TICKERS), text=f"[{i+1}/{len(TICKERS)}] {tkr}..."); data = analyze_ticker(tkr)
            if data is not None and data.iloc[-1]['Close'] > data.iloc[-1]['High55']: results.append({"Ticker": tkr, "Price": data.iloc[-1]['Close'], "Strategy": "🚀 터틀-상승"})
        my_bar.empty(); st.session_state.scan_results = results
    if st.session_state.get('scan_results'):
        for s in st.session_state.scan_results:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3); c1.write(f"### {s['Ticker']}"); c2.write(f"${s['Price']:.2f}")
                if s['Ticker'] not in st.session_state.positions and st.button("➕ 등록", key=f"t_{s['Ticker']}"):
                    st.session_state.positions[s['Ticker']] = {'Units': 1, 'Highest': s['Price'], 'History': [{'price': s['Price'], 'shares': 1}], 'Strategy': s['Strategy']}
                    save_data(st.session_state.positions); st.rerun()

# --- 탭 3: 낙폭과대 스캐너 ---
with tab3:
    st.subheader("📉 BB 하한 반등 스캔")
    if st.button("🚀 낙폭과대 분석 시작", type="primary", use_container_width=True):
        my_bar = st.progress(0, text="검색 중..."); results = []
        for i, tkr in enumerate(TICKERS):
            my_bar.progress((i+1)/len(TICKERS), text=f"[{i+1}/{len(TICKERS)}] {tkr}..."); data = analyze_ticker(tkr)
            if data is not None:
                latest, prev = data.iloc[-1], data.iloc[-2]
                if (data['Low'].iloc[-3:] <= data['BB_Lower'].iloc[-3:]).any() and latest['Close'] > latest['MA5'] and prev['Close'] <= prev['MA5']:
                    results.append({"Ticker": tkr, "Price": latest['Close'], "Strategy": "📉 낙폭-하강"})
        my_bar.empty(); st.session_state.scan_results_bear = results
    if st.session_state.get('scan_results_bear'):
        for s in st.session_state.scan_results_bear:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3); c1.write(f"### {s['Ticker']}"); c2.write(f"${s['Price']:.2f}")
                if s['Ticker'] not in st.session_state.positions and st.button("➕ 등록", key=f"b_{s['Ticker']}"):
                    st.session_state.positions[s['Ticker']] = {'Units': 1, 'Highest': s['Price'], 'History': [{'price': s['Price'], 'shares': 1}], 'Strategy': s['Strategy']}
                    save_data(st.session_state.positions); st.rerun()

# --- 탭 2: 통합 매니저 ---
with tab2:
    for tkr, pos in list(st.session_state.positions.items()):
        data = analyze_ticker(tkr)
        if data is None: continue
        latest = data.iloc[-1]; strat = pos.get('Strategy', '🚀 터틀-상승')
        total_shares = sum(h['shares'] for h in pos['History'])
        avg_entry = sum(h['price'] * h['shares'] for h in pos['History']) / total_shares if total_shares > 0 else 0
        profit_pct = (latest['Close'] / avg_entry) - 1
        if latest['Close'] > pos['Highest']: pos['Highest'] = latest['Close']; save_data(st.session_state.positions)

        with st.container(border=True):
            c_title, c_del = st.columns([4, 1]); color = "blue" if "터틀" in strat else "red"
            c_title.markdown(f"#### **{tkr}** :{color}[({strat})]")
            if c_del.button("종료", key=f"del_{tkr}"): del st.session_state.positions[tkr]; save_data(st.session_state.positions); st.rerun()

            if "낙폭" in strat:
                if profit_pct >= 0.05: st.success(f"💰 **익절 권장 (+5% 달성)**")
                elif profit_pct <= -0.03: st.error(f"🛑 **손절 권장 (-3% 도달)**")
            
            with st.expander("📊 지표 차트 및 기록 관리"):
                chart_df = data.reset_index()[['Date', 'Close']].tail(50); base = alt.Chart(chart_df).encode(x='Date:T')
                line = base.mark_line(color='#1f77b4').encode(y=alt.Y('Close:Q', scale=alt.Scale(zero=False)))
                levels = [{'val': avg_entry*1.05, 'name': '5% 익절', 'col': 'green'}, {'val': avg_entry*1.1, 'name': '10% 목표', 'col': 'blue'}, {'val': avg_entry*0.97, 'name': '3% 손절', 'col': 'red'}] if "낙폭" in strat else [{'val': avg_entry-2*latest['N'], 'name': '손절-2N', 'col': 'red'}, {'val': pos['Highest']-3*latest['N'], 'name': '익절-3N', 'col': 'green'}, {'val': avg_entry+0.5*latest['N'], 'name': '불타기', 'col': 'orange'}]
                layers = [line]
                for i, lv in enumerate(levels):
                    layers.append(alt.Chart(pd.DataFrame({'y': [lv['val']]})).mark_rule(strokeDash=[5,5], color=lv['col']).encode(y='y:Q'))
                    layers.append(alt.Chart(pd.DataFrame({'Date': [chart_df['Date'].max()], 'y': [lv['val']], 't': [f"{lv['name']}: ${lv['val']:.2f}"]})).mark_text(align='left', dx=10, dy=(i*18)-18, color=lv['col'], fontWeight='bold').encode(x='Date:T', y='y:Q', text='t:N'))
                st.altair_chart(alt.layer(*layers).properties(height=350), use_container_width=True)

                c1, c2 = st.columns(2)
                in_p = c1.number_input("단가", min_value=0.0, format="%.2f", key=f"p_{tkr}", value=latest['Close'])
                in_s = c2.number_input("수량", min_value=1, step=1, key=f"s_{tkr}")
                b1, b2 = st.columns(2)
                if b1.button("✅ 추가", key=f"a_{tkr}", use_container_width=True):
                    pos['History'].append({'price': in_p, 'shares': in_s}); pos['Units'] = min(MAX_UNIT_PER_STOCK, len(pos['History'])); save_data(st.session_state.positions); st.rerun()
                if b2.button("🔙 삭제", key=f"u_{tkr}", use_container_width=True) and len(pos['History']) > 1:
                    pos['History'].pop(); pos['Units'] = len(pos['History']); save_data(st.session_state.positions); st.rerun()

    if st.session_state.positions:
        st.divider(); today = datetime.now().strftime("%y%m%d"); file_name = f"{today}_position.csv"
        csv = pd.DataFrame([{'Ticker': k, 'Units': v['Units'], 'Highest': v['Highest'], 'History': json.dumps(v['History']), 'Strategy': v['Strategy']} for k, v in st.session_state.positions.items()]).to_csv(index=False).encode('utf-8-sig')
        st.download_button(f"💾 전체 통합 백업 ({file_name})", csv, file_name, "text/csv", use_container_width=True)
