import streamlit as st
import yfinance as yf
import pandas as pd
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
    "🚀 터틀-상승": {"risk_pct": 1.0, "max_unit_per_stock": 4, "donchian_entry": 20, "trailing_days": 10, "pyramid_n": 0.5, "initial_stop_n": 2.0},
    "📈 20일-눌림목": {"risk_pct": 2.5, "max_unit_per_stock": 2},
    "📉 BB-낙폭과대": {"risk_pct": 1.5, "max_unit_per_stock": 2}
}

strategy_desc = {
    "🚀 터틀-상승": "20일 고점 돌파 및 200일선 위에서 강한 상승 추세를 타는 종목입니다. (추세 추종)",
    "📈 20일-눌림목": "우상향 중인 우량주가 20일 이동평균선 근처까지 건강한 조정을 받은 상태입니다. (눌림목)",
    "📉 BB-낙폭과대": "볼린저 밴드 하단 및 단기 이격도 과다로 인해 V자 반등이 기대되는 종목입니다. (낙폭과대)"
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
# 2. S&P 500 + 나스닥 100 우량주 유니버스
# ==========================================
TICKERS = [
    'A', 'AAPL', 'ABBV', 'ABT', 'ACGL', 'ACN', 'ADBE', 'ADI', 'ADM', 'ADP', 'ADSK', 'AEE', 'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG', 'AKAM', 'ALB', 'ALGN', 'ALL', 'ALLE', 'AMAT', 'AMCR', 'AMD', 'AME', 'AMGN', 'AMP', 'AMT', 'AMZN', 'ANET', 'ANSS', 'AON', 'AOS', 'APA', 'APD', 'APH', 'APTV', 'ARE', 'ATO', 'AVB', 'AVGO', 'AWK', 'AXON', 'AXP', 'AZO', 
    'BA', 'BAC', 'BALL', 'BAX', 'BBY', 'BDX', 'BEN', 'BG', 'BIIB', 'BIO', 'BK', 'BKNG', 'BKR', 'BLDR', 'BLK', 'BMY', 'BR', 'BRK-B', 'BRO', 'BSX', 'BWA', 'BXP', 
    'C', 'CAG', 'CAH', 'CARR', 'CAT', 'CB', 'CBOE', 'CBRE', 'CCI', 'CCL', 'CDNS', 'CDW', 'CE', 'CEG', 'CF', 'CFG', 'CHD', 'CHRW', 'CHTR', 'CI', 'CINF', 'CL', 'CLX', 'CMA', 'CMCSA', 'CME', 'CMG', 'CMI', 'CMS', 'CNC', 'CNP', 'COF', 'COO', 'COP', 'COR', 'COST', 'CPB', 'CPRT', 'CPT', 'CRL', 'CRM', 'CRWD', 'CSCO', 'CSGP', 'CSX', 'CTAS', 'CTLT', 'CTRA', 'CTSH', 'CTVA', 'CVS', 'CVX', 'CZR', 
    'D', 'DAL', 'DD', 'DE', 'DFS', 'DG', 'DGX', 'DHI', 'DHR', 'DIS', 'DLR', 'DLTR', 'DOV', 'DOW', 'DPZ', 'DRI', 'DTE', 'DUK', 'DVA', 'DVN', 'DXC', 'DXCM', 
    'EA', 'EBAY', 'ECL', 'ED', 'EFX', 'EG', 'EIX', 'EL', 'ELV', 'EMN', 'EMR', 'ENPH', 'EOG', 'EPAM', 'EQIX', 'EQR', 'EQT', 'ES', 'ESS', 'ETN', 'ETR', 'EVRG', 'EW', 'EXC', 'EXPD', 'EXPE', 'EXR', 
    'F', 'FANG', 'FAST', 'FCX', 'FDS', 'FDX', 'FE', 'FFIV', 'FI', 'FICO', 'FIS', 'FITB', 'FLT', 'FMC', 'FOX', 'FOXA', 'FRT', 'FSLR', 'FTNT', 
    'GD', 'GE', 'GEHC', 'GEN', 'GILD', 'GIS', 'GL', 'GLW', 'GM', 'GNRC', 'GOOG', 'GOOGL', 'GPC', 'GPN', 'GRMN', 'GS', 'GWW', 
    'HAL', 'HAS', 'HBAN', 'HCA', 'HD', 'HES', 'HIG', 'HII', 'HLT', 'HOLX', 'HON', 'HPE', 'HPQ', 'HRL', 'HSIC', 'HST', 'HSY', 'HUBB', 'HUM', 'HWM', 
    'IBM', 'ICE', 'IDXX', 'IEX', 'IFF', 'ILMN', 'INCY', 'INTC', 'INTU', 'INVH', 'IP', 'IPG', 'IQV', 'IR', 'IRM', 'ISRG', 'IT', 'ITW', 'IVZ', 
    'J', 'JBHT', 'JCI', 'JKHY', 'JNJ', 'JNPR', 'JPM', 
    'K', 'KDP', 'KEY', 'KEYS', 'KHC', 'KIM', 'KLAC', 'KMB', 'KMI', 'KMX', 'KO', 'KR', 'KVUE', 
    'L', 'LDOS', 'LEN', 'LH', 'LHX', 'LIN', 'LKQ', 'LLY', 'LMT', 'LNT', 'LOW', 'LRCX', 'LUV', 'LVS', 'LW', 'LYB', 'LYV', 
    'MA', 'MAC', 'MAR', 'MAS', 'MCD', 'MCHP', 'MCK', 'MCO', 'MDLZ', 'MDT', 'MET', 'META', 'MGM', 'MHK', 'MKC', 'MKTX', 'MLM', 'MMC', 'MMM', 'MNST', 'MO', 'MOH', 'MOS', 'MPC', 'MPWR', 'MRK', 'MRNA', 'MRVL', 'MS', 'MSCI', 'MSFT', 'MSI', 'MTB', 'MTCH', 'MTD', 'MU', 
    'NCLH', 'NDAQ', 'NDSN', 'NEE', 'NEM', 'NFLX', 'NI', 'NKE', 'NOC', 'NVR', 'NWL', 'NWS', 'NWSA', 'NXPI', 
    'O', 'ODFL', 'OKE', 'OMC', 'ON', 'ORCL', 'ORLY', 'OTIS', 'OXY', 
    'PANW', 'PARA', 'PAYC', 'PAYX', 'PCAR', 'PCG', 'PEAK', 'PEG', 'PEP', 'PFE', 'PFG', 'PG', 'PGR', 'PH', 'PHM', 'PKG', 'PLD', 'PM', 'PNC', 'PNR', 'PNW', 'PODD', 'POOL', 'PPG', 'PPL', 'PRU', 'PSA', 'PSX', 'PTC', 'PWR', 'PYPL', 
    'QCOM', 'QRVO', 
    'RCL', 'RE', 'REG', 'REGN', 'RF', 'RHI', 'RJF', 'RL', 'RMD', 'ROK', 'ROL', 'ROP', 'ROST', 'RSG', 'RTX', 'RVTY', 
    'SBAC', 'SBUX', 'SCHW', 'SHW', 'SJM', 'SLB', 'SNA', 'SNPS', 'SO', 'SPG', 'SPGI', 'SRE', 'STE', 'STLD', 'STT', 'STX', 'STZ', 'SWK', 'SWKS', 'SYF', 'SYK', 'SYY', 
    'T', 'TAP', 'TDG', 'TDY', 'TECH', 'TEL', 'TER', 'TFC', 'TFX', 'TGT', 'TJX', 'TMO', 'TMUS', 'TPR', 'TRGP', 'TRMB', 'TROW', 'TRV', 'TSCO', 'TSLA', 'TSN', 'TT', 'TTWO', 'TXN', 'TXT', 'TYL', 
    'UAL', 'UBER', 'UDR', 'UHS', 'ULTA', 'UNP', 'UPS', 'URI', 'USB', 
    'V', 'VLO', 'VMC', 'VRSK', 'VRSN', 'VRTX', 'VTR', 'VZ', 
    'WAB', 'WAT', 'WBA', 'WBD', 'WDC', 'WEC', 'WELL', 'WFC', 'WHR', 'WM', 'WMB', 'WMT', 'WRB', 'WST', 'WY', 'WYNN', 
    'XEL', 'XOM', 'XYL', 
    'YUM', 'ZBH', 'ZBRA', 'ZION', 'ZTS',
    'TEAM', 'DDOG', 'MDB', 'ZS', 'WDAY', 'SNOW', 'PLTR', 'APP', 'TOST', 'CART', 'SG', 'SMCI', 'TMDX',
    'SPY', 'QQQ', 'IWM', 'XBI', 'DIA', 'VTI'
]

TICKERS = sorted(list(set(TICKERS)))

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
                'Highest': float(row['Highest']), 
                'History': history,
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
# 4. 분석 엔진 (지표 계산)
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
    
    df['High20'] = df['High'].rolling(20).max().shift(1)
    df['Low10'] = df['Low'].rolling(10).min().shift(1)
    
    df['MA200'] = df['Close'].rolling(200).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA5'] = df['Close'].rolling(5).mean()

    df['MA18'] = df['Close'].rolling(18).mean()
    df['Std18'] = df['Close'].rolling(18).std()
    df['BB_Lower_18'] = df['MA18'] - (df['Std18'] * 2)

    df['Std5'] = df['Close'].rolling(5).std()
    df['BB_Lower_5'] = df['MA5'] - (df['Std5'] * 2)

    delta = df['Close'].diff()
    avg_gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    avg_loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
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
st.set_page_config(page_title="Turtle Pro V7.55 (Master)", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions, st.session_state.global_ledger = load_data()

st.sidebar.header("⚙️ 리스크 및 시스템 설정")
total_capital = int(st.sidebar.number_input("시드머니 (만원)", value=200, step=50) * 10000)
exchange_rate = st.sidebar.number_input("현재환율 (₩/$)", value=1450, step=10)
st.sidebar.info(f"💡 **현재 유니버스:**\nS&P 500, 나스닥 100 등 총 **{len(TICKERS)}개** 종목 무필터 스캔 중.")

# --- 리스크 게이지 ---
st.sidebar.markdown("---")
st.sidebar.subheader("🚦 계좌 리스크 게이지")
current_units = sum(pos.get('Units', 0) for pos in st.session_state.positions.values())
risk_ratio = min(current_units / MAX_TOTAL_UNITS, 1.0)
st.sidebar.progress(risk_ratio, text=f"투입 유닛: {current_units} / {MAX_TOTAL_UNITS} MAX")

if current_units >= MAX_TOTAL_UNITS:
    st.sidebar.error("⚠️ 최대 허용 유닛 도달! 신규 매수 금지")
elif current_units >= MAX_TOTAL_UNITS * 0.8:
    st.sidebar.warning("⚡ 리스크 한도 임박 (80% 이상)")
else:
    st.sidebar.success("✅ 리스크 관리 양호")
st.sidebar.markdown("---")

# --- CSV 백업/복구 업로더 ---
if up_file := st.sidebar.file_uploader("📂 백업 CSV 업로드"):
    if st.sidebar.button("데이터 즉시 복구", type="primary"):
        try:
            df = pd.read_csv(up_file)
            st.session_state.positions = {row['Ticker']: {'Units': len([h for h in (json.loads(row['History']) if isinstance(row['History'], str) else []) if h.get('type', 'Buy') == 'Buy']), 'Highest': float(row['Highest']), 'History': json.loads(row['History']) if isinstance(row['History'], str) else [], 'Strategy': row['Strategy'], 'last_pyramid_level': row.get('last_pyramid_level') if pd.notna(row.get('last_pyramid_level')) else None} for _, row in df[df['Ticker'] != '_GLOBAL_LEDGER_'].iterrows()}
            st.session_state.global_ledger = next((json.loads(row['History']) for _, row in df[df['Ticker'] == '_GLOBAL_LEDGER_'].iterrows()), [])
            save_data(st.session_state.positions, st.session_state.global_ledger)
            st.rerun()
        except Exception as e: 
            st.sidebar.error(f"❌ 오류: {e}")

# 메인 타이틀 및 시장 상태 필터
st.title("🐢 Turtle System Pro V7.55")
is_bull, spy_val, ma200_val, is_trending = check_market_filter()

if is_bull: 
    st.success(f"🟢 시장 통과 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {'📈 상승 추세' if is_trending else '➡️ 횡보'}")
else: 
    st.error(f"🔴 시장 경고 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {'📈 상승 추세' if is_trending else '➡️ 횡보/하락'}")

# --- 시장 상황별 맞춤 트레이딩 가이드 ---
with st.expander("💡 현재 시장 상황 맞춤 트레이딩 가이드", expanded=True):
    if spy_val >= ma200_val and is_trending:
        st.markdown("#### 🌞 [완벽한 강세장] 적극적인 추세 추종")
        st.write("지수가 장기 생명선(200일선) 위에 있고 추세도 살아있는 **최적의 장세**입니다.")
        st.markdown("- **1순위 (적극 추천):** `📈 20일-눌림목` (우상향 주도주의 건강한 조정을 공략)\n- **2순위:** `🚀 터틀-상승` (강력한 돌파 매매 가능)\n- **비추천:** `📉 BB-낙폭과대` (초우량주는 하단 밴드까지 잘 떨어지지 않음)")
    elif spy_val >= ma200_val and not is_trending:
        st.markdown("#### ⛅ [횡보/조정장] 돌파 매매 주의")
        st.write("지수가 200일선 위에는 있지만, 단기적으로 힘이 빠져 횡보하고 있습니다.")
        st.markdown("- **1순위 (추천):** `📈 20일-눌림목` (박스권 하단 지지 확인 후 매수)\n- **2순위:** `📉 BB-낙폭과대` (단기 급락 종목 위주)\n- **❌ 금지:** `🚀 터틀-상승` (가짜 돌파에 속아 고점에 물릴 위험 큼)")
    elif spy_val < ma200_val and is_trending:
        st.markdown("#### ⛈️ [강세장 속 폭락] 패닉 셀링 줍기")
        st.write("장기 펀더멘털은 견고하나 악재/투매로 지수가 200일선을 깬 **공포 장세**입니다.")
        st.markdown("- **1순위 (강력 추천):** `📉 BB-낙폭과대` (억울하게 폭락한 우량주의 V자 반등을 노리는 바닥 쇼핑 찬스)\n- **⚠️ 주의:** `📈 20일-눌림목` (지하실로 뚫고 갈 수 있으므로 평소 비중의 절반만 접근)\n- **❌ 절대 금지:** `🚀 터틀-상승`")
    else:
        st.markdown("#### ❄️ [완벽한 빙하기] 현금 관망 최우선")
        st.write("지수가 200일선 아래에 있고 추세마저 꺾인 **대세 하락장**입니다.")
        st.markdown("- **1순위:** **현금 관망 (스캐너 사용 자제)**\n- **2순위 (초단기 대응):** `📉 BB-낙폭과대` (극단적 투매 시 3분할 트레일링 스탑으로 짧게만 대응)\n- **❌ 절대 금지:** `🚀 터틀-상승`, `📈 20일-눌림목`")

tabs = st.tabs(["🚀 터틀", "📈 눌림목", "📉 BB낙폭", "📋 매니저", "🇺🇸 분석", "🌍 뉴스", "📊 일지"])

# ==========================================
# 6. 스캐너 탭 
# ==========================================
for i, s_name in enumerate(["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"]):
    with tabs[i]:
        st.info(f"💡 **전략 설명:** {strategy_desc.get(s_name, '')}")
        config = STRATEGY_CONFIG.get(s_name, {"risk_pct": 2.0})
        if st.button(f"🔎 {s_name} 스캔 (총 {len(TICKERS)}개)", key=f"run_{i}", use_container_width=True):
            res, is_cand = [], False
            pb = st.progress(0, text="전 종목 분석 중... (최대 5분 소요)")
            
            for idx, tkr in enumerate(TICKERS):
                pb.progress((idx + 1) / len(TICKERS))
                if (df := analyze_ticker(tkr)) is not None:
                    lt, pv = df.iloc[-1], df.iloc[-2]
                    cond = False
                    
                    if "터틀" in s_name:
                        cond = (lt['Close'] > lt['High20']) and (lt['Close'] > lt['MA200'])
                    elif "눌림목" in s_name:
                        signal = (df['Low'].iloc[-5:] <= df['MA20'].iloc[-5:]).any()
                        cond = signal and (lt['Close'] > lt['MA5']) and (pv['Close'] <= pv['MA5']) and (lt['Close'] > lt['MA200'])
                    else: 
                        cond = (lt['BB_Lower_5'] < lt['BB_Lower_18']) and (lt['BB_Lower_5'] <= lt['Close'] <= lt['BB_Lower_18'])

                    if cond:
                        risk_sh = (total_capital * (config["risk_pct"] / 100)) / (lt['N'] * exchange_rate) if lt['N'] > 0 else 0
                        cash_sh = (total_capital / MAX_TOTAL_UNITS) / (lt['Close'] * exchange_rate)
                        final_sh = round(min(risk_sh, cash_sh), 4)
                        if final_sh >= 0.0001: 
                            res.append({"tkr": tkr, "p": lt['Close'], "sh": final_sh, "n": lt['N']})
            pb.empty()
            if not res: 
                st.info("ℹ️ 포착된 종목이 없습니다.")

            for r in res:
                with st.container(border=True):
                    l_col, r_col = st.columns([3, 1])
                    l_col.write(f"### {r['tkr']} [✅ 포착]\n현재가: ${r['p']:.2f} | 수량: {r['sh']:.4f}주 | N: ${r['n']:.2f}")
                    if r_col.button("➕ 등록", key=f"reg_{r['tkr']}_{i}"):
                        st.session_state.positions[r['tkr']] = {
                            'Units': 1, 'Highest': r['p'], 
                            'History': [{'type': 'Buy', 'price': r['p'], 'shares': r['sh']}], 
                            'Strategy': s_name, 'last_pyramid_level': r['p']
                        }
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
        m_p = mc3.number_input("진입가", value=0.0)
        m_h = mc4.number_input("수량", value=1.0, min_value=0.0001, format="%.4f")
        if st.button("➕ 등록", use_container_width=True) and m_t:
            st.session_state.positions[m_t] = {
                'Units': 1, 'Highest': m_p, 
                'History': [{'type': 'Buy', 'price': m_p, 'shares': m_h}], 
                'Strategy': m_s, 'last_pyramid_level': m_p
            }
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
                    if active_lots[-1]['shares'] > rem_sell: 
                        active_lots[-1]['shares'] -= rem_sell
                        rem_sell = 0
                    else: 
                        rem_sell -= active_lots[-1]['shares']
                        active_lots.pop()
        
        if total_s <= 0.0001:
            del st.session_state.positions[tkr]
            needs_save = True
            continue
            
        pos['Units'] = len(active_lots)
        pos['last_pyramid_level'] = active_lots[-1]['price'] if active_lots else avg_e
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

            max_u = config.get("max_unit_per_stock", 2)
            curr_u = pos['Units']
            fill_pct = (curr_u / max_u) * 100 if max_u > 0 else 0
            
            st.write(f"**🛒 진입 현황:** 총 **{curr_u}회** 매수 진행 / 최대 **{max_u}회** 진입 가능 (`할당량의 {fill_pct:.0f}%` 채움)")
            st.progress(min(curr_u / max_u, 1.0) if max_u > 0 else 0.0)

            lvls, add_pt = [{'val': avg_e, 'name': '평단가', 'col': 'gray'}], 0.0

            if "터틀" in st_n:
                base_p = pos.get('last_pyramid_level', avg_e)
                dyn_stop, add_pt, trail = base_p - (2.0 * lt['N']), base_p + (0.5 * lt['N']), lt['Low10']
                lvls.extend([
                    {'val': dyn_stop, 'name': '통합손절', 'col': 'red'}, 
                    {'val': trail, 'name': 'Trailing', 'col': 'green'}, 
                    {'val': add_pt, 'name': '불타기', 'col': 'orange'}
                ])
                
                # 추천 수량 계산
                risk_sh = (total_capital * (config["risk_pct"] / 100)) / (lt['N'] * exchange_rate) if lt['N'] > 0 else 0
                cash_sh = (total_capital / MAX_TOTAL_UNITS) / (lt['Close'] * exchange_rate)
                add_shares = round(min(risk_sh, cash_sh), 4)

                effective_stop = max(dyn_stop, trail)
                stop_name = "Trailing(10일저점)" if effective_stop == trail else "통합손절(-2N)"

                if lt['Close'] < effective_stop:
                    st.error(f"🛑 {stop_name} 이탈! 전량 매도 권장 (${effective_stop:.2f})")
                elif lt['Close'] >= add_pt:
                    if curr_u < max_u:
                        st.success(f"🔥 불타기(추가매수) 포인트 도달! (${add_pt:.2f}) 👉 추천 수량: {add_shares:.4f}주 ({curr_u + 1}유닛)")
                    else:
                        st.warning(f"⚠️ 불타기 포인트(${add_pt:.2f}) 도달했으나 종목 할당 유닛 초과로 추가매수 금지")
                else:
                    # [수정] 도달 전 미리 다음 불타기 정보 표시
                    status_msg = f"✅ 순항 중 (수익률: {profit:.2%} | {stop_name}: ${effective_stop:.2f})"
                    if curr_u < max_u:
                        st.info(f"{status_msg} \n\n **📍 다음 불타기(${add_pt:.2f})에서 추천 매수수량 {add_shares:.4f}주 ({curr_u + 1}유닛)**")
                    else:
                        st.info(f"{status_msg} \n\n **📍 다음 불타기(${add_pt:.2f})에서 종목 할당 유닛 초과로 추가매수금지**")
            
            elif "BB" in st_n or "낙폭과대" in st_n or "눌림목" in st_n:
                profit_highest = (pos['Highest'] / avg_e - 1) if avg_e > 0 else 0
                
                if profit_highest >= 0.10:
                    dyn_sl, sl_name = avg_e * 1.10, "TS 방어선 (+10%)"
                elif profit_highest >= 0.06:
                    dyn_sl, sl_name = avg_e * 1.06, "TS 방어선 (+6%)"
                else:
                    dyn_sl, sl_name = avg_e * 0.96, "초기 손절 (-4%)"
                    
                tp1, tp2, tp3 = avg_e * 1.06, avg_e * 1.10, avg_e * 1.15
                
                lvls.extend([
                    {'val': dyn_sl, 'name': sl_name, 'col': 'red'}, 
                    {'val': tp1, 'name': '1차(+6%)', 'col': 'blue'}, 
                    {'val': tp2, 'name': '2차(+10%)', 'col': 'darkblue'},
                    {'val': tp3, 'name': '3차(+15%)', 'col': 'purple'}
                ])
                
                if lt['Close'] < dyn_sl: 
                    st.error(f"🛑 {sl_name} 이탈! 전량 매도 권장 (${dyn_sl:.2f})")
                elif lt['Close'] >= tp3: 
                    st.success(f"🎉 3차 익절(+15%) 도달! 남은 전량 익절 권장 (${tp3:.2f})")
                elif lt['Close'] >= tp2: 
                    st.success(f"💰 2차 익절(+10%) 도달! 25% 매도 권장 (현재 방어선: 본전+10%)")
                elif lt['Close'] >= tp1: 
                    st.success(f"💵 1차 익절(+6%) 도달! 50% 매도 권장 (현재 방어선: 본전+6%)")
                else: 
                    st.info(f"✅ 순항 중 (수익률: {profit:.2%} | {sl_name}: ${dyn_sl:.2f})")

            lvls.append({'val': lt['Close'], 'name': '현재가', 'col': 'purple'})
            
            c_df = df.reset_index()[['Date', 'Close']].tail(60)
            chart = alt.layer(
                alt.Chart(c_df).mark_line(color='#1f77b4').encode(
                    x=alt.X('Date:T', title=None), 
                    y=alt.Y('Close:Q', scale=alt.Scale(zero=False))
                ), 
                *[alt.layer(
                    alt.Chart(pd.DataFrame({'y': [l['val']]})).mark_rule(strokeDash=[5, 5], color=l['col']).encode(y='y:Q'), 
                    alt.Chart(pd.DataFrame({'Date': [c_df['Date'].max()], 'y': [l['val']], 't': [f"{l['name']}: ${l['val']:.2f}"]})).mark_text(align='left', dx=5, dy=-4, color=l['col'], fontWeight='bold').encode(x='Date:T', y='y:Q', text='t:N')
                ) for l in lvls if not pd.isna(l['val'])]
            ).properties(height=320)
            
            st.altair_chart(chart, use_container_width=True)

            c_p, c_s = st.columns(2)
            u_p = c_p.number_input("단가", value=float(lt['Close']), key=f"up_{tkr}")
            u_s = c_s.number_input("수량", value=1.0, min_value=0.0001, format="%.4f", key=f"us_{tkr}")
            b_a, b_s, b_d = st.columns(3)
            
            if b_a.button("➕ 부분 매수", key=f"ba_{tkr}", use_container_width=True): 
                pos['History'].append({'type': 'Buy', 'price': u_p, 'shares': u_s})
                log_trade(tkr, 'Buy', u_p, u_s)
                st.rerun()
            
            if b_s.button("➖ 부분 매도", key=f"bs_{tkr}", use_container_width=True):
                if u_s >= total_s: 
                    del st.session_state.positions[tkr]
                    log_trade(tkr, 'Sell (All)', u_p, total_s, (u_p - avg_e) * total_s)
                else: 
                    pos['History'].append({'type': 'Sell', 'price': u_p, 'shares': u_s})
                    log_trade(tkr, 'Sell (Partial)', u_p, u_s, (u_p - avg_e) * u_s)
                st.rerun()
                
            if b_d.button("🔙 취소", key=f"bd_{tkr}", use_container_width=True):
                for idx in range(len(st.session_state.global_ledger)-1, -1, -1):
                    if st.session_state.global_ledger[idx]['ticker'] == tkr: 
                        st.session_state.global_ledger.pop(idx)
                        break
                pos['History'].pop()
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()

            with st.expander(f"📜 {tkr} 매수/매도 상세 내역", expanded=False):
                if pos['History']:
                    hist_df = pd.DataFrame(pos['History'])
                    hist_df.rename(columns={'type': '거래 유형', 'price': '체결 단가($)', 'shares': '체결 수량'}, inplace=True)
                    st.dataframe(hist_df, use_container_width=True, hide_index=True)
                else:
                    st.write("거래 내역이 없습니다.")

    if needs_save: save_data(st.session_state.positions, st.session_state.global_ledger)

# ==========================================
# 8 & 9. 분석 / 뉴스 / 일지 탭
# ==========================================
with tabs[4]:
    if (t_in := st.text_input("티커 분석").upper()) and st.button("분석 실행"):
        if (d := analyze_ticker(t_in)) is not None:
            st.info(f"**[{t_in}]** 종가: **${d['Close'].iloc[-1]:.2f}** | RSI: **{d['RSI'].iloc[-1]:.1f}**")
            with st.expander("📋 SEC", expanded=True): 
                [st.write(f"- {f['form']} ({f['date']}) [링크]({f['url']})") for f in get_sec_filings(t_in)]
            with st.expander("📰 뉴스", expanded=True): 
                [st.write(f"- [{n['title']}]({n['link']})") for n in get_stock_news(t_in)]

with tabs[5]:
    if st.button("🔄 뉴스 새로고침"): 
        get_global_news.clear()
        st.rerun()
    [st.write(f"📍 [{i['title']}]({i['link']})") for i in get_global_news()]

with tabs[6]:
    krw_profit = sum(i.get('realized_profit', 0) for i in st.session_state.global_ledger) * exchange_rate
    st.metric("누적 수익금", f"₩{krw_profit:,.0f}", f"{(krw_profit / total_capital * 100) if total_capital else 0:.2f}%")
    if st.session_state.global_ledger:
        df_l = pd.DataFrame(st.session_state.global_ledger).iloc[::-1]
        st.dataframe(df_l, use_container_width=True)

