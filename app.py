import streamlit as st
import yfinance as yf
import pandas as pd
import os
import time
import requests
import json
import altair as alt
import feedparser
from datetime import datetime, timedelta

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 데이터 입출력 및 환경 설정
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
# 2. 분석 엔진 (지표 및 시장 필터)
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy = spy['Close'].iloc[-1]
        ma200_now = spy['MA200'].iloc[-1]
        last_6_ma200 = spy['MA200'].tail(6)
        is_trending_up = all(last_6_ma200.iloc[i] > last_6_ma200.iloc[i-1] for i in range(1, 6))
        is_bull = (curr_spy > ma200_now) and is_trending_up
        return is_bull, curr_spy, ma200_now, is_trending_up
    except: return True, 0, 0, False

@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="1y")
        if len(df) < 200: return None
        
        # 터틀 지표
        df['TR'] = df[['High', 'Low', 'Close']].apply(lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1)
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        
        # 이평선 및 볼린저밴드
        df['MA200'] = df['Close'].rolling(200).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA5'] = df['Close'].rolling(5).mean()
        df['Std'] = df['Close'].rolling(20).std()
        df['BB_Lower'] = df['MA20'] - (df['Std'] * 2)
        
        # RSI
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0); loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + avg_gain/avg_loss))
        
        return df 
    except: return None

# ==========================================
# 3. 보조 도구 (SEC 공시 및 뉴스)
# ==========================================
def fetch_ticker_cached(ticker: str):
    now = time.time()
    cache = st.session_state.get("price_cache", {})
    if ticker in cache:
        p, ts, info = cache[ticker]
        if now - ts < CACHE_TTL: return p, info, True
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="5d")
        if not h.empty:
            p = h["Close"].iloc[-1]
            try: info = s.info
            except: info = {}
            st.session_state["price_cache"][ticker] = (p, now, info)
            return p, info, False
    except: pass
    return None, {}, False

@st.cache_data(ttl=86400)
def get_cik(ticker: str):
    try:
        headers = {"User-Agent": "TurtlePro/1.0 contact@example.com"}
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
        for entry in res.json().values():
            if entry["ticker"].upper() == ticker.upper(): return str(entry["cik_str"])
    except: pass
    return None

def get_sec_filings(ticker: str, limit: int = 12):
    cik = get_cik(ticker)
    if not cik: return None, "CIK 미발견"
    try:
        headers = {"User-Agent": "TurtlePro/1.0 contact@example.com"}
        url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        res = requests.get(url, headers=headers, timeout=10)
        sub = res.json()
        recent = sub.get("filings", {}).get("recent", {})
        filings = []
        for i in range(len(recent.get("form", []))):
            filings.append({"form": recent["form"][i], "date": recent["filingDate"][i], "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"})
        return filings[:limit], None
    except: return None, "데이터 로딩 실패"

# ==========================================
# 4. 메인 UI 렌더링
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.33", layout="centered", page_icon="🐢")
if "positions" not in st.session_state: st.session_state.positions = load_data()
if "price_cache" not in st.session_state: st.session_state["price_cache"] = {}

# --- 사이드바 (리스크 및 백업) ---
st.sidebar.header("⚙️ 리스크 및 백업")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", min_value=100, value=200, step=50)
total_capital = int(cap_manwon * 10000)
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("환율 (₩/$)", min_value=1000, value=1450, step=10)

st.sidebar.divider()
uploaded_file = st.sidebar.file_uploader("📂 백업 CSV 업로드")
if uploaded_file is not None and st.sidebar.button("데이터 즉시 복구", type="primary"):
    try:
        df = pd.read_csv(uploaded_file)
        st.session_state.positions = {row['Ticker']: {'Units': int(row['Units']), 'Highest': float(row['Highest']), 'History': json.loads(row['History']), 'Strategy': row['Strategy']} for _, row in df.iterrows()}
        save_data(st.session_state.positions); st.sidebar.success("✅ 복구 완료!"); st.rerun()
    except: st.sidebar.error("❌ 파일 형식 오류")

# --- 대시보드 상단 ---
st.title("🐢 Turtle System Pro V7.33")
is_bull, spy_val, ma200_val, is_trending_up = check_market_filter()
if is_bull: st.success(f"🟢 **시장 대세 상승장** | SPY: ${spy_val:.2f} | 200일선 우상향")
else: st.error(f"🔴 **시장 조정/하락 주의** | SPY: ${spy_val:.2f} | 리스크 관리 필요")

c1, c2, c3 = st.columns(3)
t_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
c1.metric("총 유닛", f"{t_units}/{MAX_TOTAL_UNITS} U")
c2.metric("계좌 위험도", f"{t_units * (risk_per_unit * 100):.1f}%")
c3.metric("보유 종목", f"{len(st.session_state.positions)}개")

st.divider()
tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 매니저", "🇺🇸 분석", "🌍 뉴스"])

# --- 스캐너 탭 (1, 2, 3) ---
strats = ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"]
for i, strat in enumerate(strats):
    with tabs[i]:
        col_a, col_b = st.columns([3, 2])
        is_search = col_a.button(f"🔎 {strat} 분석 시작", key=f"btn_{i}", use_container_width=True)
        show_cand = col_b.checkbox("⚠️ 포착 대기(Pre-signal) 포함", key=f"chk_{i}")
        
        if is_search:
            res = []
            p_bar = st.progress(0, text="S&P 500 종목 스캔 중...")
            for idx, tkr in enumerate(TICKERS):
                p_bar.progress((idx+1)/len(TICKERS))
                df = analyze_ticker(tkr)
                if df is not None:
                    latest, prev = df.iloc[-1], df.iloc[-2]
                    cond, is_cand = False, False
                    
                    if "터틀" in strat:
                        cond = (latest['Close'] > latest['High55']) and (latest['Close'] > latest['MA200']) and (50 <= latest['RSI'] < 70)
                        if show_cand and not cond: is_cand = (latest['Close'] > latest['High55'] * 0.98) and (latest['Close'] > latest['MA200'])
                    elif "눌림목" in strat:
                        touch = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                        rebound = (latest['Close'] > latest['MA5']) and (prev['Close'] <= prev['MA5'])
                        cond = touch and rebound and (latest['Close'] > latest['MA200'])
                        if show_cand and not cond: is_cand = touch and (latest['Close'] > latest['MA200'])
                    else: # BB낙폭
                        touch = (df['Low'].iloc[-3:] <= df['BB_Lower'].iloc[-3:]).any()
                        rebound = (latest['Close'] > latest['MA5']) and (prev['Close'] <= prev['MA5'])
                        cond = touch and rebound and (latest['Close'] > latest['MA200'])
                        if show_cand and not cond: is_cand = touch and (latest['Close'] > latest['MA200'])
                    
                    if cond or is_cand:
                        shares = int((total_capital * risk_per_unit) / (latest['N'] * exchange_rate)) if latest['N'] > 0 else 1
                        res.append({"tkr": tkr, "price": latest['Close'], "shares": shares, "is_cand": is_cand})
            
            p_bar.empty()
            if not res: st.info("ℹ️ 현재 조건에 맞는 종목이 없습니다.")
            for s in res:
                with st.container(border=True):
                    cl_1, cl_2 = st.columns([3, 1])
                    status_tag = " [⚠️ 대기]" if s['is_cand'] else " [✅ 포착]"
                    cl_1.write(f"### {s['tkr']}{status_tag}")
                    cl_1.write(f"현재가: ${s['price']:.2f} | 권장 수량: {s['shares']}주")
                    if not s['is_cand'] and cl_2.button("➕ 등록", key=f"reg_{s['tkr']}_{i}"):
                        st.session_state.positions[s['tkr']] = {'Units': 1, 'Highest': s['price'], 'History': [{'price': s['price'], 'shares': s['shares']}], 'Strategy': strat}
                        save_data(st.session_state.positions); st.rerun()

# --- 탭 4: 포지션 매니저 (완전 복구) ---
with tabs[3]:
    if not st.session_state.positions: st.info("보유 중인 포지션이 없습니다.")
    for tkr, pos in list(st.session_state.positions.items()):
        df = analyze_ticker(tkr)
        if df is None: continue
        latest = df.iloc[-1]; strat = pos['Strategy']
        total_shares = sum(h['shares'] for h in pos['History'])
        avg_entry = sum(h['price']*h['shares'] for h in pos['History']) / total_shares if total_shares > 0 else 0
        profit_pct = (latest['Close'] / avg_entry) - 1
        if latest['Close'] > pos['Highest']: pos['Highest'] = latest['Close']; save_data(st.session_state.positions)
        
        with st.container(border=True):
            h_1, h_2 = st.columns([4, 1])
            s_color = "blue" if "터틀" in strat else ("green" if "눌림목" in strat else "red")
            h_1.markdown(f"#### **{tkr}** :{s_color}[({strat})] - {total_shares}주")
            if h_2.button("종료", key=f"exit_{tkr}"): del st.session_state.positions[tkr]; save_data(st.session_state.positions); st.rerun()
            
            if "눌림목" in strat:
                tp, sl = avg_entry * 1.06, avg_entry * 0.96
                if profit_pct >= 0.06: st.success(f"💰 **수익실현 권장 (+6%)**")
                elif profit_pct <= -0.04: st.error(f"🛑 **손절 권장 (-4%)**")
                else: st.info(f"✅ 보유 중 (수익률: {profit_pct:.2%})")
            elif "BB" in strat:
                tp, sl = avg_entry * 1.05, avg_entry * 0.95
                if profit_pct >= 0.05: st.success(f"💰 **수익실현 권장 (+5%)**")
                elif profit_pct <= -0.05: st.error(f"🛑 **손절 권장 (-5%)**")
                else: st.info(f"✅ 보유 중 (수익률: {profit_pct:.2%})")
            else: # 터틀
                stop, donchian, add = avg_entry - 2*latest['N'], latest['Low20'], avg_entry + 0.5*latest['N']
                if latest['Close'] < stop: st.error(f"🛑 **초기손절선(${stop:.2f}) 이탈**")
                elif latest['Close'] < donchian: st.error(f"🛑 **20일 신저가(${donchian:.2f}) 이탈**")
                elif latest['Close'] >= add and pos['Units'] < MAX_UNIT_PER_STOCK: st.success(f"🚀 **불타기 타점(${add:.2f}) 돌파!**")
                else: st.info(f"✅ 추세 순항 중 ({profit_pct:.2%})")
            
            with st.expander("📊 차트 및 매수 히스토리"):
                c_df = df.reset_index()[['Date', 'Close']].tail(60)
                chart = alt.Chart(c_df).mark_line().encode(x='Date:T', y=alt.Y('Close:Q', scale=alt.Scale(zero=False)))
                st.altair_chart(chart.properties(height=250), use_container_width=True)
                st.table(pd.DataFrame(pos['History']))

    if st.session_state.positions:
        csv = pd.DataFrame([{'Ticker': k, **v, 'History': json.dumps(v['History'])} for k, v in st.session_state.positions.items()]).to_csv(index=False).encode('utf-8-sig')
        st.download_button(f"💾 전체 통합 백업 ({datetime.now().strftime('%y%m%d')})", csv, f"{datetime.now().strftime('%y%m%d')}_pos.csv", "text/csv", use_container_width=True)

# --- 탭 5 & 6: 분석 및 뉴스 (완전 복구) ---
with tabs[4]:
    t_in = st.text_input("분석할 티커 입력", key="us_input").upper()
    if t_in and st.button("상세 분석 시작"):
        p, info, _ = fetch_ticker_cached(t_in)
        if p:
            st.write(f"### {t_in} - 현재가: ${p:.2f}")
            with st.expander("📋 SEC 실시간 공시"):
                filings, err = get_sec_filings(t_in)
                if filings:
                    for f in filings: st.markdown(f"- [{f['form']}]({f['url']}) : {f['date']}")
                else: st.write(err)
with tabs[5]:
    st.subheader("🌍 실시간 마켓 뉴스")
    feed = feedparser.parse("https://news.google.com/rss/search?q=global+stock+market&hl=en-US&gl=US&ceid=US:en")
    for e in feed.entries[:10]: st.markdown(f"- [{e.title}]({e.link})")
