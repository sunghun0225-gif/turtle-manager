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
# 2. 분석 엔진 (터틀 & 시장 필터)
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy = spy['Close'].iloc[-1]
        ma200_now = spy['MA200'].iloc[-1]
        last_6_ma200 = spy['MA200'].tail(6).values
        is_trending_up = all(last_6_ma200[i] > last_6_ma200[i-1] for i in range(1, 6))
        is_bull = (curr_spy > ma200_now) and is_trending_up
        return is_bull, curr_spy, ma200_now, is_trending_up
    except: return True, 0, 0, False

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
# 3. 추가 엔진 (미국 개별 분석 및 KST 뉴스)
# ==========================================
FILING_LABELS = {
    "10-K": "📊 연간보고서", "20-F": "📊 연간보고서(외국)", "10-Q": "📋 분기보고서",
    "8-K":  "🔔 중요공시", "DEF 14A": "🗳️ 주주총회", "SC 13G": "📌 대량보유",
    "SC 13D": "📌 대량보유(적극)", "S-1":  "🚀 IPO신고", "4": "👤 내부자거래",
    "3": "👤 내부자최초", "5": "👤 내부자연간",
}

def filing_label(form):
    for key, label in FILING_LABELS.items():
        if form == key or form.startswith(key): return label
    return f"📄 {form}"

def fetch_history_safe(ticker_obj, period="5d", retries=3, base_delay=2):
    for attempt in range(retries):
        try:
            h = ticker_obj.history(period=period)
            if not h.empty: return h
        except:
            if attempt < retries - 1: time.sleep(base_delay * (attempt + 1))
    return None

def fetch_ticker_cached(ticker: str):
    now = time.time()
    cache = st.session_state["price_cache"]
    if ticker in cache:
        price, ts, info_cached = cache[ticker]
        if now - ts < CACHE_TTL: return price, info_cached, True
    try:
        s = yf.Ticker(ticker)
        h = fetch_history_safe(s, period="5d")
        if h is not None and not h.empty:
            price = h["Close"].iloc[-1]
            try: info = s.info
            except: info = {}
            cache[ticker] = (price, now, info)
            return price, info, False
    except: pass
    return None, {}, False

@st.cache_data(ttl=86400)
def get_cik(ticker: str):
    try:
        headers = {"User-Agent": "SwingScanner/1.0 contact@example.com"}
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
        for entry in res.json().values():
            if entry["ticker"].upper() == ticker.upper(): return str(entry["cik_str"])
    except: pass
    return None

def get_sec_filings(ticker: str, limit: int = 12):
    cik = get_cik(ticker)
    if not cik: return None, "CIK를 찾을 수 없습니다."
    try:
        headers = {"User-Agent": "SwingScanner/1.0 contact@example.com"}
        url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        res = requests.get(url, headers=headers, timeout=10)
        sub = res.json()
        recent = sub.get("filings", {}).get("recent", {})
        if not recent: return None, "공시 데이터가 없습니다."
        forms, dates, acc_times = recent.get("form", []), recent.get("filingDate", []), recent.get("acceptanceDateTime", [])
        filings = []
        for i in range(len(forms)):
            if i < len(acc_times) and acc_times[i]:
                raw_dt = acc_times[i]
                try:
                    dt_kst = datetime.strptime(raw_dt[:16], "%Y-%m-%dT%H:%M") + timedelta(hours=9)
                    display_date, sort_key = dt_kst.strftime("%Y-%m-%d %H:%M (KST)"), raw_dt
                except: display_date, sort_key = dates[i], dates[i] + "T00:00:00"
            else: display_date, sort_key = dates[i], dates[i] + "T00:00:00"
            filings.append({"form": forms[i], "date": display_date, "sort_key": sort_key, "label": filing_label(forms[i]), "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={forms[i]}&dateb=&owner=include&count=10", "cik": cik})
        filings.sort(key=lambda x: x['sort_key'], reverse=True)
        return filings[:limit], None
    except Exception as e: return None, f"오류: {e}"

def get_stock_news(query_name, market="US"):
    import urllib.parse
    news_list = []
    try:
        query = urllib.parse.quote(f"{query_name} stock")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={query}+when:90d&hl=en-US&gl=US&ceid=US:en")
        for entry in feed.entries[:20]:
            raw = entry.get("published_parsed")
            if raw:
                dt_kst = datetime(*raw[:6]) + timedelta(hours=9)
                date_str = dt_kst.strftime("%Y-%m-%d %H:%M (KST)")
            else: date_str = "날짜/시간 미상"
            news_list.append({"title": entry.title, "link": entry.link, "date": date_str, "raw_time": raw})
        news_list.sort(key=lambda x: x['raw_time'] if x['raw_time'] else time.localtime(0), reverse=True)
    except: pass
    return news_list[:8]

# ==========================================
# 4. 메인 UI 및 세션 초기화
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.22", layout="centered", page_icon="🐢")

if "positions" not in st.session_state: st.session_state.positions = load_data()
if "my_tickers_us" not in st.session_state: st.session_state["my_tickers_us"] = []
if "price_cache" not in st.session_state: st.session_state["price_cache"] = {}

# --- 사이드바 ---
st.sidebar.header("⚙️ 리스크 및 백업")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", min_value=100, value=200, step=50)
total_capital = int(cap_manwon * 10000)
st.sidebar.markdown(f"### 💰 **₩ {total_capital:,}**")
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 감수율 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", min_value=1000, value=1450, step=10)

st.sidebar.divider()
uploaded_file = st.sidebar.file_uploader("📂 백업 CSV 업로드")
if uploaded_file is not None and st.sidebar.button("데이터 즉시 복구", type="primary"):
    try:
        df = pd.read_csv(uploaded_file)
        st.session_state.positions = {row['Ticker']: {'Units': int(row['Units']), 'Highest': float(row['Highest']), 'History': json.loads(row['History']), 'Strategy': row['Strategy']} for _, row in df.iterrows()}
        save_data(st.session_state.positions); st.sidebar.success("✅ 복구 완료!"); st.rerun()
    except: st.sidebar.error("❌ 파일 형식 오류 (CSV 파일이 맞는지 확인해주세요)")

# --- 메인 타이틀 ---
st.title("🐢 Turtle System Pro V7.22")

is_bull, spy_val, ma200_val, is_trending_up = check_market_filter()
if is_bull:
    st.success(f"🟢 **시장 필터 통과 (대세 상승장)** | SPY: ${spy_val:.2f} | 200일선: 우상향 중")
else:
    trend_text = "우상향" if is_trending_up else "꺾임/하락"
    st.error(f"🔴 **시장 필터 경고 (대세 하락/혼조)** | SPY: ${spy_val:.2f} | 200일선 추세: {trend_text}")

current_total_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
c_d1, c_d2, c_d3 = st.columns(3)
c_d1.metric("총 관리 유닛", f"{current_total_units}/{MAX_TOTAL_UNITS} U")
c_d2.metric("계좌 위험도", f"{current_total_units * (risk_per_unit * 100):.1f}%")
c_d3.metric("보유 종목", f"{len(st.session_state.positions)}개")

st.divider()
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🚀 1. 터틀 스캐너", "📋 2. 포지션 매니저", "📉 3. 낙폭과대 스캐너", "🇺🇸 4. 미국 종목 분석", "🌍 5. 세계 경제 뉴스"])

# --- 탭 1 & 3: 스캐너 ---
for tab, strat_name in zip([tab1, tab3], ["🚀 터틀-상승", "📉 낙폭-하강"]):
    with tab:
        st.subheader(f"{strat_name} 종목 검색")
        if st.button(f"🚀 {strat_name} 분석 시작", key=f"btn_{strat_name}", use_container_width=True):
            my_bar = st.progress(0, text="분석 중...")
            results = []
            for i, tkr in enumerate(TICKERS):
                my_bar.progress((i+1)/len(TICKERS))
                data = analyze_ticker(tkr)
                if data is not None:
                    latest, prev = data.iloc[-1], data.iloc[-2]
                    cond = (latest['Close'] > latest['High55']) if "터틀" in strat_name else ((data['Low'].iloc[-3:] <= data['BB_Lower'].iloc[-3:]).any() and latest['Close'] > latest['MA5'] and prev['Close'] <= prev['MA5'])
                    if cond:
                        risk_shares = int((total_capital * risk_per_unit) / (latest['N'] * exchange_rate)) if latest['N'] > 0 else 1
                        cash_shares = int((total_capital / MAX_TOTAL_UNITS) / (latest['Close'] * exchange_rate))
                        shares = max(1, min(risk_shares, cash_shares))
                        results.append({"Ticker": tkr, "Price": latest['Close'], "Shares": shares, "Strategy": strat_name})
            my_bar.empty(); st.session_state[f"res_{strat_name}"] = results
        
        for s in st.session_state.get(f"res_{strat_name}", []):
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"### {s['Ticker']}"); c2.write(f"현재가: ${s['Price']:.2f}"); c3.write(f"권장: {s['Shares']}주")
                if s['Ticker'] not in st.session_state.positions and st.button("➕ 등록", key=f"reg_{strat_name}_{s['Ticker']}", use_container_width=True):
                    st.session_state.positions[s['Ticker']] = {'Units': 1, 'Highest': s['Price'], 'History': [{'price': s['Price'], 'shares': s['Shares']}], 'Strategy': s['Strategy']}
                    save_data(st.session_state.positions); st.rerun()

# --- 탭 2: 통합 매니저 ---
with tab2:
    with st.expander("✍️ 보유 종목 수기 등록 (전략 선택)", expanded=False):
        m1, m2, m3, m4 = st.columns(4)
        m_tkr = m1.text_input("티커", key="m_tkr").upper()
        m_str = m2.selectbox("적용 전략", ["🚀 터틀-상승", "📉 낙폭-하강"], key="m_str")
        m_prc = m3.number_input("단가", min_value=0.0, format="%.2f", key="m_prc")
        m_shr = m4.number_input("수량", min_value=1, step=1, key=m_tkr+"_s")
        if st.button("➕ 직접 등록 실행", type="primary", use_container_width=True):
            if m_tkr and analyze_ticker(m_tkr) is not None:
                st.session_state.positions[m_tkr] = {'Units': 1, 'Highest': m_prc, 'History': [{'price': m_prc, 'shares': m_shr}], 'Strategy': m_str}
                save_data(st.session_state.positions); st.success(f"{m_tkr} 등록 완료!"); time.sleep(0.5); st.rerun()
            else: st.error("유효한 티커를 입력하세요.")
    st.divider()
    
    if not st.session_state.positions: st.info("보유 포지션이 없습니다.")
    for tkr, pos in list(st.session_state.positions.items()):
        data = analyze_ticker(tkr)
        if data is None: continue
        latest = data.iloc[-1]; strat = pos.get('Strategy', '🚀 터틀-상승')
        total_shares = sum(h['shares'] for h in pos['History'])
        avg_entry = sum(h['price'] * h['shares'] for h in pos['History']) / total_shares if total_shares > 0 else 0
        profit_pct = (latest['Close'] / avg_entry) - 1 if avg_entry > 0 else 0
        if latest['Close'] > pos['Highest']: pos['Highest'] = latest['Close']; save_data(st.session_state.positions)
        
        # 추가 매수 권장 수량 실시간 계산 (공통)
        risk_shares = int((total_capital * risk_per_unit) / (latest['N'] * exchange_rate)) if latest['N'] > 0 else 1
        cash_shares = int((total_capital / MAX_TOTAL_UNITS) / (latest['Close'] * exchange_rate))
        add_shares = max(1, min(risk_shares, cash_shares))

        with st.container(border=True):
            c_t, c_d = st.columns([4, 1])
            c_t.markdown(f"#### **{tkr}** :{('blue' if '터틀' in strat else 'red')}[({strat})] - {total_shares}주")
            if c_d.button("종료", key=f"ex_{tkr}"): del st.session_state.positions[tkr]; save_data(st.session_state.positions); st.rerun()
            
            if "낙폭" in strat:
                if profit_pct >= 0.05: st.success("💰 **수익실현 권장 (+5% 도달)**")
                elif profit_pct <= -0.03: st.error("🛑 **손절 권장 (-3% 도달)**")
                else: st.info(f"✅ 보유 중 (수익률: {profit_pct:.2%})")
            else:
                stop, trail, donchian, add = avg_entry - 2*latest['N'], pos['Highest'] - 3*latest['N'], latest['Low20'], avg_entry + 0.5*latest['N']
                
                if latest['Close'] < stop: st.error(f"🛑 **[상황 A]** 초기손실방어선(${stop:.2f}) 이탈!")
                elif latest['Close'] < trail: st.error(f"💰 **[상황 C]** 최종추세이탈(${trail:.2f})!") 
                elif latest['Close'] >= add and pos['Units'] < MAX_UNIT_PER_STOCK: 
                    st.success(f"🚀 **[상황 B]** 불타기(${add:.2f}) 돌파! 👉 **추가 매수 권장: {add_shares}주**")
                elif latest['Close'] >= add and pos['Units'] >= MAX_UNIT_PER_STOCK:
                    st.success(f"🚀 **[상황 B]** 불타기(${add:.2f}) 돌파! (최대 보유 한도 도달로 관망)")
                else: st.info(f"✅ 순항 중 (수익률: {profit_pct:.2%})")
            
            with st.expander("📊 지표 차트 및 상세 관리"):
                chart_df = data.reset_index()[['Date', 'Close']].tail(90)
                base = alt.Chart(chart_df).encode(x=alt.X('Date:T', title=None))
                line = base.mark_line(color='#1f77b4').encode(y=alt.Y('Close:Q', scale=alt.Scale(zero=False)))
                
                if "낙폭" in strat:
                    levels = [
                        {'val': avg_entry, 'name': '평단가', 'col': 'gray'},
                        {'val': avg_entry*1.05, 'name': '5% 익절', 'col': 'green'}, 
                        {'val': avg_entry*1.1, 'name': '10% 목표', 'col': 'blue'}, 
                        {'val': avg_entry*0.97, 'name': '3% 손절', 'col': 'red'}
                    ]
                else:
                    levels = [
                        {'val': avg_entry, 'name': '평단가', 'col': 'gray'},
                        {'val': stop, 'name': '초기손실방어', 'col': 'red'},          
                        {'val': trail, 'name': '최종추세이탈', 'col': 'green'},      
                        {'val': add, 'name': '불타기', 'col': 'orange'}
                    ]
                
                levels.sort(key=lambda x: x['val'], reverse=True)
                
                layers = [line]
                for lv in levels:
                    layers.append(alt.Chart(pd.DataFrame({'y': [lv['val']]})).mark_rule(strokeDash=[5,5], color=lv['col']).encode(y='y:Q'))
                    layers.append(alt.Chart(pd.DataFrame({'Date': [chart_df['Date'].max()], 'y': [lv['val']], 't': [f"{lv['name']}: ${lv['val']:.2f}"]})).mark_text(align='left', dx=10, dy=-4, color=lv['col'], fontWeight='bold').encode(x='Date:T', y='y:Q', text='t:N'))
                st.altair_chart(alt.layer(*layers).properties(height=350), use_container_width=True)
                
                # 💡 신규 추가: 차트 바로 아래에 불타기 예정 수량 브리핑 표시
                if "터틀" in strat:
                    if pos['Units'] < MAX_UNIT_PER_STOCK:
                        st.info(f"💡 **불타기 영역 도달 시, 현재 보유기준 {add_shares}주 매수**")
                    else:
                        st.info(f"💡 **불타기 영역 도달 시, 최대 보유 한도({MAX_UNIT_PER_STOCK}U) 도달로 추가 매수 없음**")
                
                c1, c2 = st.columns(2)
                in_p = c1.number_input("단가", min_value=0.0, format="%.2f", key=f"p_{tkr}", value=latest['Close'])
                in_s = c2.number_input("수량", min_value=1, step=1, key=f"s_{tkr}")
                b1, b2 = st.columns(2)
                if b1.button("✅ 추가", key=f"a_{tkr}", use_container_width=True):
                    pos['History'].append({'price': in_p, 'shares': in_s}); pos['Units'] = min(MAX_UNIT_PER_STOCK, len(pos['History'])); save_data(st.session_state.positions); st.rerun()
                if b2.button("🔙 삭제", key=f"u_{tkr}", use_container_width=True) and len(pos['History']) > 1:
                    pos['History'].pop(); pos['Units'] = len(pos['History']); save_data(st.session_state.positions); st.rerun()
                st.markdown("**매수 내역**"); st.table(pd.DataFrame(pos['History']).style.format({'price': '{:.2f}'}))
    
    if st.session_state.positions:
        csv = pd.DataFrame([{'Ticker': k, **v, 'History': json.dumps(v['History'])} for k, v in st.session_state.positions.items()]).to_csv(index=False).encode('utf-8-sig')
        st.download_button(f"💾 전체 통합 백업 ({datetime.now().strftime('%y%m%d')})", csv, f"{datetime.now().strftime('%y%m%d')}_pos.csv", "text/csv", use_container_width=True)

# --- 탭 4 & 5: 뉴스 및 공시 ---
with tab4:
    st.subheader("🇺🇸 미국 종목 분석")
    t_in = st.text_input("티커 입력", key="us_in").upper()
    if st.button("분석 시작", key="start_us") and t_in:
        p, info, _ = fetch_ticker_cached(t_in)
        if p:
            st.info(f"**[{t_in}]** 현재가: ${p:.2f}")
            with st.expander("📋 SEC 실시간 공시 (KST)", expanded=True):
                filings, _ = get_sec_filings(t_in)
                if filings:
                    for f in filings:
                        ca, cb, cc = st.columns([3, 2, 2])
                        ca.write(f"**{f['label']}**"); cb.caption(f["date"]); cc.markdown(f"[원문]({f['url']})")
            with st.expander("📰 뉴스 & 홈페이지"):
                for n in get_stock_news(t_in): st.markdown(f"- [{n['title']}]({n['link']}) `[{n['date']}]`")
with tab5:
    st.subheader("🌍 세계 경제 뉴스 (KST)")
    if st.button("🔄 새로고침"): st.rerun()
    feed = feedparser.parse("https://news.google.com/rss/search?q=global+economy+market+when:24h&hl=en-US&gl=US&ceid=US:en")
    entries = feed.entries; entries.sort(key=lambda x: x.get("published_parsed") or time.localtime(0), reverse=True)
    for e in entries[:10]:
        raw = e.get("published_parsed")
        dt_kst = datetime(*raw[:6]) + timedelta(hours=9) if raw else None
        st.markdown(f"📍 [{e.title}]({e.link}) `[{dt_kst.strftime('%Y-%m-%d %H:%M (KST)') if dt_kst else '미상'}]`")
