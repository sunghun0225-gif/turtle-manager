import streamlit as st
import yfinance as yf
import pandas as pd
import os
import time
import requests
import json
import altair as alt
import feedparser
import urllib.parse
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
            # [FIX 2 적용] History 안전 파싱
            raw_history = row['History']
            if isinstance(raw_history, str):
                history = json.loads(raw_history)
            elif isinstance(raw_history, list):
                history = raw_history
            else:
                history = []
                
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
        return (curr_spy > ma200_now) and is_trending_up, curr_spy, ma200_now, is_trending_up
    except: 
        return True, 0, 0, False

@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="1y")
        if len(df) < 200: 
            return None
            
        # yfinance 최신버전 MultiIndex 대응
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
        
        # [FIX 1 적용] TR 계산 안정성 강화
        df['prev_close'] = df['Close'].shift(1)
        df['TR'] = df.apply(
            lambda x: max(
                x['High'] - x['Low'],
                abs(x['High'] - x['prev_close']) if pd.notna(x['prev_close']) else 0,
                abs(x['Low']  - x['prev_close']) if pd.notna(x['prev_close']) else 0
            ), axis=1
        )
        df.drop(columns=['prev_close'], inplace=True)
        
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        df['MA200'] = df['Close'].rolling(200).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA5'] = df['Close'].rolling(5).mean()
        df['Std'] = df['Close'].rolling(20).std()
        df['BB_Lower'] = df['MA20'] - (df['Std'] * 2)
        
        # RSI (EMA 방식)
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (avg_gain / (avg_loss + 1e-9)))) # 분모 0 방지
        
        return df 
    except: 
        return None

# ==========================================
# 3. 보조 분석 툴 (SEC & KST 뉴스)
# ==========================================
FILING_LABELS = {"10-K": "📊 연간보고서", "10-Q": "📋 분기보고서", "8-K": "🔔 중요공시", "4": "👤 내부자거래"}

@st.cache_data(ttl=86400)
def get_cik(ticker: str):
    try:
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "TurtlePro/1.0"}).json()
        for v in res.values():
            if v["ticker"].upper() == ticker.upper(): return str(v["cik_str"]).zfill(10)
    except: return None

def get_sec_filings(ticker: str):
    cik = get_cik(ticker)
    if not cik: return []
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        res = requests.get(url, headers={"User-Agent": "TurtlePro/1.0"}).json()
        recent = res.get("filings", {}).get("recent", {})
        filings = []
        for i in range(min(10, len(recent.get("form", [])))):
            form = recent["form"][i]
            label = FILING_LABELS.get(form, f"📄 {form}")
            filings.append({"form": label, "date": recent["filingDate"][i], "url": f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={cik}&action=getcompany"})
        return filings
    except: return []

def get_stock_news(query_name):
    news_list = []
    try:
        query = urllib.parse.quote(f"{query_name} stock")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={query}+when:90d&hl=en-US&gl=US&ceid=US:en")
        for entry in feed.entries[:15]:
            raw = entry.get("published_parsed")
            if raw:
                dt_kst = datetime(*raw[:6]) + timedelta(hours=9)
                date_str = dt_kst.strftime("%Y-%m-%d %H:%M (KST)")
            else:
                date_str = "시간 미상"
            news_list.append({"title": entry.title, "link": entry.link, "date": date_str, "raw": raw})
        news_list.sort(key=lambda x: x['raw'] if x['raw'] else time.localtime(0), reverse=True)
        return news_list[:8]
    except:
        return []

# ==========================================
# 4. 메인 UI 및 사이드바 (백업 복원 포함)
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.37", layout="centered", page_icon="🐢")

if "positions" not in st.session_state: 
    st.session_state.positions = load_data()

st.sidebar.header("⚙️ 리스크 및 백업")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", value=200, step=50)
total_capital = int(cap_manwon * 10000)
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("환율 (₩/$)", value=1450, step=10)

st.sidebar.divider()
up_file = st.sidebar.file_uploader("📂 백업 CSV 업로드")
if up_file and st.sidebar.button("데이터 즉시 복구", type="primary"):
    try:
        df = pd.read_csv(up_file)
        recovered = {}
        for _, row in df.iterrows():
            raw = row['History']
            history = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
            recovered[row['Ticker']] = {
                'Units': int(row['Units']),
                'Highest': float(row['Highest']),
                'History': history,
                'Strategy': row['Strategy']
            }
        st.session_state.positions = recovered
        save_data(st.session_state.positions)
        st.sidebar.success("복구 완료!")
        st.rerun()
    except: 
        st.sidebar.error("파일 형식 오류")

st.title("🐢 Turtle System Pro V7.37")
is_bull, spy_val, _, _ = check_market_filter()
if is_bull: 
    st.success(f"🟢 **시장 대세 상승** | SPY: ${spy_val:.2f}")
else: 
    st.error(f"🔴 **시장 주의보** | SPY: ${spy_val:.2f}")

c1, c2, c3 = st.columns(3)
t_units = sum(pos['Units'] for pos in st.session_state.positions.values())
c1.metric("총 유닛", f"{t_units}/{MAX_TOTAL_UNITS} U")
c2.metric("계좌 위험도", f"{t_units * (risk_per_unit * 100):.1f}%")
c3.metric("보유 종목", f"{len(st.session_state.positions)}개")

st.divider()
tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 매니저", "🇺🇸 분석", "🌍 뉴스"])

# ==========================================
# 5. 스캐너 탭 (3대 전략 + 포착 대기 모드)
# ==========================================
for i, s_name in enumerate(["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"]):
    with tabs[i]:
        c_a, c_b = st.columns([3, 2])
        is_run = c_a.button(f"🔎 {s_name} 스캔 시작", key=f"r_{i}", use_container_width=True)
        is_cand = c_b.checkbox("⚠️ 포착 대기 포함", key=f"c_{i}")
        
        if is_run:
            res = []
            pb = st.progress(0, text="S&P 500 전수 조사 중...")
            for idx, tkr in enumerate(TICKERS):
                pb.progress((idx+1)/len(TICKERS))
                df = analyze_ticker(tkr)
                if df is not None:
                    lt, pv = df.iloc[-1], df.iloc[-2]
                    cond, cand = False, False
                    
                    if "터틀" in s_name:
                        cond = (lt['Close'] > lt['High55']) and (lt['Close'] > lt['MA200']) and (50 <= lt['RSI'] < 70)
                        if is_cand and not cond: 
                            cand = (lt['Close'] > lt['High55'] * 0.98) and (lt['Close'] > lt['MA200'])
                            
                    elif "눌림목" in s_name:
                        t20 = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                        cond = t20 and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                        if is_cand and not cond: 
                            cand = t20 and (lt['Close'] > lt['MA200'])
                            
                    else: # BB낙폭
                        tbb = (df['Low'].iloc[-3:] <= df['BB_Lower'].iloc[-3:]).any()
                        cond = tbb and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                        if is_cand and not cond: 
                            cand = tbb and (lt['Close'] > lt['MA200'])
                    
                    if cond or cand:
                        sh = int((total_capital * risk_per_unit) / (lt['N'] * exchange_rate)) if lt['N'] > 0 else 1
                        res.append({"tkr": tkr, "p": lt['Close'], "sh": sh, "is_cand": cand})
                        
            pb.empty()
            if not res: st.info("조건 부합 종목 없음")
            
            for r in res:
                with st.container(border=True):
                    l, rt = st.columns([3, 1])
                    tag = " [⚠️ 대기]" if r['is_cand'] else " [✅ 포착]"
                    l.write(f"### {r['tkr']}{tag}\n가: ${r['p']:.2f} | {r['sh']}주 권장")
                    if not r['is_cand'] and rt.button("등록", key=f"reg_{r['tkr']}_{i}"):
                        st.session_state.positions[r['tkr']] = {
                            'Units': 1, 
                            'Highest': r['p'], 
                            'History': [{'price': r['p'], 'shares': r['sh']}], 
                            'Strategy': s_name
                        }
                        save_data(st.session_state.positions)
                        st.rerun()

# ==========================================
# 6. 매니저 탭 (수기 등록 / 유닛 관리 / 복원된 차트)
# ==========================================
with tabs[3]:
    with st.expander("✍️ 수기 종목 등록", expanded=False):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_t = mc1.text_input("티커").upper()
        m_s = mc2.selectbox("전략", ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"])
        m_p = mc3.number_input("진입단가", value=0.0)
        m_h = mc4.number_input("수량(주)", value=1)
        if st.button("➕ 포지션 등록", use_container_width=True):
            if m_t:
                st.session_state.positions[m_t] = {
                    'Units': 1, 
                    'Highest': m_p, 
                    'History': [{'price': m_p, 'shares': m_h}], 
                    'Strategy': m_s
                }
                save_data(st.session_state.positions)
                st.rerun()

    st.divider()
    for tkr, pos in list(st.session_state.positions.items()):
        # [FIX 3 적용] Units 항상 동기화
        pos['Units'] = len(pos['History'])
        
        df = analyze_ticker(tkr)
        if df is None: continue
        
        lt = df.iloc[-1]
        st_n = pos['Strategy']
        total_s = sum(h['shares'] for h in pos['History'])
        
        # [FIX 4 적용] ZeroDivisionError 방지
        if total_s > 0:
            avg_e = sum(h['price'] * h['shares'] for h in pos['History']) / total_s
            profit = (lt['Close'] / avg_e - 1) if avg_e > 0 else 0.0
        else:
            avg_e, profit = 0.0, 0.0

        if lt['Close'] > pos['Highest']: 
            pos['Highest'] = lt['Close']
            save_data(st.session_state.positions)
        
        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            s_c = "blue" if "터틀" in st_n else ("green" if "눌림목" in st_n else "red")
            h1.markdown(f"#### {tkr} :{s_c}[({st_n})] - {total_s}주")
            if h2.button("종료", key=f"ex_{tkr}"): 
                del st.session_state.positions[tkr]
                save_data(st.session_state.positions)
                st.rerun()
            
            # --- 전략별 가이드라인 세팅 (차트 라인 완벽 복원) ---
            lvls = [{'val': avg_e, 'name': '평단가', 'col': 'gray'}]
            
            if "눌림목" in st_n:
                tp, sl = avg_e * 1.06, avg_e * 0.96
                lvls += [{'val': tp, 'name': '6%익절', 'col': 'blue'}, {'val': sl, 'name': '4%손절', 'col': 'red'}]
                if profit >= 0.06: st.success("💰 수익실현 시점")
                elif profit <= -0.04: st.error("🛑 손절 시점")
                    
            elif "BB" in st_n:
                tp, sl = avg_e * 1.05, avg_e * 0.95
                lvls += [{'val': tp, 'name': '5%익절', 'col': 'blue'}, {'val': sl, 'name': '5%손절', 'col': 'red'}]
                if profit >= 0.05: st.success("💰 수익실현 시점")
                elif profit <= -0.05: st.error("🛑 손절 시점")
                    
            else: # 터틀
                stop  = avg_e - 2 * lt['N']
                trail = pos['Highest'] - 3 * lt['N']
                don   = lt['Low20']
                add   = avg_e + 0.5 * lt['N']
                lvls += [
                    {'val': stop,  'name': '손절(2N)',     'col': 'red'},
                    {'val': trail, 'name': '최종추세이탈', 'col': 'green'},
                    {'val': don,   'name': '20일저가',    'col': 'brown'},
                    {'val': add,   'name': '불타기',      'col': 'orange'}
                ]
                if lt['Close'] < stop or lt['Close'] < don or lt['Close'] < trail:
                    st.error("🛑 추세 이탈 경고")
                elif lt['Close'] >= add and pos['Units'] < MAX_UNIT_PER_STOCK:
                    st.success("🚀 불타기 가능 구간")

            lvls.append({'val': lt['Close'], 'name': '현재가', 'col': 'purple'})

            # --- 차트 렌더링 ---
            c_df = df.reset_index()[['Date', 'Close']].tail(60)
            base = alt.Chart(c_df).encode(x='Date:T')
            line = base.mark_line(color='#1f77b4').encode(y=alt.Y('Close:Q', scale=alt.Scale(zero=False)))
            rules = []
            for lv in lvls:
                rules.append(alt.Chart(pd.DataFrame({'y': [lv['val']]})).mark_rule(strokeDash=[5,5], color=lv['col']).encode(y='y:Q'))
                rules.append(alt.Chart(pd.DataFrame({'Date':[c_df['Date'].max()],'y':[lv['val']],'t':[f"{lv['name']}: ${lv['val']:.2f}"]}))
                             .mark_text(align='left', dx=5, dy=-4, color=lv['col'], fontWeight='bold').encode(x='Date:T', y='y:Q', text='t:N'))
            st.altair_chart(alt.layer(line, *rules).properties(height=300), use_container_width=True)
            
            # --- 유닛 개별 관리 (추가/삭제) ---
            cc1, cc2 = st.columns(2)
            u_p = cc1.number_input("추가 단가", value=float(lt['Close']), key=f"up_{tkr}")
            u_s = cc2.number_input("추가 수량", value=1, key=f"us_{tkr}")
            b_a, b_d = st.columns(2)
            if b_a.button("✅ 유닛 추가", key=f"ba_{tkr}", use_container_width=True):
                pos['History'].append({'price': u_p, 'shares': u_s})
                pos['Units'] = len(pos['History'])
                save_data(st.session_state.positions); st.rerun()
            if b_d.button("🔙 최근 유닛 취소", key=f"bd_{tkr}", use_container_width=True) and len(pos['History']) > 1:
                pos['History'].pop()
                pos['Units'] = len(pos['History'])
                save_data(st.session_state.positions); st.rerun()
                
            st.table(pd.DataFrame(pos['History']).style.format({'price': '{:.2f}'}))

    if st.session_state.positions:
        csv_data = pd.DataFrame([{'Ticker': k, **{kk:vv for kk,vv in v.items() if kk != 'History'}, 'History': json.dumps(v['History'])} for k, v in st.session_state.positions.items()]).to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 전체 통합 데이터 백업", csv_data, f"Turtle_Final_{datetime.now().strftime('%y%m%d')}.csv", "text/csv", use_container_width=True)

# ==========================================
# 7. 분석 / 뉴스 탭 (UI & 기능 완벽 복원)
# ==========================================
with tabs[4]:
    st.subheader("🇺🇸 개별 종목 정밀 분석")
    t_in = st.text_input("상세 분석할 티커 입력").upper()
    if t_in and st.button("분석 시작", use_container_width=True):
        d = analyze_ticker(t_in)
        if d is not None:
            st.info(f"**[{t_in}]** 현재가: **${d['Close'].iloc[-1]:.2f}** | RSI(14): **{d['RSI'].iloc[-1]:.1f}**")
            
            with st.expander("📋 SEC 실시간 주요 공시 (KST)", expanded=True):
                fils = get_sec_filings(t_in)
                if fils:
                    for f in fils:
                        c_a, c_b, c_c = st.columns([3, 2, 2])
                        c_a.write(f"**{f['form']}**"); c_b.caption(f['date']); c_c.markdown(f"[원문 링크]({f['url']})")
                else: st.write("최근 공시 데이터가 없습니다.")
            
            with st.expander("📰 개별 종목 최신 뉴스", expanded=True):
                s_news = get_stock_news(t_in)
                if s_news:
                    for n in s_news: st.markdown(f"- [{n['title']}]({n['link']}) `[{n['date']}]`")
                else: st.write("관련 뉴스를 불러오지 못했습니다.")

with tabs[5]:
    st.subheader("🌍 글로벌 마켓 핵심 뉴스 (KST)")
    if st.button("🔄 실시간 뉴스 새로고침"): st.rerun()
        
    f_p = feedparser.parse("https://news.google.com/rss/search?q=global+economy+market+when:24h&hl=en-US&gl=US&ceid=US:en")
    for e in f_p.entries[:10]:
        raw = e.get("published_parsed")
        if raw:
            dt = datetime(*raw[:6]) + timedelta(hours=9)
            date_str = dt.strftime('%m-%d %H:%M')
        else:
            date_str = "시간 미상"
        st.markdown(f"📍 [{e.title}]({e.link}) `[{date_str}]`")
