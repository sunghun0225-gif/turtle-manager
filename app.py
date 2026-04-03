import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import os, time, requests, json, feedparser, urllib.parse
import altair as alt
from datetime import datetime, timedelta
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 설정 및 리스크 파라미터
# ==========================================
DB_FILE = 'internal_memory.csv'
MAX_TOTAL_UNITS = 10

STRATEGY_CONFIG = {
    "🚀 터틀-상승": {"risk_pct": 1.5, "max_unit_per_stock": 4, "donchian_entry": 20, "trailing_days": 10, "pyramid_n": 0.5, "initial_stop_n": 2.0},
    "📈 20일-눌림목": {"risk_pct": 2.0, "max_unit_per_stock": 2},
    "📉 BB-낙폭과대": {"risk_pct": 2.0, "max_unit_per_stock": 2}
}

def safe_download(ticker_symbol, period="1y", retries=3):
    for attempt in range(retries):
        try:
            df = yf.download(ticker_symbol, period=period, progress=False, timeout=15)
            if len(df) > 100: return df
        except:
            if attempt == retries - 1: st.toast(f"⚠️ {ticker_symbol} 데이터 로드 실패", icon="⚠️")
            time.sleep(1.5 ** attempt) 
    return None

# ==========================================
# 2. 강력한 '핵심 600 유니버스' 구축 (방탄 스크래핑)
# ==========================================
@st.cache_data(ttl=86400)
def get_sp500_tickers():
    try:
        html = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'}).text
        # 표 순서가 바뀌어도 자동으로 Symbol 열을 찾아냄
        for tb in pd.read_html(html):
            if 'Symbol' in tb.columns:
                return [t.replace('.', '-') for t in tb['Symbol'].tolist()]
    except: pass
    return ['SPY']

@st.cache_data(ttl=86400)
def get_nasdaq100_tickers():
    try:
        html = requests.get('https://en.wikipedia.org/wiki/Nasdaq-100', headers={'User-Agent': 'Mozilla/5.0'}).text
        # 표 순서가 바뀌어도 자동으로 Ticker 열을 찾아냄
        for tb in pd.read_html(html):
            if 'Ticker' in tb.columns:
                return [t.replace('.', '-') for t in tb['Ticker'].tolist()]
    except: pass
    return ['QQQ']

# 러셀 2000 및 XBI (바이오) 핵심 고변동성/거래대금 상위 종목 수동 편입
CORE_RUSSELL_XBI = [
    'NBIX', 'EXAS', 'SRPT', 'UTHR', 'CRSP', 'EDIT', 'NTLA', 'BEAM', 'INCY', 'BMRN', 'ALNY', 'SGEN', 'MCRB', 'PRTA',
    'COIN', 'MSTR', 'HOOD', 'PLTR', 'CELH', 'DKNG', 'CVNA', 'RBLX', 'AFRM', 'SOFI', 'SYM', 'IOT', 'FOUR', 'DUOL', 'CART'
]

# S&P500 + 나스닥100 + 핵심 러셀/바이오 합친 후 중복(set) 제거
raw_tickers = get_sp500_tickers() + get_nasdaq100_tickers() + CORE_RUSSELL_XBI
TICKERS = sorted(list(set(raw_tickers)))

# ==========================================
# 3. 데이터 입출력 및 기록 헬퍼 함수
# ==========================================
def load_data():
    positions, global_ledger = {}, []
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        for _, row in df.iterrows():
            tkr = row['Ticker']
            history = json.loads(row['History']) if isinstance(row['History'], str) else (row['History'] if isinstance(row['History'], list) else [])
            
            if tkr == '_GLOBAL_LEDGER_':
                global_ledger = history
                continue

            for h in history:
                h['type'] = h.get('type', 'Buy')
                h['shares'] = float(h.get('shares', 0.0))

            positions[tkr] = {
                'Units': len([h for h in history if h.get('type') == 'Buy']),
                'Highest': float(row['Highest']), 'History': history,
                'Strategy': row.get('Strategy', '🚀 터틀-상승'),
                'last_pyramid_level': row.get('last_pyramid_level') if pd.notna(row.get('last_pyramid_level')) else None
            }
    return positions, global_ledger

def save_data(positions, global_ledger):
    rows = [{'Ticker': k, 'Units': v.get('Units', 1), 'Highest': v['Highest'], 'History': json.dumps(v.get('History', [])), 'Strategy': v.get('Strategy', '🚀 터틀-상승'), 'last_pyramid_level': v.get('last_pyramid_level')} for k, v in positions.items()]
    rows.append({'Ticker': '_GLOBAL_LEDGER_', 'Units': 0, 'Highest': 0.0, 'History': json.dumps(global_ledger), 'Strategy': 'SYSTEM', 'last_pyramid_level': None})
    pd.DataFrame(rows).to_csv(DB_FILE, index=False)

def log_trade(tkr, trade_type, price, shares, profit=0.0):
    st.session_state.global_ledger.append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ticker': tkr, 'type': trade_type, 'price': float(price), 'shares': float(shares), 'realized_profit': float(profit)
    })
    save_data(st.session_state.positions, st.session_state.global_ledger)

# ==========================================
# 4. 분석 엔진 및 보조 툴
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = safe_download("SPY", period="1y") 
        if spy is None: return True, 0, 0, False
        if isinstance(spy.columns, pd.MultiIndex): spy.columns = spy.columns.get_level_values(0)
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy, ma200_now = spy['Close'].iloc[-1], spy['MA200'].iloc[-1]
        is_trending_up = all(spy['MA200'].tail(6).iloc[i] > spy['MA200'].tail(6).iloc[i-1] for i in range(1, 6))
        return (curr_spy > ma200_now) and is_trending_up, curr_spy, ma200_now, is_trending_up
    except: return True, 0, 0, False

@st.cache_data(ttl=1800)
def analyze_ticker(ticker):
    df = safe_download(ticker) 
    if df is None or len(df) < 200: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(lambda x: max(x['High']-x['Low'], abs(x['High']-x['prev_close']) if pd.notna(x['prev_close']) else 0, abs(x['Low']-x['prev_close']) if pd.notna(x['prev_close']) else 0), axis=1)
    df['N'] = df['TR'].rolling(20).mean()
    df['High20'], df['High55'] = df['High'].rolling(20).max().shift(1), df['High'].rolling(55).max().shift(1)
    df['Low10'], df['Low20'] = df['Low'].rolling(10).min().shift(1), df['Low'].rolling(20).min().shift(1)
    df['MA200'], df['MA20'], df['MA5'], df['Std'] = df['Close'].rolling(200).mean(), df['Close'].rolling(20).mean(), df['Close'].rolling(5).mean(), df['Close'].rolling(20).std()
    df['BB_Lower'], df['BB_Upper'] = df['MA20'] - (df['Std'] * 2), df['MA20'] + (df['Std'] * 2)

    delta = df['Close'].diff()
    avg_gain, avg_loss = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean(), -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / (avg_loss + 1e-9))))
    return df.drop(columns=['prev_close'])

@st.cache_data(ttl=86400)
def get_sec_filings(ticker: str):
    try:
        cik = next((str(v["cik_str"]).zfill(10) for v in requests.get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "TurtlePro/1.0"}, verify=False).json().values() if v["ticker"].upper() == ticker.upper()), None)
        if not cik: return []
        recent = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers={"User-Agent": "TurtlePro/1.0"}, verify=False).json().get("filings", {}).get("recent", {})
        return [{"form": {"10-K": "📊 연간", "10-Q": "📋 분기", "8-K": "🔔 수시", "4": "👤 내부자"}.get(recent["form"][i], f"📄 {recent['form'][i]}"), "date": recent["filingDate"][i], "url": f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={cik}&action=getcompany"} for i in range(min(10, len(recent.get("form", []))))]
    except: return []

def get_stock_news(query_name):
    try:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={urllib.parse.quote(f'{query_name} stock')}+when:90d&hl=en-US&gl=US&ceid=US:en")
        return sorted([{"title": e.title, "link": e.link, "date": (datetime(*e.published_parsed[:6]) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M (KST)") if e.get("published_parsed") else "미상", "raw": e.get("published_parsed", (0,)*9)} for e in feed.entries[:15]], key=lambda x: x['raw'], reverse=True)[:8]
    except: return []

@st.cache_data(ttl=1800)
def get_global_news():
    try:
        return [{"title": e.title, "link": e.link, "date": (datetime(*e.published_parsed[:6]) + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M') if e.get("published_parsed") else "미상"} for e in feedparser.parse("https://news.google.com/rss/search?q=global+economy+market+when:24h&hl=en-US&gl=US&ceid=US:en").entries[:10]]
    except: return []

# ==========================================
# 5. 메인 UI 및 사이드바
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.55 (Final Secure)", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions, st.session_state.global_ledger = load_data()

st.sidebar.header("⚙️ 리스크 및 시스템 설정")
total_capital = int(st.sidebar.number_input("시드머니 (만원)", value=200, step=50) * 10000)
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", value=1450, step=10)
st.sidebar.info(f"💡 **현재 스캔 유니버스:**\nS&P 500, 나스닥 100, 러셀/XBI 핵심 주도주 등 총 **{len(TICKERS)}개** 종목 자동 스캔 중")

if up_file := st.sidebar.file_uploader("📂 백업 CSV 업로드"):
    if st.sidebar.button("데이터 즉시 복구", type="primary"):
        try:
            df = pd.read_csv(up_file)
            st.session_state.positions = {row['Ticker']: {'Units': len([h for h in (json.loads(row['History']) if isinstance(row['History'], str) else []) if h.get('type', 'Buy') == 'Buy']), 'Highest': float(row['Highest']), 'History': json.loads(row['History']) if isinstance(row['History'], str) else [], 'Strategy': row['Strategy'], 'last_pyramid_level': row.get('last_pyramid_level') if pd.notna(row.get('last_pyramid_level')) else None} for _, row in df[df['Ticker'] != '_GLOBAL_LEDGER_'].iterrows()}
            st.session_state.global_ledger = next((json.loads(row['History']) for _, row in df[df['Ticker'] == '_GLOBAL_LEDGER_'].iterrows()), [])
            save_data(st.session_state.positions, st.session_state.global_ledger)
            st.rerun()
        except Exception as e: st.sidebar.error(f"❌ 오류: {e}")

st.title("🐢 Turtle System Pro V7.55")
is_bull, spy_val, ma200_val, is_trending = check_market_filter()
if is_bull:
    st.success(f"🟢 시장 통과 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {'📈 상승 추세' if is_trending else '➡️ 횡보'}")
else:
    st.error(f"🔴 시장 경고 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {'📈 상승 추세' if is_trending else '➡️ 횡보/하락'}")

c1, c2, c3 = st.columns(3)
c1.metric("총 관리 유닛", f"{sum(p['Units'] for p in st.session_state.positions.values())}/{MAX_TOTAL_UNITS} U")
c2.metric("계좌 전체 위험도", f"{sum([STRATEGY_CONFIG.get(p['Strategy'], {}).get('risk_pct', 2.0) * p['Units'] for p in st.session_state.positions.values()]):.1f}%")
c3.metric("보유 종목", f"{len(st.session_state.positions)}개")

tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 매니저", "🇺🇸 분석", "🌍 뉴스", "📊 일지"])

# ==========================================
# 6. 스캐너 탭
# ==========================================
for i, s_name in enumerate(["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"]):
    with tabs[i]:
        config = STRATEGY_CONFIG.get(s_name, {"risk_pct": 2.0})
        col_btn, col_chk = st.columns([3, 2])
        if col_btn.button(f"🔎 {s_name} 스캔 (약 {len(TICKERS)}개)", key=f"run_{i}", use_container_width=True):
            res, is_cand = [], col_chk.checkbox("⚠️ 대기 종목 포함", key=f"cand_{i}")
            pb = st.progress(0, text="대규모 유니버스 분석 중... (수 분 소요)")
            
            for idx, tkr in enumerate(TICKERS):
                pb.progress((idx + 1) / len(TICKERS))
                if (df := analyze_ticker(tkr)) is not None:
                    lt, pv = df.iloc[-1], df.iloc[-2]
                    cond, cand = False, False
                    
                    if "터틀" in s_name:
                        cond = (lt['Close'] > lt[f'High{config.get("donchian_entry", 20)}']) and (lt['Close'] > lt['MA200'])
                        cand = not cond and is_cand and (lt['Close'] > lt[f'High{config.get("donchian_entry", 20)}'] * 0.98) and (lt['Close'] > lt['MA200'])
                    else:
                        is_pullback = "눌림목" in s_name
                        if is_pullback:
                            signal = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                            cond = signal and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                            cand = not cond and is_cand and signal and (lt['Close'] > lt['MA200'])
                        else:
                            signal = (df['Low'].iloc[-3:] <= df['BB_Lower'].iloc[-3:]).any()
                            cond = signal and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5'])
                            cand = not cond and is_cand and signal

                    if cond or cand:
                        risk_sh = (total_capital * (config["risk_pct"] / 100)) / (lt['N'] * exchange_rate) if lt['N'] > 0 else 0
                        cash_sh = (total_capital / MAX_TOTAL_UNITS) / (lt['Close'] * exchange_rate)
                        final_sh = round(min(risk_sh, cash_sh), 4)
                        if final_sh >= 0.0001: res.append({"tkr": tkr, "p": lt['Close'], "sh": final_sh, "is_cand": cand, "n": lt['N']})
            pb.empty()
            if not res: st.info("ℹ️ 포착된 종목이 없습니다.")

            for r in res:
                with st.container(border=True):
                    l_col, r_col = st.columns([3, 1])
                    l_col.write(f"### {r['tkr']}{' [⚠️ 대기]' if r['is_cand'] else ' [✅ 포착]'}\n현재가: ${r['p']:.2f} | 수량: {r['sh']:.4f}주 | N: ${r['n']:.2f}")
                    if not r['is_cand'] and r_col.button("➕ 등록", key=f"reg_{r['tkr']}_{i}"):
                        st.session_state.positions[r['tkr']] = {'Units': 1, 'Highest': r['p'], 'History': [{'type': 'Buy', 'price': r['p'], 'shares': r['sh']}], 'Strategy': s_name, 'last_pyramid_level': r['p']}
                        log_trade(r['tkr'], 'Buy', r['p'], r['sh'])
                        st.rerun()

# ==========================================
# 7. 매니저 탭
# ==========================================
with tabs[3]:
    with st.expander("✍️ 수기 등록", expanded=False):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_t = mc1.text_input("티커").upper()
        m_s = mc2.selectbox("전략", ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"])
        m_p, m_h = mc3.number_input("진입가", value=0.0), mc4.number_input("수량", value=1.0, min_value=0.0001, format="%.4f")
        if st.button("➕ 등록", use_container_width=True) and m_t:
            st.session_state.positions[m_t] = {'Units': 1, 'Highest': m_p, 'History': [{'type': 'Buy', 'price': m_p, 'shares': m_h}], 'Strategy': m_s, 'last_pyramid_level': m_p}
            log_trade(m_t, 'Buy', m_p, m_h)
            st.rerun()

    needs_save = False

    for tkr, pos in list(st.session_state.positions.items()):
        if (df := analyze_ticker(tkr)) is None: continue
        lt, st_n, config = df.iloc[-1], pos['Strategy'], STRATEGY_CONFIG.get(pos['Strategy'], {"risk_pct": 2.0, "max_unit_per_stock": 2})
        total_s, avg_e, active_lots = 0.0, 0.0, []
        
        for h in pos['History']:
            sh = float(h['shares'])
            if h.get('type', 'Buy') == 'Buy':
                avg_e = (avg_e * total_s + h['price'] * sh) / (total_s + sh) if (total_s + sh) > 0 else 0
                total_s += sh
                active_lots.append({'price': h['price'], 'shares': sh})
            else:
                total_s = max(0.0, total_s - sh)
                rem_sell = sh
                while rem_sell > 0.0001 and active_lots:
                    if active_lots[-1]['shares'] > rem_sell: active_lots[-1]['shares'] -= rem_sell; rem_sell = 0
                    else: rem_sell -= active_lots[-1]['shares']; active_lots.pop()
        
        if total_s <= 0.0001:
            del st.session_state.positions[tkr]
            needs_save = True
            continue
            
        pos['Units'], pos['last_pyramid_level'] = len(active_lots), active_lots[-1]['price'] if active_lots else avg_e
        profit = (lt['Close'] / avg_e - 1) if avg_e > 0 else 0.0
        
        if lt['Close'] > pos['Highest']: 
            pos['Highest'] = lt['Close']
            needs_save = True

        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            h1.markdown(f"#### {tkr} :{'blue' if '터틀' in st_n else ('green' if '눌림목' in st_n else 'red')}[({st_n})] - {total_s:.4f}주")
            
            if h2.button("전량 매도", key=f"ex_{tkr}"):
                del st.session_state.positions[tkr]
                log_trade(tkr, 'Sell (All)', lt['Close'], total_s, (lt['Close'] - avg_e) * total_s)
                st.rerun()

            lvls, add_shares, add_pt, bb_add, eff_sl = [{'val': avg_e, 'name': '평단가', 'col': 'gray'}], -1.0, 0.0, 0.0, 0.0

            if "터틀" in st_n:
                base_p = pos.get('last_pyramid_level', avg_e)
                dyn_stop, add_pt, trail = base_p - (2.0 * lt['N']), base_p + (0.5 * lt['N']), lt[f'Low{config.get("trailing_days", 10)}']
                lvls.extend([{'val': dyn_stop, 'name': f'{pos["Units"]}차 통합손절', 'col': 'red'}, {'val': trail, 'name': 'Trailing', 'col': 'green'}, {'val': add_pt, 'name': '불타기', 'col': 'orange'}])
                
                if lt['Close'] < trail: st.error("🛑 Trailing 이탈")
                elif lt['Close'] < dyn_stop: st.error(f"🛑 손절선(${dyn_stop:.2f}) 이탈")
                else: st.info(f"✅ {pos['Units']}차 탑승 (수익률: {profit:.2%} | 손절선: ${dyn_stop:.2f})")
                add_shares = max(0.0001, min((total_capital * (config["risk_pct"]/100)) / (lt['N']*exchange_rate) if lt['N']>0 else 0, (total_capital/MAX_TOTAL_UNITS)/(lt['Close']*exchange_rate)))

            elif "BB" in st_n or "낙폭" in st_n:
                eff_sl, bb_add, tp1, tp2 = max(avg_e - 1.5 * lt['N'], lt['BB_Lower']), lt['MA20'] - 0.5 * lt['Std'], lt['MA20'], lt['MA20'] + lt['Std']
                lvls.extend([{'val': eff_sl, 'name': '손절', 'col': 'red'}, {'val': bb_add, 'name': '타점', 'col': 'gray'}, {'val': tp1, 'name': '1차', 'col': 'blue'}, {'val': tp2, 'name': '2차', 'col': 'darkblue'}])
                
                if lt['Close'] >= tp2: st.success("💰 2차 익절 도달")
                elif lt['Close'] >= tp1: st.success("📈 1차 익절 도달")
                elif lt['Close'] < eff_sl: st.error(f"🛑 손절 권장 (${eff_sl:.2f})")
                else: st.info(f"✅ 반등 중 (수익률: {profit:.2%} | 손절: ${eff_sl:.2f})")
                add_shares = max(0.0001, min((total_capital * (config["risk_pct"]/100)) / (lt['N']*exchange_rate) if lt['N']>0 else 0, (total_capital/MAX_TOTAL_UNITS)/(lt['Close']*exchange_rate)))

            else:
                lvls.extend([{'val': avg_e * 1.06, 'name': '6% 익절', 'col': 'blue'}, {'val': avg_e * 0.96, 'name': '4% 손절', 'col': 'red'}])
                st.success("💰 목표 도달") if profit >= 0.06 else (st.error("🛑 위험 감지") if profit <= -0.04 else st.info(f"✅ 순항 중 ({profit:.2%})"))

            lvls.append({'val': lt['Close'], 'name': '현재가', 'col': 'purple'})

            c_df = df.reset_index()[['Date', 'Close']].tail(60)
            chart = alt.layer(alt.Chart(c_df).mark_line(color='#1f77b4').encode(x=alt.X('Date:T', title=None), y=alt.Y('Close:Q', scale=alt.Scale(zero=False))), *[alt.layer(alt.Chart(pd.DataFrame({'y': [l['val']]})).mark_rule(strokeDash=[5, 5], color=l['col']).encode(y='y:Q'), alt.Chart(pd.DataFrame({'Date': [c_df['Date'].max()], 'y': [l['val']], 't': [f"{l['name']}: ${l['val']:.2f}"]})).mark_text(align='left', dx=5, dy=-4, color=l['col'], fontWeight='bold').encode(x='Date:T', y='y:Q', text='t:N')) for l in lvls if not pd.isna(l['val'])]).properties(height=320)
            st.altair_chart(chart, use_container_width=True)

            if add_shares >= 0.0001:
                if pos['Units'] < config.get("max_unit_per_stock", 2):
                    st.warning(f"🔔 추가 매수 타점! **{add_shares:.4f}주** 추가 검토") if ("터틀" in st_n and lt['Close'] >= add_pt) or ("BB" in st_n and lt['Close'] <= bb_add) else st.info(f"💡 대기 중: 타점 도달 시 **{add_shares:.4f}주** 권장")
                else: st.write("✅ 최대 허용 유닛 보유 중")

            c_p, c_s = st.columns(2)
            u_p, u_s = c_p.number_input("단가", value=float(lt['Close']), key=f"up_{tkr}"), c_s.number_input("수량", value=1.0, min_value=0.0001, format="%.4f", key=f"us_{tkr}")
            b_a, b_s, b_d = st.columns(3)
            
            if b_a.button("➕ 부분 매수", key=f"ba_{tkr}", use_container_width=True):
                pos['History'].append({'type': 'Buy', 'price': u_p, 'shares': u_s}); log_trade(tkr, 'Buy', u_p, u_s); st.rerun()
            if b_s.button("➖ 부분 매도", key=f"bs_{tkr}", use_container_width=True):
                if u_s >= total_s: 
                    del st.session_state.positions[tkr]
                    log_trade(tkr, 'Sell (All)', u_p, total_s, (u_p - avg_e) * total_s)
                else: 
                    pos['History'].append({'type': 'Sell', 'price': u_p, 'shares': u_s})
                    log_trade(tkr, 'Sell (Partial)', u_p, u_s, (u_p - avg_e) * u_s)
                st.rerun()
            if b_d.button("🔙 거래 취소", key=f"bd_{tkr}", use_container_width=True) and len(pos['History']) > 1:
                for idx in range(len(st.session_state.global_ledger)-1, -1, -1):
                    if st.session_state.global_ledger[idx]['ticker'] == tkr: 
                        st.session_state.global_ledger.pop(idx)
                        break
                pos['History'].pop()
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()
                
            st.table(pd.DataFrame([{'구분': '🔴 매수' if h.get('type','Buy') == 'Buy' else '🔵 매도', '단가': f"${h['price']:.2f}", '수량': f"{h['shares']:.4f}주"} for h in pos['History']]))

    if needs_save:
        save_data(st.session_state.positions, st.session_state.global_ledger)

    if st.session_state.positions or st.session_state.global_ledger:
        st.download_button("💾 데이터 백업 (CSV)", pd.DataFrame([{'Ticker': k, 'Units': v.get('Units', 1), 'Highest': v['Highest'], 'History': json.dumps(v['History']), 'Strategy': v['Strategy'], 'last_pyramid_level': v.get('last_pyramid_level')} for k, v in st.session_state.positions.items()] + [{'Ticker': '_GLOBAL_LEDGER_', 'Units': 0, 'Highest': 0.0, 'History': json.dumps(st.session_state.global_ledger), 'Strategy': 'SYSTEM', 'last_pyramid_level': None}]).to_csv(index=False).encode('utf-8-sig'), f"Backup_{datetime.now().strftime('%y%m%d')}.csv", "text/csv", use_container_width=True)

# ==========================================
# 8 & 9. 분석 / 뉴스 / 일지 탭
# ==========================================
with tabs[4]:
    if (t_in := st.text_input("티커 입력").upper()) and st.button("분석", use_container_width=True):
        if (d := analyze_ticker(t_in)) is not None:
            st.info(f"**[{t_in}]** 종가: **${d['Close'].iloc[-1]:.2f}** | RSI: **{d['RSI'].iloc[-1]:.1f}**")
            with st.expander("📋 SEC 공시", expanded=True): [st.write(f"**{f['form']}** ({f['date']}) - [링크]({f['url']})") for f in get_sec_filings(t_in)] or st.write("없음")
            with st.expander("📰 뉴스", expanded=True): [st.write(f"- [{n['title']}]({n['link']}) `{n['date']}`") for n in get_stock_news(t_in)] or st.write("없음")

with tabs[5]:
    if st.button("🔄 새로고침", use_container_width=True): get_global_news.clear(); st.rerun()
    [st.write(f"📍 [{i['title']}]({i['link']}) `{i['date']}`") for i in get_global_news()]

with tabs[6]:
    krw_profit = sum(i.get('realized_profit', 0) for i in st.session_state.global_ledger) * exchange_rate
    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("시드머니", f"₩{total_capital:,}")
    c_m2.metric("누적 수익금", f"₩{krw_profit:,.0f}", f"{(krw_profit / total_capital * 100) if total_capital else 0:.2f}%")
    c_m3.metric("거래 건수", f"{len(st.session_state.global_ledger)}건")
    if st.session_state.global_ledger:
        df_l = pd.DataFrame(st.session_state.global_ledger)[['timestamp', 'ticker', 'type', 'price', 'shares', 'realized_profit']]
        df_l.columns = ['일시', '티커', '구분', '단가($)', '수량(주)', '실현손익($)']
        df_l['단가($)'], df_l['수량(주)'], df_l['실현손익($)'] = df_l['단가($)'].apply(lambda x: f"${x:.2f}"), df_l['수량(주)'].apply(lambda x: f"{x:.4f}"), df_l['실현손익($)'].apply(lambda x: f"${x:.2f}" if x != 0 else "-")
        st.dataframe(df_l.iloc[::-1].reset_index(drop=True), use_container_width=True)
    with st.expander("⚠️ 관리자"):
        if st.button("🗑️ 장부 초기화"): st.session_state.global_ledger = []; save_data(st.session_state.positions, []); st.rerun()
