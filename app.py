import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
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
# 1. 설정 및 전략별 리스크 파라미터
# ==========================================
DB_FILE = 'internal_memory.csv'
MAX_TOTAL_UNITS = 10
CACHE_TTL = 300

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
        "risk_pct": 2.0,           
        "max_unit_per_stock": 2,   
    }
}

DEFAULT_RISK_PCT = 2.0

def safe_download(ticker_symbol, period="1y", retries=3):
    for attempt in range(retries):
        try:
            df = yf.download(ticker_symbol, period=period, progress=False, timeout=15)
            if len(df) > 100:
                return df
        except Exception:
            if attempt == retries - 1:
                st.toast(f"⚠️ {ticker_symbol} 데이터 로드 실패", icon="⚠️")
            time.sleep(1.5 ** attempt) 
    return None

# [업데이트] S&P 500 크롤링 대신 3대 테마(고모멘텀, 메가트렌드, 레버리지) 유니버스 하드코딩
TICKERS = [
    'PLTR', 'CRWD', 'MSTR', 'COIN', 'NVDA', 'AVGO', 'CELH',
    'LLY', 'NVO', 'VKTX', 'REGN', 'VRTX',
    'IWM', 'XBI', 'TQQQ', 'SOXL'
]

# ==========================================
# 2. 데이터 입출력 (장부 기록 방식 및 단일 CSV 백업 대응)
# ==========================================
def load_data():
    positions = {}
    global_ledger = []
    
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        for _, row in df.iterrows():
            tkr = row['Ticker']
            raw_history = row['History']
            
            if isinstance(raw_history, str):
                try: history = json.loads(raw_history)
                except: history = []
            elif isinstance(raw_history, list):
                history = raw_history
            else:
                history = []

            if tkr == '_GLOBAL_LEDGER_':
                global_ledger = history
                continue

            for h in history:
                if 'type' not in h:
                    h['type'] = 'Buy'
                # 기존 정수 데이터를 안전하게 실수(float)로 변환
                h['shares'] = float(h.get('shares', 0.0))

            lp_level = row.get('last_pyramid_level')
            if pd.isna(lp_level): 
                lp_level = None

            positions[tkr] = {
                'Units': len([h for h in history if h.get('type') == 'Buy']),
                'Highest': float(row['Highest']),
                'History': history,
                'Strategy': row['Strategy'] if 'Strategy' in df.columns else '🚀 터틀-상승',
                'last_pyramid_level': lp_level
            }
            
    return positions, global_ledger

def save_data(positions, global_ledger):
    rows = []
    for tkr, data in positions.items():
        history = data.get('History', [])
        rows.append({
            'Ticker': tkr,
            'Units': data.get('Units', 1),
            'Highest': data['Highest'],
            'History': json.dumps(history),
            'Strategy': data.get('Strategy', '🚀 터틀-상승'),
            'last_pyramid_level': data.get('last_pyramid_level')
        })
        
    rows.append({
        'Ticker': '_GLOBAL_LEDGER_',
        'Units': 0,
        'Highest': 0.0,
        'History': json.dumps(global_ledger),
        'Strategy': 'SYSTEM',
        'last_pyramid_level': None
    })
    
    pd.DataFrame(rows).to_csv(DB_FILE, index=False)

# ==========================================
# 3. 분석 엔진
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = safe_download("SPY", period="1y") 
        if spy is None: 
            return True, 0, 0, False
            
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
        df = safe_download(ticker) 
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
# 3-1. 보조 분석 툴 (뉴스 및 SEC) (생략 없이 유지)
# ==========================================
FILING_LABELS = {"10-K": "📊 연간보고서", "10-Q": "📋 분기보고서", "8-K": "🔔 중요공시", "4": "👤 내부자거래"}

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
            filings.append({"form": label, "date": recent["filingDate"][i], "url": f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={cik}&action=getcompany"})
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
            if raw:
                dt_kst = datetime(*raw[:6]) + timedelta(hours=9)
                date_str = dt_kst.strftime("%Y-%m-%d %H:%M (KST)")
            else:
                date_str = "시간 미상"
            news_list.append({"title": entry.title, "link": entry.link, "date": date_str, "raw": raw if raw else (0,)*9})
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
            if raw:
                dt = datetime(*raw[:6]) + timedelta(hours=9)
                date_str = dt.strftime('%Y-%m-%d %H:%M')
            else:
                date_str = "시간 미상"
            result.append({"title": e.title, "link": e.link, "date": date_str})
        return result
    except: return []

# ==========================================
# 4. 메인 UI 및 사이드바
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.55 (Fractional)", layout="centered", page_icon="🐢")

if "positions" not in st.session_state or "global_ledger" not in st.session_state:
    pos_data, ledger_data = load_data()
    st.session_state.positions = pos_data
    st.session_state.global_ledger = ledger_data

st.sidebar.header("⚙️ 리스크 및 시스템 설정")
cap_manwon = st.sidebar.number_input("시드머니 (만원)", value=200, step=50)
total_capital = int(cap_manwon * 10000)
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", value=1450, step=10)

st.sidebar.info("💡 **소수점 매매 적용됨:**\n주당 단가에 상관없이 자본금 대비 정확한 % 리스크만큼 매수 수량(소수점 4자리)이 계산됩니다.")

st.sidebar.divider()
up_file = st.sidebar.file_uploader("📂 백업 CSV 업로드")

if up_file and st.sidebar.button("데이터 즉시 복구", type="primary"):
    try:
        df = pd.read_csv(up_file)
        recovered_pos = {}
        recovered_ledger = []
        for _, row in df.iterrows():
            tkr = row['Ticker']
            raw_history = row['History']
            
            if isinstance(raw_history, str):
                try: history = json.loads(raw_history)
                except: history = []
            else:
                history = raw_history if isinstance(raw_history, list) else []
            
            if tkr == '_GLOBAL_LEDGER_':
                recovered_ledger = history
                continue
                
            for h in history:
                if 'type' not in h: h['type'] = 'Buy'
                h['shares'] = float(h.get('shares', 0.0))
            
            lp_level = row.get('last_pyramid_level')
            if pd.isna(lp_level): lp_level = None
                
            recovered_pos[tkr] = {
                'Units': len([h for h in history if h.get('type') == 'Buy']), 
                'Highest': float(row['Highest']), 
                'History': history, 
                'Strategy': row['Strategy'],
                'last_pyramid_level': lp_level
            }
            
        st.session_state.positions = recovered_pos
        st.session_state.global_ledger = recovered_ledger
        save_data(st.session_state.positions, st.session_state.global_ledger)
        st.sidebar.success("✅ 백업 데이터 복구 완료!")
        st.rerun()
    except Exception as e: 
        st.sidebar.error(f"❌ 파일 형식 오류: {e}")

st.title("🐢 Turtle System Pro V7.55")

is_bull, spy_val, ma200_val, is_trending_up = check_market_filter()
trend_label = "📈 MA200 우상향" if is_trending_up else "➡️ MA200 횡보/하향"

if is_bull: 
    st.success(f"🟢 **시장 필터 통과 (대세 상승)** | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {trend_label}")
else: 
    st.error(f"🔴 **시장 필터 경고 (대세 하락)** | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {trend_label}")

c1, c2, c3 = st.columns(3)
t_units = sum(pos['Units'] for pos in st.session_state.positions.values())
c1.metric("총 관리 유닛", f"{t_units}/{MAX_TOTAL_UNITS} U")

avg_risk = sum([STRATEGY_CONFIG.get(p['Strategy'], {}).get("risk_pct", 2.0) * p['Units'] for p in st.session_state.positions.values()])
c2.metric("계좌 전체 위험도", f"{avg_risk:.1f}%")
c3.metric("현재 보유 종목", f"{len(st.session_state.positions)}개")

st.divider()
tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 포지션 매니저", "🇺🇸 정밀 분석", "🌍 마켓 뉴스", "📊 누적 매매 일지"])

# ==========================================
# 5. 스캐너 탭 (소수점 계산 적용)
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
            pb = st.progress(0, text="유니버스 전 종목 분석 중...")
            
            for idx, tkr in enumerate(TICKERS):
                pb.progress((idx + 1) / len(TICKERS))
                df = analyze_ticker(tkr)
                
                if df is not None:
                    lt = df.iloc[-1]
                    pv = df.iloc[-2]
                    cond = False
                    cand = False
                    
                    if "터틀" in s_name:
                        period = config.get("donchian_entry", 20)
                        cond = (lt['Close'] > lt[f'High{period}']) and (lt['Close'] > lt['MA200']) and (50 <= lt['RSI'] < 70)
                        if is_cand and not cond: 
                            cand = (lt['Close'] > lt[f'High{period}'] * 0.98) and (lt['Close'] > lt['MA200'])
                            
                    elif "눌림목" in s_name:
                        t20 = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                        cond = t20 and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                        if is_cand and not cond: 
                            cand = t20 and (lt['Close'] > lt['MA200'])
                            
                    else:  # BB낙폭과대
                        tbb = (df['Low'].iloc[-3:] <= df['BB_Lower'].iloc[-3:]).any()
                        cond = tbb and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                        if is_cand and not cond: 
                            cand = tbb and (lt['Close'] > lt['MA200'])

                    if cond or cand:
                        risk_pct = config["risk_pct"] / 100
                        # [업데이트] int 형변환을 제거하고 round로 소수점 4자리까지 허용
                        sh = round((total_capital * risk_pct) / (lt['N'] * exchange_rate), 4) if lt['N'] > 0 else 0.0
                        res.append({"tkr": tkr, "p": lt['Close'], "sh": sh, "is_cand": cand, "n": lt['N']})
                        
            pb.empty()
            
            if not res: 
                st.info("ℹ️ 현재 시장 상황에서 조건에 부합하는 종목이 없습니다.")

            for r in res:
                with st.container(border=True):
                    l_col, r_col = st.columns([3, 1])
                    tag = " [⚠️ 대기]" if r['is_cand'] else " [✅ 포착]"
                    l_col.write(f"### {r['tkr']}{tag}")
                    # 수량을 소수점 4자리로 출력
                    l_col.write(f"현재가: ${r['p']:.2f} | 권장 매수량: {r['sh']:.4f}주 | N(ATR): ${r['n']:.2f}")

                    if not r['is_cand'] and r_col.button("➕ 등록", key=f"reg_{r['tkr']}_{i}"):
                        st.session_state.positions[r['tkr']] = {
                            'Units': 1, 
                            'Highest': r['p'], 
                            'History': [{'type': 'Buy', 'price': r['p'], 'shares': float(r['sh'])}], 
                            'Strategy': s_name, 
                            'last_pyramid_level': r['p']
                        }
                        
                        st.session_state.global_ledger.append({
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'ticker': r['tkr'],
                            'type': 'Buy',
                            'price': float(r['p']),
                            'shares': float(r['sh']),
                            'realized_profit': 0.0
                        })
                        save_data(st.session_state.positions, st.session_state.global_ledger)
                        st.rerun()

# ==========================================
# 6. 매니저 탭 (소수점 입력 대응)
# ==========================================
with tabs[3]:
    with st.expander("✍️ 보유 종목 수기 등록", expanded=False):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_t = mc1.text_input("티커").upper()
        m_s = mc2.selectbox("적용 전략", ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"])
        m_p = mc3.number_input("초기 진입단가", value=0.0)
        # [업데이트] 매수 수량을 소수점으로 입력받을 수 있도록 수정
        m_h = mc4.number_input("매수 수량(주)", value=1.0, min_value=0.0001, step=0.1, format="%.4f")

        if st.button("➕ 포지션 직접 등록", use_container_width=True):
            if m_t:
                st.session_state.positions[m_t] = {
                    'Units': 1, 
                    'Highest': m_p,
                    'History': [{'type': 'Buy', 'price': m_p, 'shares': float(m_h)}],
                    'Strategy': m_s, 
                    'last_pyramid_level': m_p
                }
                
                st.session_state.global_ledger.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'ticker': m_t,
                    'type': 'Buy',
                    'price': float(m_p),
                    'shares': float(m_h),
                    'realized_profit': 0.0
                })
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()

    st.divider()

    for tkr, pos in list(st.session_state.positions.items()):
        df = analyze_ticker(tkr)
        if df is None: continue

        lt = df.iloc[-1]
        st_n = pos['Strategy']
        config = STRATEGY_CONFIG.get(st_n, {"risk_pct": DEFAULT_RISK_PCT, "max_unit_per_stock": 2})
        max_units = config.get("max_unit_per_stock", 2)
        
        total_s = 0.0
        avg_e = 0.0
        active_lots = []
        
        for h in pos['History']:
            h_type = h.get('type', 'Buy')
            # 안정적인 계산을 위해 float 보장
            h_shares = float(h['shares']) 
            
            if h_type == 'Buy':
                new_total = total_s + h_shares
                avg_e = (avg_e * total_s + h['price'] * h_shares) / new_total if new_total > 0 else 0
                total_s = new_total
                active_lots.append({'price': h['price'], 'shares': h_shares})
            elif h_type == 'Sell':
                total_s -= h_shares
                if total_s <= 0.0001:  # 소수점 오차 방지
                    total_s = 0.0
                    avg_e = 0.0
                rem_sell = h_shares
                while rem_sell > 0.0001 and active_lots:
                    if active_lots[-1]['shares'] > rem_sell:
                        active_lots[-1]['shares'] -= rem_sell
                        rem_sell = 0
                    else:
                        rem_sell -= active_lots[-1]['shares']
                        active_lots.pop()
        
        pos['Units'] = len(active_lots)
        if active_lots:
            pos['last_pyramid_level'] = active_lots[-1]['price']
        else:
            pos['last_pyramid_level'] = avg_e

        profit = (lt['Close'] / avg_e - 1) if avg_e > 0 else 0.0

        if lt['Close'] > pos['Highest']: 
            pos['Highest'] = lt['Close']
            save_data(st.session_state.positions, st.session_state.global_ledger)

        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            s_color = "blue" if "터틀" in st_n else ("green" if "눌림목" in st_n else "red")
            h1.markdown(f"#### {tkr} :{s_color}[({st_n})] - 잔여 {total_s:.4f}주")
            
            if h2.button("전량 매매 종료", key=f"ex_{tkr}"):
                realized_profit = (lt['Close'] - avg_e) * total_s
                st.session_state.global_ledger.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'ticker': tkr,
                    'type': 'Sell (All)',
                    'price': float(lt['Close']),
                    'shares': total_s,
                    'realized_profit': float(realized_profit)
                })
                del st.session_state.positions[tkr]
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()

            lvls = [{'val': avg_e, 'name': '전체 평단가', 'col': 'gray'}]
            add_shares_info = -1.0
            add_point = 0.0
            bb_add_point = 0.0
            strong_oversold = False
            tp1 = 0.0
            effective_sl = 0.0

            if "터틀" in st_n:
                n = lt['N']
                trail_stop = lt[f'Low{config.get("trailing_days", 10)}']
                last_pyramid = pos.get('last_pyramid_level')
                
                base_price = last_pyramid if last_pyramid else avg_e
                dynamic_stop_2n = base_price - config.get("initial_stop_n", 2.0) * n
                add_point = base_price + config.get("pyramid_n", 0.5) * n
                
                lvls.append({'val': dynamic_stop_2n, 'name': f'{pos["Units"]}차 통합손절(2N)', 'col': 'red'})
                lvls.append({'val': trail_stop, 'name': f'{config.get("trailing_days", 10)}일신저가(Trailing)', 'col': 'green'})
                lvls.append({'val': add_point, 'name': f'{pos["Units"]+1}차 불타기타점', 'col': 'orange'})

                if lt['Close'] < trail_stop:
                    st.error(f"🛑 **[터틀 청산]** {config.get('trailing_days', 10)}일 신저가 이탈 → 전량 매도 권장")
                elif lt['Close'] < dynamic_stop_2n:
                    st.error(f"🛑 **[위험]** {pos['Units']}차 통합 손절선(${dynamic_stop_2n:.2f}) 이탈")
                else:
                    st.info(f"✅ {pos['Units']}차 추세 탑승 중 (수익률: {profit:.2%} | 🛡️ 현재 손절선: ${dynamic_stop_2n:.2f})")

                risk_pct = config["risk_pct"] / 100
                risk_s = round((total_capital * risk_pct) / (n * exchange_rate), 4) if n > 0 else 0.0
                cash_s = round((total_capital / MAX_TOTAL_UNITS) / (lt['Close'] * exchange_rate), 4)
                add_shares_info = max(0.0001, min(risk_s, cash_s))

            elif "BB" in st_n or "낙폭" in st_n:
                n_val = lt['N']
                tp1 = lt['MA20']
                tp2 = lt['MA20'] + lt['Std']
                sl_n = avg_e - 1.5 * n_val          
                sl_bb = lt['BB_Lower']               
                effective_sl = max(sl_n, sl_bb)      
                bb_add_point = tp1 - 0.5 * lt['Std']
                strong_oversold = lt['RSI'] < 33

                lvls.append({'val': effective_sl, 'name': '손절(1.5N/BB)', 'col': 'red'})
                lvls.append({'val': bb_add_point, 'name': 'MA20-0.5σ(타점)', 'col': 'gray'})
                lvls.append({'val': tp1, 'name': 'MA20(1차익절)', 'col': 'blue'})
                lvls.append({'val': tp2, 'name': 'MA20+1σ(2차익절)', 'col': 'darkblue'})

                if lt['Close'] >= tp2:
                    st.success("💰 **[2차 목표 도달]** MA20+1σ 도달 → 전량 익절 검토")
                elif lt['Close'] >= tp1:
                    st.success("📈 **[1차 목표 도달]** MA20 복귀 → 부분 익절 + Stop to Breakeven 권장")
                elif lt['Close'] < effective_sl:
                    st.error(f"🛑 **[손절 조건]** 1.5N 또는 BB Lower 이탈 → 즉시 손절 권장 (${effective_sl:.2f})")
                else:
                    st.info(f"✅ 바닥 반등 중 (현재 수익률: {profit:.2%} | 🛡️ 손절선: ${effective_sl:.2f})")

                risk_pct = config["risk_pct"] / 100
                risk_s = round((total_capital * risk_pct) / (n_val * exchange_rate), 4) if n_val > 0 else 0.0
                cash_s = round((total_capital / MAX_TOTAL_UNITS) / (lt['Close'] * exchange_rate), 4)
                add_shares_info = max(0.0001, min(risk_s, cash_s))

            else: 
                tp = avg_e * 1.06
                sl = avg_e * 0.96
                lvls.append({'val': tp, 'name': '6% 익절선', 'col': 'blue'})
                lvls.append({'val': sl, 'name': '4% 손절선', 'col': 'red'})

                if profit >= 0.06: 
                    st.success("💰 **[목표 도달]** 6% 수익실현을 권장합니다.")
                elif profit <= -0.04: 
                    st.error("🛑 **[위험 감지]** 4% 손절선을 이탈했습니다.")
                else: 
                    st.info(f"✅ 순항 중 (현재 수익률: {profit:.2%})")

            lvls.append({'val': lt['Close'], 'name': '현재가', 'col': 'purple'})

            c_df = df.reset_index()[['Date', 'Close']].tail(60)
            base = alt.Chart(c_df).encode(x=alt.X('Date:T', title=None))
            line = base.mark_line(color='#1f77b4').encode(y=alt.Y('Close:Q', scale=alt.Scale(zero=False)))
            
            rules = []
            for l in lvls:
                if not pd.isna(l['val']):
                    rules.append(
                        alt.Chart(pd.DataFrame({'y': [l['val']]}))
                        .mark_rule(strokeDash=[5, 5], color=l['col'])
                        .encode(y='y:Q')
                    )
                    rules.append(
                        alt.Chart(pd.DataFrame({'Date': [c_df['Date'].max()], 'y': [l['val']], 't': [f"{l['name']}: ${l['val']:.2f}"]}))
                        .mark_text(align='left', dx=5, dy=-4, color=l['col'], fontWeight='bold')
                        .encode(x='Date:T', y='y:Q', text='t:N')
                    )
            
            st.altair_chart(alt.layer(line, *rules).properties(height=320), use_container_width=True)

            if "터틀" in st_n and add_shares_info >= 0.0001:
                if pos['Units'] < max_units:
                    if not pd.isna(add_point):
                        if lt['Close'] >= add_point: 
                            st.warning(f"🔔 **[추가 매수 알람]** 불타기 타점(${add_point:.2f}) 돌파! **{add_shares_info:.4f}주** 추가 진입 검토")
                        else: 
                            st.info(f"💡 **불타기 대기:** ${add_point:.2f} 도달 시 **{add_shares_info:.4f}주** 추가 매수 권장 (현재 {pos['Units']}/{max_units}U)")
                    else:
                        st.error("⚠️ 불타기 가격을 계산할 수 없습니다.")
                else: 
                    st.write(f"✅ **유닛 풀(Full) 탑승:** 최대 허용 유닛({max_units}U) 보유 중")
            
            elif ("BB" in st_n or "낙폭" in st_n) and add_shares_info >= 0.0001:
                if pos['Units'] < max_units:
                    if lt['Close'] >= tp1 and lt['Close'] <= bb_add_point and 35 <= lt['RSI'] <= 45: 
                        st.warning(f"📌 **[BB 2차 진입 기회]** MA20 -0.5σ 재진입! **{add_shares_info:.4f}주** 추가 매수 검토 (현재 {pos['Units']}/{max_units}U)")
                    elif lt['Close'] <= lt['BB_Lower'] * 1.02 and strong_oversold and lt['Close'] > effective_sl: 
                        st.warning(f"⚠️ **[강한 Oversold]** BB 하단 부근 + RSI {lt['RSI']:.1f} → **{add_shares_info:.4f}주** 저가 평균화 기회 (현재 {pos['Units']}/{max_units}U)")
                    else:
                        st.info(f"💡 **대기 중:** 안전한 추가 매수 타점을 기다립니다. (현재 {pos['Units']}/{max_units}U)")
                else: 
                    st.write(f"✅ **유닛 풀(Full) 탑승:** 최대 허용 유닛({max_units}U) 보유 중")

            # [업데이트] 부분 매수/매도 시 소수점 입력창 지원
            c_p, c_s = st.columns(2)
            u_p = c_p.number_input("거래 단가 ($)", value=float(lt['Close']), key=f"up_{tkr}")
            u_s = c_s.number_input("거래 수량 (주)", value=1.0, min_value=0.0001, step=0.1, format="%.4f", key=f"us_{tkr}")
            
            b_a, b_s, b_d = st.columns(3)
            
            if b_a.button("➕ 추가 매수", key=f"ba_{tkr}", use_container_width=True):
                pos['History'].append({'type': 'Buy', 'price': float(u_p), 'shares': float(u_s)})
                st.session_state.global_ledger.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'ticker': tkr,
                    'type': 'Buy',
                    'price': float(u_p),
                    'shares': float(u_s),
                    'realized_profit': 0.0
                })
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()

            if b_s.button("➖ 부분 매도", key=f"bs_{tkr}", use_container_width=True):
                if u_s >= total_s:
                    realized_profit = (u_p - avg_e) * total_s
                    st.session_state.global_ledger.append({
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'ticker': tkr,
                        'type': 'Sell (All)',
                        'price': float(u_p),
                        'shares': total_s,
                        'realized_profit': float(realized_profit)
                    })
                    del st.session_state.positions[tkr]
                else:
                    realized_profit = (u_p - avg_e) * u_s
                    pos['History'].append({'type': 'Sell', 'price': float(u_p), 'shares': float(u_s)})
                    st.session_state.global_ledger.append({
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'ticker': tkr,
                        'type': 'Sell (Partial)',
                        'price': float(u_p),
                        'shares': float(u_s),
                        'realized_profit': float(realized_profit)
                    })
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()
                
            if b_d.button("🔙 최근 거래 취소", key=f"bd_{tkr}", use_container_width=True) and len(pos['History']) > 1:
                for idx in range(len(st.session_state.global_ledger)-1, -1, -1):
                    if st.session_state.global_ledger[idx]['ticker'] == tkr:
                        st.session_state.global_ledger.pop(idx)
                        break
                pos['History'].pop()
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()
                
            df_hist = pd.DataFrame(pos['History'])
            if 'type' not in df_hist.columns:
                df_hist['type'] = 'Buy'
            
            display_df = pd.DataFrame({
                '구분': df_hist['type'].map({'Buy': '🔴 매수', 'Sell': '🔵 매도'}),
                '단가': df_hist['price'].apply(lambda x: f"${x:.2f}"),
                # 수량 포맷 변경
                '수량': df_hist['shares'].apply(lambda x: f"{float(x):.4f}주") 
            })
            st.table(display_df)

    if st.session_state.positions or st.session_state.global_ledger:
        rows_to_export = []
        for k, v in st.session_state.positions.items():
            rows_to_export.append({
                'Ticker': k,
                'Units': v.get('Units', 1),
                'Highest': v['Highest'],
                'History': json.dumps(v['History']) if isinstance(v['History'], list) else v['History'],
                'Strategy': v['Strategy'],
                'last_pyramid_level': v.get('last_pyramid_level')
            })
            
        rows_to_export.append({
            'Ticker': '_GLOBAL_LEDGER_',
            'Units': 0,
            'Highest': 0.0,
            'History': json.dumps(st.session_state.global_ledger),
            'Strategy': 'SYSTEM',
            'last_pyramid_level': None
        })
        
        csv_data = pd.DataFrame(rows_to_export).to_csv(index=False).encode('utf-8-sig')

        st.download_button(
            "💾 포지션 및 누적 장부 데이터 통합 백업 (CSV)",
            csv_data,
            f"Turtle_Positions_Backup_{datetime.now().strftime('%y%m%d')}.csv",
            "text/csv",
            use_container_width=True
        )

# ==========================================
# 7. 분석 / 뉴스 탭
# ==========================================
with tabs[4]:
    st.subheader("🇺🇸 미국 주식 정밀 분석")
    t_in = st.text_input("분석을 원하는 종목의 티커를 입력하세요").upper()

    if t_in and st.button("분석 실행", use_container_width=True):
        d = analyze_ticker(t_in)
        if d is not None:
            st.info(f"**[{t_in}]** 실시간 종가: **${d['Close'].iloc[-1]:.2f}** | RSI(14): **{d['RSI'].iloc[-1]:.1f}**")

            with st.expander("📋 SEC 실시간 기업 공시 (KST 기준 변환)", expanded=True):
                fils = get_sec_filings(t_in)
                if fils:
                    for f in fils:
                        c_a, c_b, c_c = st.columns([3, 2, 2])
                        c_a.write(f"**{f['form']}**")
                        c_b.caption(f['date'])
                        c_c.markdown(f"[원문 링크]({f['url']})")
                else:
                    st.write("해당 기업의 최근 공시 데이터를 찾을 수 없습니다.")

            with st.expander("📰 관련 구글 뉴스 (최신순)", expanded=True):
                s_news = get_stock_news(t_in)
                if s_news:
                    for n in s_news:
                        st.markdown(f"- [{n['title']}]({n['link']}) `[{n['date']}]`")
                else:
                    st.write("관련 뉴스를 검색하지 못했습니다.")

with tabs[5]:
    st.subheader("🌍 글로벌 경제 핵심 뉴스 (KST)")

    if st.button("🔄 최신 뉴스 불러오기", use_container_width=True):
        get_global_news.clear()
        st.rerun()

    global_news = get_global_news()
    if global_news:
        for item in global_news:
            st.markdown(f"📍 [{item['title']}]({item['link']}) `[{item['date']}]`")
    else:
        st.info("뉴스를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")

# ==========================================
# 8. 누적 매매 일지 탭
# ==========================================
with tabs[6]:
    st.subheader("📊 누적 매매 일지 및 계좌 수익률")
    
    total_profit_usd = sum(item.get('realized_profit', 0.0) for item in st.session_state.global_ledger)
    total_profit_krw = total_profit_usd * exchange_rate
    total_return_pct = (total_profit_krw / total_capital) * 100 if total_capital > 0 else 0.0
    
    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("초기 시드머니", f"₩{total_capital:,.0f}")
    c_m2.metric("누적 실현 수익금", f"₩{total_profit_krw:,.0f} (${total_profit_usd:,.2f})", f"{total_return_pct:.2f}%")
    c_m3.metric("총 누적 거래 건수", f"{len(st.session_state.global_ledger)}건")
    
    st.divider()
    
    if st.session_state.global_ledger:
        df_ledger = pd.DataFrame(st.session_state.global_ledger)
        df_ledger.columns = ['일시', '티커', '구분', '단가($)', '수량(주)', '실현손익($)']
        
        df_ledger['단가($)'] = df_ledger['단가($)'].apply(lambda x: f"${float(x):.2f}")
        # 장부에도 소수점 수량 표기
        df_ledger['수량(주)'] = df_ledger['수량(주)'].apply(lambda x: f"{float(x):.4f}")
        df_ledger['실현손익($)'] = df_ledger['실현손익($)'].apply(lambda x: f"${float(x):.2f}" if x != 0 else "-")
        
        df_ledger = df_ledger.iloc[::-1].reset_index(drop=True)
        st.dataframe(df_ledger, use_container_width=True)
    else:
        st.info("아직 시스템에 기록된 누적 매매 내역이 없습니다.")
        
    st.markdown("<br><br>", unsafe_allow_html=True)
    with st.expander("⚠️ 관리자 도구"):
        if st.button("🗑️ 장부 전체 초기화 (복구 불가)", type="secondary", use_container_width=True):
            st.session_state.global_ledger = []
            save_data(st.session_state.positions, st.session_state.global_ledger)
            st.rerun()

