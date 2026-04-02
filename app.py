import streamlit as st
import yfinance as yf
import pandas as pd
import os, time, requests, json, feedparser
import altair as alt
from datetime import datetime, timedelta
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 환경 설정
# ==========================================
DB_FILE = 'internal_memory.csv'
MAX_TOTAL_UNITS = 10
MAX_UNIT_PER_STOCK = 3
CACHE_TTL = 300

@st.cache_data(ttl=86400)
def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0'}
        html = requests.get(url, headers=headers).text
        table = pd.read_html(html)[0]
        return [t.replace('.', '-') for t in table['Symbol'].tolist()]
    except:
        return ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA']

TICKERS = get_sp500_tickers()

def load_data():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        return {row['Ticker']: {'Units': int(row['Units']), 'Highest': float(row['Highest']), 
                'History': json.loads(row['History']), 'Strategy': row.get('Strategy', '🚀 터틀-상승')} for _, row in df.iterrows()}
    return {}

def save_data(positions):
    if positions:
        rows = [{'Ticker': k, 'Units': v['Units'], 'Highest': v['Highest'], 
                 'History': json.dumps(v['History']), 'Strategy': v['Strategy']} for k, v in positions.items()]
        pd.DataFrame(rows).to_csv(DB_FILE, index=False)
    elif os.path.exists(DB_FILE): os.remove(DB_FILE)

# ==========================================
# 2. 분석 엔진
# ==========================================
@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="1y")
        if len(df) < 200: return None
        df['TR'] = df[['High', 'Low', 'Close']].apply(lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1)
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        df['MA200'] = df['Close'].rolling(200).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA5'] = df['Close'].rolling(5).mean()
        df['Std'] = df['Close'].rolling(20).std()
        df['BB_Lower'] = df['MA20'] - (df['Std'] * 2)
        delta = df['Close'].diff(); gain = delta.where(delta > 0, 0); loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean(); avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + avg_gain/avg_loss))
        return df
    except: return None

# ==========================================
# 3. UI 렌더링
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.31", layout="centered", page_icon="🐢")
if "positions" not in st.session_state: st.session_state.positions = load_data()

st.title("🐢 Turtle System Pro V7.31")
st.sidebar.header("⚙️ 리스크 설정")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", value=200)
total_capital = cap_manwon * 10000
risk_per_unit = st.sidebar.slider("1 Unit당 위험 (%)", 1.0, 5.0, 2.0) / 100
exchange_rate = st.sidebar.number_input("환율 (₩/$)", value=1450)

tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 매니저", "🇺🇸 분석"])

# 스캐너 로직 (포착 대기 모드 포함)
for i, strat in enumerate(["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"]):
    with tabs[i]:
        col_btn, col_chk = st.columns([3, 2])
        is_search = col_btn.button(f"🔎 {strat} 분석", key=f"btn_{i}")
        # 💡 핵심 업데이트: 대기 종목 포함 체크박스
        show_candidates = col_chk.checkbox("⚠️ 포착 대기 종목 포함", key=f"chk_{i}")
        
        if is_search:
            res = []
            p_bar = st.progress(0, text="스캐닝 중...")
            for idx, tkr in enumerate(TICKERS):
                p_bar.progress((idx+1)/len(TICKERS))
                df = analyze_ticker(tkr)
                if df is not None:
                    latest, prev = df.iloc[-1], df.iloc[-2]
                    cond, is_cand = False, False
                    
                    if "터틀" in strat:
                        cond = (latest['Close'] > latest['High55']) and (latest['Close'] > latest['MA200']) and (50 <= latest['RSI'] < 70)
                        if show_candidates and not cond:
                            is_cand = (latest['Close'] > latest['High55'] * 0.98) and (latest['Close'] > latest['MA200'])
                    elif "눌림목" in strat:
                        touch = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                        rebound = (latest['Close'] > latest['MA5']) and (prev['Close'] <= prev['MA5'])
                        cond = touch and rebound and (latest['Close'] > latest['MA200'])
                        if show_candidates and not cond:
                            is_cand = touch and (latest['Close'] > latest['MA200']) # 터치는 했으나 아직 반등 전
                    else: # BB낙폭
                        touch = (df['Low'].iloc[-3:] <= df['BB_Lower'].iloc[-3:]).any()
                        rebound = (latest['Close'] > latest['MA5']) and (prev['Close'] <= prev['MA5'])
                        cond = touch and rebound and (latest['Close'] > latest['MA200'])
                        if show_candidates and not cond:
                            is_cand = touch and (latest['Close'] > latest['MA200'])

                    if cond or is_cand:
                        risk_shares = int((total_capital * risk_per_unit) / (latest['N'] * exchange_rate)) if latest['N'] > 0 else 1
                        res.append({"tkr": tkr, "price": latest['Close'], "shares": risk_shares, "is_cand": is_cand})
            p_bar.empty()
            if not res: st.info("종목이 없습니다. 시장이 휴식 중입니다.")
            for s in res:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    label = " [⚠️ 대기]" if s['is_cand'] else " [✅ 포착]"
                    c1.write(f"### {s['tkr']}{label}")
                    c1.write(f"가격: ${s['price']:.2f} | 권장: {s['shares']}주")
                    if not s['is_cand'] and c2.button("등록", key=f"reg_{s['tkr']}"):
                        st.session_state.positions[s['tkr']] = {'Units': 1, 'Highest': s['price'], 'History': [{'price': s['price'], 'shares': s['shares']}], 'Strategy': strat}
                        save_data(st.session_state.positions); st.rerun()

# --- 매니저 탭 (기존 로직 유지) ---
with tabs[3]:
    for tkr, pos in list(st.session_state.positions.items()):
        df = analyze_ticker(tkr)
        if df is not None:
            latest = df.iloc[-1]; strat = pos['Strategy']
            with st.container(border=True):
                st.write(f"#### {tkr} ({strat})")
                if st.button("삭제", key=f"del_{tkr}"): del st.session_state.positions[tkr]; save_data(st.session_state.positions); st.rerun()
