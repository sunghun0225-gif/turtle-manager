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
# 1. 설정 및 전략별 리스크 파라미터 (V7.5 적용)
# ==========================================
DB_FILE = 'internal_memory.csv'
MAX_TOTAL_UNITS = 10
CACHE_TTL = 300

# [NEW] 전략별 개별 설정 적용
STRATEGY_CONFIG = {
    "🚀 터틀-상승": {
        "risk_pct": 1.5,           
        "max_unit_per_stock": 4,   
        "donchian_entry": 20,      
        "trailing_days": 10,       
        "pyramid_n": 0.5,
        "initial_stop_n": 2.0
    },
    "📈 20일-눌림목": {
        "risk_pct": 2.0,
        "max_unit_per_stock": 2,
    },
    "📉 BB-낙폭과대": {
        "risk_pct": 2.5,
        "max_unit_per_stock": 2,
    }
}

DEFAULT_RISK_PCT = 2.0

# [NEW] yfinance 안정성 강화 (Rate Limit + Retry)
def safe_download(ticker_symbol, period="1y", retries=3):
    for attempt in range(retries):
        try:
            df = yf.download(ticker_symbol, period=period, progress=False, timeout=15)
            if len(df) > 100:
                return df
        except Exception:
            if attempt == retries - 1:
                st.toast(f"⚠️ {ticker_symbol} 데이터 로드 실패 (재시도 {attempt+1}/{retries})", icon="⚠️")
            time.sleep(1.5 ** attempt) 
    return None

@st.cache_data(ttl=86400)
def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0'}
        html = requests.get(url, headers=headers, verify=False, timeout=10).text
        table = pd.read_html(html)[0]
        tickers = table['Symbol'].tolist()
        return [ticker.replace('.', '-') for ticker in tickers]
    except:
        return ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B', 'JNJ', 'JPM']

TICKERS = get_sp500_tickers()

# ==========================================
# 2. 데이터 입출력
# ==========================================
def load_data():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        positions = {}
        for _, row in df.iterrows():
            raw_history = row['History']
            if isinstance(raw_history, str):
                history = json.loads(raw_history)
            elif isinstance(raw_history, list):
                history = raw_history
            else:
                history = []

            # [NEW] last_pyramid_level 속성 추가 로드
            positions[row['Ticker']] = {
                'Units': len(history),
                'Highest': float(row['Highest']),
                'History': history,
                'Strategy': row['Strategy'] if 'Strategy' in df.columns else '🚀 터틀-상승',
                'last_pyramid_level': row.get('last_pyramid_level') if 'last_pyramid_level' in df.columns else None
            }
        return positions
    return {}

def save_data(positions):
    if positions:
        rows = []
        for tkr, data in positions.items():
            history = data.get('History', [])
            if not isinstance(history, list):
                try:
                    history = json.loads(history)
                except Exception:
                    history = []
            rows.append({
                'Ticker': tkr,
                'Units': len(history),
                'Highest': data['Highest'],
                'History': json.dumps(history),
                'Strategy': data.get('Strategy', '🚀 터틀-상승'),
                'last_pyramid_level': data.get('last_pyramid_level')
            })
        pd.DataFrame(rows).to_csv(DB_FILE, index=False)
    elif os.path.exists(DB_FILE):
        os.remove(DB_FILE)

# ==========================================
# 3. 분석 엔진
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = safe_download("SPY", period="1y") # [NEW] safe_download 적용
        if spy is None: return True, 0, 0, False
        
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)
            
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy = spy['Close'].iloc[-1]
        ma200_now = spy['MA200'].iloc[-1]
        last_6_ma200 = spy['MA200'].tail(6)
        is_trending_up = all(last_6_ma200.iloc[i] > last_6_ma200.iloc[i-1] for i in range(1, 6))
        return (curr_spy > ma200_now) and is_trending_up, curr_spy, ma200_now, is_trending_up
    except:
        return True, 0, 0, False

@st.cache_data(ttl=1800)
def analyze_ticker(ticker):
    try:
        df = safe_download(ticker) # [NEW] safe_download 적용
        if df is None or len(df) < 200:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.copy()
        df['prev_close'] = df['Close'].shift(1)
        df['TR'] = df.apply(lambda x: max(x['High']-x['Low'], 
                                           abs(x['High']-x['prev_close']) if pd.notna(x['prev_close']) else 0,
                                           abs(x['Low']-x['prev_close']) if pd.notna(x['prev_close']) else 0), axis=1)
        df.drop(columns=['prev_close'], inplace=True)
        df['N'] = df['TR'].rolling(20).mean()
        
        # [NEW] Donchian & Trailing 지표 추가 (20/55/10)
        df['High20'] = df['High'].rolling(20).max().shift(1)
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low10'] = df['Low'].rolling(10).min().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        
        df['MA200'] = df['Close'].rolling(200).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA5'] = df['Close'].rolling(5).mean()
        df['Std'] = df['Close'].rolling(20).std()
        df['BB_Lower'] = df['MA20'] - (df['Std'] * 2)
        df['BB_Upper'] = df['MA20'] + (df['Std'] * 2)

        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (avg_gain / (avg_loss + 1e-9))))
        return df
    except:
        return None

# ==========================================
# 3-1. 보조 분석 툴 (SEC & 뉴스 - V7.43 복원)
# ==========================================
FILING_LABELS = {
    "10-K": "📊 연간보고서", "10-Q": "📋 분기보고서", "8-K": "🔔 중요공시", "4": "👤 내부자거래"
}

@st.cache_data(ttl=86400)
def get_cik(ticker: str):
    try:
        headers = {"User-Agent": "TurtlePro/1.0"}
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, verify=False).json()
        for v in res.values():
            if v["ticker"].upper() == ticker.upper():
                return str(v["cik_str"]).zfill(10)
    except: return None

def get_sec_filings(ticker: str):
    cik = get_cik(ticker)
    if not cik: return []
    try:
        headers = {"User-Agent": "TurtlePro/1.0"}
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        res = requests.get(url, headers=headers, verify=False).json()
        recent = res.get("filings", {}).get("recent", {})
        filings = []
        for i in range(min(10, len(recent.get("form", [])))):
            form = recent["form"][i]
            label = FILING_LABELS.get(form, f"📄 {form}")
            filings.append({
                "form": label, "date": recent["filingDate"][i], 
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={cik}&action=getcompany"
            })
        return filings
    except: return []

def get_stock_news(query_name):
    news_list = []
    try:
        query = urllib.parse.quote(f"{query_name} stock")
        url = f"https://news.google.com/rss/search?q={query}+when:90d&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        for entry in feed.entries[:15]:
            raw = entry.get("published_parsed")
            dt_kst = datetime(*raw[:6]) + timedelta(hours=9) if raw else None
            date_str = dt_kst.strftime("%Y-%m-%d %H:%M (KST)") if dt_kst else "시간 미상"
            news_list.append({
                "title": entry.title, "link": entry.link, "date": date_str, "raw": raw if raw else (0,)*9
            })
        news_list.sort(key=lambda x: x['raw'], reverse=True)
        return news_list[:8]
    except: return []

@st.cache_data(ttl=1800)
def get_global_news():
    try:
        feed = feedparser.parse("https://news.google.com/rss/search?q=global+economy+market+when:24h&hl=en-US&gl=US&ceid=US:en")
        result = []
        for e in feed.entries[:10]:
            raw = e.get("published_parsed")
            dt = datetime(*raw[:6]) + timedelta(hours=9) if raw else None
            date_str = dt.strftime('%Y-%m-%d %H:%M') if dt else "시간 미상"
            result.append({"title": e.title, "link": e.link, "date": date_str})
        return result
    except: return []

# ==========================================
# 4. 메인 UI 및 사이드바
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.50", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions = load_data()

st.sidebar.header("⚙️ 리스크 및 시스템 설정")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", value=200, step=50)
total_capital = int(cap_manwon * 10000)
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", value=1450, step=10)

st.sidebar.info("💡 **위험 감수율(%) 안내:**\nV7.50부터는 일괄 설정 대신 종목 스캔 시 **전략별 최적화된 리스크**(터틀 1.5%, 눌림목 2.0%, 낙폭 2.5%)가 자동 적용됩니다.")

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
                'Units': len(history),
                'Highest': float(row['Highest']),
                'History': history,
                'Strategy': row['Strategy'],
                'last_pyramid_level': row.get('last_pyramid_level') if 'last_pyramid_level' in df.columns else None
            }
        st.session_state.positions = recovered
        save_data(st.session_state.positions)
        st.sidebar.success("✅ 백업 데이터 복구 완료!")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"❌ 파일 형식 오류: {e}")

st.title("🐢 Turtle System Pro V7.50")

is_bull, spy_val, ma200_val, is_trending_up = check_market_filter()
trend_label = "📈 MA200 우상향" if is_trending_up else "➡️ MA200 횡보/하향"
if is_bull: st.success(f"🟢 **시장 필터 통과 (대세 상승)** | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {trend_label}")
else: st.error(f"🔴 **시장 필터 경고 (대세 하락)** | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {trend_label}")

c1, c2, c3 = st.columns(3)
t_units = sum(pos['Units'] for pos in st.session_state.positions.values())
c1.metric("총 관리 유닛", f"{t_units}/{MAX_TOTAL_UNITS} U")

# 계좌 위험도 표시 (근사치)
avg_risk = sum([STRATEGY_CONFIG.get(p['Strategy'], {}).get("risk_pct", 2.0) * p['Units'] for p in st.session_state.positions.values()])
c2.metric("계좌 전체 위험도", f"{avg_risk:.1f}%")
c3.metric("현재 보유 종목", f"{len(st.session_state.positions)}개")

st.divider()
tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 포지션 매니저", "🇺🇸 정밀 분석", "🌍 마켓 뉴스"])

# ==========================================
# 5. 스캐너 탭 (전략별 설정 연동)
# ==========================================
strategies = ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"]

for i, s_name in enumerate(strategies):
    with tabs[i]:
        config = STRATEGY_CONFIG.get(s_name, {"risk_pct": DEFAULT_RISK_PCT, "max_unit_per_stock": 2})
        col_btn, col_chk = st.columns([3, 2])
        is_run = col_btn.button(f"🔎 {s_name} 스캐너 실행", key=f"run_{i}", use_container_width=True)
        is_cand = col_chk.checkbox("⚠️ 포착 대기 종목 포함", key=f"cand_{i}")

        if is_run:
            res = []
            pb = st.progress(0, text="S&P 500 전 종목 분석 중...")

            for idx, tkr in enumerate(TICKERS):
                pb.progress((idx + 1) / len(TICKERS))
                df = analyze_ticker(tkr)

                if df is not None:
                    lt = df.iloc[-1]
                    pv = df.iloc[-2]
                    cond, cand = False, False

                    if "터틀" in s_name:
                        period = config.get("donchian_entry", 20)
                        cond = (lt['Close'] > lt[f'High{period}']) and (lt['Close'] > lt['MA200']) and (50 <= lt['RSI'] < 70)
                        if is_cand and not cond:
                            cand = (lt['Close'] > lt[f'High{period}'] * 0.98) and (lt['Close'] > lt['MA200'])

                    elif "눌림목" in s_name:
                        t20 = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                        cond = t20 and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                        if is_cand and not cond: cand = t20 and (lt['Close'] > lt['MA200'])

                    else:  
                        tbb = (df['Low'].iloc[-3:] <= df['BB_Lower'].iloc[-3:]).any()
                        cond = tbb and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                        if is_cand and not cond: cand = tbb and (lt['Close'] > lt['MA200'])

                    if cond or cand:
                        risk_pct = config["risk_pct"] / 100
                        sh = int((total_capital * risk_pct) / (lt['N'] * exchange_rate)) if lt['N'] > 0 else 1
                        res.append({"tkr": tkr, "p": lt['Close'], "sh": sh, "is_cand": cand, "n": lt['N']})

            pb.empty()

            if not res: st.info("ℹ️ 현재 시장 상황에서 조건에 부합하는 종목이 없습니다.")

            for r in res:
                with st.container(border=True):
                    l_col, r_col = st.columns([3, 1])
                    tag = " [⚠️ 대기]" if r['is_cand'] else " [✅ 포착]"
                    l_col.write(f"### {r['tkr']}{tag}")
                    l_col.write(f"현재가: ${r['p']:.2f} | 권장 매수량: {r['sh']}주 | N(ATR): ${r['n']:.2f}")

                    if not r['is_cand'] and r_col.button("➕ 등록", key=f"reg_{r['tkr']}_{i}"):
                        st.session_state.positions[r['tkr']] = {
                            'Units': 1, 'Highest': r['p'], 
                            'History': [{'price': r['p'], 'shares': r['sh']}],
                            'Strategy': s_name, 'last_pyramid_level': r['p']
                        }
                        save_data(st.session_state.positions)
                        st.rerun()

# ==========================================
# 6. 매니저 탭 (차트 연동 및 V7.5 로직 병합)
# ==========================================
with tabs[3]:
    with st.expander("✍️ 보유 종목 수기 등록", expanded=False):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_t = mc1.text_input("티커").upper()
        m_s = mc2.selectbox("적용 전략", ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"])
        m_p = mc3.number_input("초기 진입단가", value=0.0)
        m_h = mc4.number_input("매수 수량(주)", value=1)

        if st.button("➕ 포지션 직접 등록", use_container_width=True):
            if m_t:
                st.session_state.positions[m_t] = {
                    'Units': 1, 'Highest': m_p,
                    'History': [{'price': m_p, 'shares': m_h}],
                    'Strategy': m_s, 'last_pyramid_level': m_p
                }
                save_data(st.session_state.positions)
                st.rerun()

    st.divider()

    for tkr, pos in list(st.session_state.positions.items()):
        pos['Units'] = len(pos['History'])
        df = analyze_ticker(tkr)
        if df is None: continue

        lt = df.iloc[-1]
        st_n = pos['Strategy']
        config = STRATEGY_CONFIG.get(st_n, {"risk_pct": DEFAULT_RISK_PCT, "max_unit_per_stock": 2})
        max_units = config.get("max_unit_per_stock", 2)
        
        total_s = sum(h['shares'] for h in pos['History'])
        avg_e = sum(h['price'] * h['shares'] for h in pos['History']) / total_s if total_s > 0 else 0.0
        profit = (lt['Close'] / avg_e - 1) if avg_e > 0 else 0.0

        if lt['Close'] > pos['Highest']:
            pos['Highest'] = lt['Close']
            save_data(st.session_state.positions)

        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            s_color = "blue" if "터틀" in st_n else ("green" if "눌림목" in st_n else "red")
            h1.markdown(f"#### {tkr} :{s_color}[({st_n})] - 총 {total_s}주")

            if h2.button("매매 종료", key=f"ex_{tkr}"):
                del st.session_state.positions[tkr]
                save_data(st.session_state.positions)
                st.rerun()

            lvls = [{'val': avg_e, 'name': '평균단가', 'col': 'gray'}]
            add_shares_info = -1
            add_point = 0.0

            # --- 눌림목 전략 ---
            if "눌림목" in st_n:
                tp = avg_e * 1.06
                sl = avg_e * 0.96
                lvls.append({'val': tp, 'name': '6% 익절선', 'col': 'blue'})
                lvls.append({'val': sl, 'name': '4% 손절선', 'col': 'red'})

                if profit >= 0.06: st.success("💰 **[목표 도달]** 6% 수익실현을 권장합니다.")
                elif profit <= -0.04: st.error("🛑 **[위험 감지]** 4% 손절선을 이탈했습니다.")
                else: st.info(f"✅ 순항 중 (현재 수익률: {profit:.2%})")

            # --- BB-낙폭과대 전략 (V7.5 세부 적용) ---
            elif "BB" in st_n or "낙폭" in st_n:
                n_val = lt['N']
                sl_n = avg_e - 1.5 * n_val          
                sl_bb = lt['BB_Lower']               
                effective_sl = max(sl_n, sl_bb)      
                tp1 = lt['MA20']                     
                tp2 = lt['MA20'] + lt['Std']         

                lvls.append({'val': effective_sl, 'name': f'손절(1.5N

