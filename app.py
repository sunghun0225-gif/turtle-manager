import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import os, time, requests, json, feedparser, urllib.parse
import altair as alt
from datetime import datetime, timedelta
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import locale
import pandas.tseries.offsets as offsets

try:
    locale.setlocale(locale.LC_TIME, 'ko_KR.UTF-8')
except:
    pass

# ==========================================
# 1. 설정 및 리스크 파라미터 (분할 매수 최적화)
# ==========================================
DB_FILE = 'internal_memory.csv'
MAX_TOTAL_UNITS = 10 

# 분할 매수를 위해 눌림목과 낙폭과대의 최대 유닛을 2(1차 50%, 2차 50%)로 설정
STRATEGY_CONFIG = {
    "🚀 터틀-상승": {"risk_pct": 1.0, "max_unit_per_stock": 4, "donchian_entry": 20, "trailing_days": 10, "pyramid_n": 0.5, "initial_stop_n": 2.0},
    "📈 20일-눌림목": {"risk_pct": 2.5, "max_unit_per_stock": 2},
    "📉 BB-낙폭과대": {"risk_pct": 1.5, "max_unit_per_stock": 2}
}

strategy_desc = {
    "🚀 터틀-상승": "강세장에서 20일 고점을 돌파하는 주도주를 잡습니다.",
    "📈 20일-눌림목": "우상향 우량주가 조정을 마치고 반등(RSI 40 돌파 & MACD 상승)할 때 1차 진입합니다.",
    "📉 BB-낙폭과대": "단기 패닉셀로 볼린저 하단을 뚫고 RSI 35를 회복할 때 1차 진입합니다."
}

# 기존 540여개 유니버스 완벽 유지
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
# 2. 데이터 수집
# ==========================================
def get_last_trading_date():
    today = pd.Timestamp.now(tz='America/New_York').normalize()
    if today.weekday() >= 5: last_trading = today - offsets.BDay(1)
    else: last_trading = today - offsets.BDay(0)
    while True:
        df_test = yf.download("SPY", start=last_trading.strftime('%Y-%m-%d'), end=last_trading.strftime('%Y-%m-%d'), progress=False, timeout=10)
        if len(df_test) > 0: return last_trading
        last_trading -= timedelta(days=1)

def safe_download_single(ticker_symbol, period="1y", retries=3):
    for attempt in range(retries):
        try:
            tkr = yf.Ticker(ticker_symbol)
            df = tkr.history(period=period)
            if len(df) > 20:
                if df.index.tz is not None: df.index = df.index.tz_localize(None)
                return df
        except: pass
        try:
            df = yf.download(ticker_symbol, period=period, progress=False, timeout=15)
            if len(df) > 20:
                if df.index.tz is not None: df.index = df.index.tz_localize(None)
                return df
        except: pass
        time.sleep(1.5 ** attempt)
    return None

@st.cache_data(ttl=1800, show_spinner=False)
def bulk_download_all():
    chunks = [TICKERS[i:i+50] for i in range(0, len(TICKERS), 50)]
    all_data = {}
    pb = st.progress(0, text="📥 야후 파이낸스 대량 데이터 수집 중...")
    for idx, chunk in enumerate(chunks):
        try:
            data = yf.download(chunk, period="1y", progress=False, timeout=25, threads=True, repair=True, group_by='ticker')
            if isinstance(data.columns, pd.MultiIndex):
                for ticker in chunk:
                    try:
                        if ticker in data.columns.get_level_values(0):
                            df = data[ticker].dropna(how='all')
                            if len(df) > 20: all_data[ticker] = df
                    except: pass
            else:
                if len(data) > 20 and len(chunk) == 1: all_data[chunk[0]] = data.dropna(how='all')
        except: pass
        pb.progress((idx + 1) / len(chunks))
        time.sleep(1.0)
    pb.empty()
    return all_data

# ==========================================
# 3. 데이터 기록 (세션)
# ==========================================
def load_data():
    positions, global_ledger = {}, []
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        for _, row in df.iterrows():
            tkr = row['Ticker']
            history = json.loads(row['History']) if isinstance(row['History'], str) else []
            if tkr == '_GLOBAL_LEDGER_':
                global_ledger = history
                continue
            for h in history: h['shares'] = float(h.get('shares', 0.0))
            positions[tkr] = {
                'Units': len([h for h in history if h.get('type') == 'Buy']),
                'Highest': float(row['Highest']),
                'History': history,
                'Strategy': row.get('Strategy', '🚀 터틀-상승')
            }
    return positions, global_ledger

def save_data(positions, global_ledger):
    rows = [{'Ticker': k, 'Units': v.get('Units', 1), 'Highest': v['Highest'],
             'History': json.dumps(v.get('History', [])), 'Strategy': v.get('Strategy')}
            for k, v in positions.items()]
    rows.append({'Ticker': '_GLOBAL_LEDGER_', 'Units': 0, 'Highest': 0.0, 'History': json.dumps(global_ledger), 'Strategy': 'SYSTEM'})
    pd.DataFrame(rows).to_csv(DB_FILE, index=False)

def log_trade(tkr, trade_type, price, shares, profit=0.0):
    st.session_state.global_ledger.append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ticker': tkr, 'type': trade_type, 'price': float(price),
        'shares': float(shares), 'realized_profit': float(profit)
    })
    save_data(st.session_state.positions, st.session_state.global_ledger)

# ==========================================
# 4. 분석 엔진 (지표 & 턴어라운드 로직)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def check_market_filter():
    try:
        spy = safe_download_single("SPY", period="1y")
        if spy is None: return True, 0.0, 0.0, False, "데이터 실패"
        if isinstance(spy.columns, pd.MultiIndex): spy.columns = spy.columns.get_level_values(0)
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy = float(spy['Close'].iloc[-1])
        ma200_now = float(spy['MA200'].iloc[-1])
        is_trending_up = float(spy['MA200'].iloc[-1]) > float(spy['MA200'].iloc[-2])
        return (curr_spy > ma200_now), curr_spy, ma200_now, is_trending_up, spy.index[-1].strftime('%Y-%m-%d')
    except:
        return True, 0.0, 0.0, False, "오류"

def compute_indicators(df):
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df['MA200'] = df['Close'].rolling(200).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['High20'] = df['High'].rolling(20).max().shift(1)
    
    df['MA18'] = df['Close'].rolling(18).mean()
    df['Std18'] = df['Close'].rolling(18).std()
    df['BB_Lower'] = df['MA18'] - (df['Std18'] * 2)

    delta = df['Close'].diff()
    avg_gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    avg_loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / (avg_loss + 1e-9))))
    df['RSI_Prev'] = df['RSI'].shift(1)

    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    df['MACD_Hist_Prev'] = df['MACD_Hist'].shift(1)
    
    df['TR'] = df.apply(lambda x: max(x['High'] - x['Low'], abs(x['High'] - x['Close']), abs(x['Low'] - x['Close'])), axis=1)
    df['N'] = df['TR'].rolling(20).mean()
    
    return df

def analyze_ticker_from_bulk(ticker, all_data):
    if ticker not in all_data: return None
    df = all_data[ticker].copy()
    if len(df) < 200: return None
    return compute_indicators(df)

def update_position_state(tkr, pos, df):
    if df is None: return None
    lt = df.iloc[-1]
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
    if total_s <= 0.0001: return None
    pos['Units'] = len(active_lots)
    if lt['Close'] > pos['Highest']: pos['Highest'] = lt['Close']
    return pos, avg_e, total_s, lt

# ==========================================
# 5. 메인 UI 및 스캐너
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.66 (Smart Scaling)", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions, st.session_state.global_ledger = load_data()

st.sidebar.header("⚙️ 시스템 설정 (V7.66)")
total_capital = int(st.sidebar.number_input("시드머니 (만원)", value=200, step=50) * 10000)
exchange_rate = st.sidebar.number_input("현재환율 (₩/$)", value=1450, step=10)
st.sidebar.info(f"💡 **현재 유니버스:** S&P 500 등 총 **{len(TICKERS)}개** (유지됨)")

is_bull, spy_val, ma200_val, is_trending, last_date = check_market_filter()
st.title("🐢 Turtle System Pro V7.66")
st.caption("✨ 스마트 분할 매수 및 다이내믹 익절 엔진 탑재 완료")

if is_bull:
    st.success(f"🟢 시장 통과 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {'📈 강세장' if is_trending else '➡️ 조정장'}")
else:
    st.error(f"🔴 시장 경고 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | 📉 약세장")

tabs = st.tabs(["🔎 스마트 스캐너", "📋 매니저", "📊 일지"])

# --- 스캐너 탭 ---
with tabs[0]:
    st.write("💡 시장(SPY)의 흐름에 맞춰 현재 가장 유리한 전략을 시스템이 스스로 추천하고 검색합니다.")
    
    if is_bull and is_trending:
        target_s = "🚀 터틀-상승"
        st.info("🌞 **현재 시장:** 강세장 \n👉 20일 고점을 돌파하는 주도주(터틀)를 1차 타겟으로 스캔합니다.")
    elif is_bull and not is_trending:
        target_s = "📈 20일-눌림목"
        st.info("⛅ **현재 시장:** 조정장 \n👉 건강한 조정을 마치고 턴어라운드하는 눌림목 종목을 1차 타겟으로 스캔합니다. (RSI 40 완화 적용)")
    else:
        target_s = "📉 BB-낙폭과대"
        st.error("⛈️ **현재 시장:** 폭락/약세장 \n👉 패닉셀 진정 후 반등하는 낙폭과대 종목만 극도로 제한적으로 스캔합니다. (RSI 35 완화 적용)")

    if st.button(f"🔎 현재 시장 맞춤 스캔 실행 ({target_s})", use_container_width=True):
        res = []
        all_data = bulk_download_all()
        pb = st.progress(0, text="종목 분석 및 턴어라운드(무릎) 타점 계산 중...")
        
        for idx, tkr in enumerate(TICKERS):
            pb.progress((idx + 1) / len(TICKERS))
            df = analyze_ticker_from_bulk(tkr, all_data)
            if df is not None:
                lt = df.iloc[-1]
                macd_turn = lt['MACD_Hist'] > lt['MACD_Hist_Prev'] # 공통: 하락세 진정
                
                cond = False
                if target_s == "🚀 터틀-상승":
                    cond = (lt['Close'] > lt['High20']) and (lt['Close'] > lt['MA200']) and (lt['MACD_Hist'] > 0)
                elif target_s == "📈 20일-눌림목":
                    cond = (lt['RSI_Prev'] <= 40) and (lt['RSI'] > 40) and macd_turn and (lt['Close'] > lt['MA200'])
                else:
                    cond = (lt['RSI_Prev'] <= 35) and (lt['RSI'] > 35) and macd_turn and (lt['Close'] <= lt['BB_Lower'])

                if cond:
                    # 추천 수량 (할당량의 50% 분할 매수용으로 안내)
                    slot_usd = (total_capital / MAX_TOTAL_UNITS) / exchange_rate
                    buy_usd = slot_usd if target_s == "🚀 터틀-상승" else slot_usd / 2
                    sh = round(buy_usd / lt['Close'], 4)
                    res.append({"tkr": tkr, "p": lt['Close'], "sh": sh, "n": lt['N']})
        pb.empty()
        
        if not res: st.warning("📢 현재 시장 조건에 부합하는 타점이 없습니다.")
        else:
            for r in res:
                with st.container(border=True):
                    l_col, r_col = st.columns([3, 1])
                    l_col.write(f"### {r['tkr']} [✅ 포착]\n현재가: ${r['p']:.2f} | 1차 추천수량: {r['sh']:.4f}주")
                    if r_col.button("➕ 1차 진입", key=f"reg_{r['tkr']}"):
                        st.session_state.positions[r['tkr']] = {
                            'Units': 1, 'Highest': r['p'],
                            'History': [{'type': 'Buy', 'price': r['p'], 'shares': r['sh']}],
                            'Strategy': target_s
                        }
                        log_trade(r['tkr'], 'Buy', r['p'], r['sh'])
                        st.rerun()

# --- 매니저 탭 ---
with tabs[1]:
    for tkr, pos in list(st.session_state.positions.items()):
        df = analyze_ticker_from_bulk(tkr, bulk_download_all()) if len(st.session_state.positions) <= 5 else safe_download_single(tkr)
        if df is None: df = safe_download_single(tkr)
        if df is None: continue
        
        df = compute_indicators(df)
        st_n = pos['Strategy']
        updated = update_position_state(tkr, pos, df)
        if updated is None:
            del st.session_state.positions[tkr]
            st.rerun()
            continue
            
        pos, avg_e, total_s, lt = updated
        profit = (lt['Close'] / avg_e - 1) if avg_e > 0 else 0.0

        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            h1.markdown(f"#### {tkr} :{'blue' if '터틀' in st_n else ('green' if '눌림목' in st_n else 'red')}[({st_n})] - {total_s:.4f}주")
            h1.caption(f"📊 평단가: **${avg_e:.2f}** | RSI: **{lt['RSI']:.1f}** | MACD: **{lt['MACD_Hist']:.2f}**")
            
            if h2.button("전량 매도", key=f"ex_{tkr}"):
                del st.session_state.positions[tkr]
                log_trade(tkr, 'Sell (All)', lt['Close'], total_s, (lt['Close'] - avg_e) * total_s)
                st.rerun()

            curr_u = pos['Units']
            
            # --- 💡 스마트 다이내믹 알림 엔진 ---
            is_macd_dead = lt['MACD_Hist'] < 0
            is_rsi_falling = (lt['RSI_Prev'] >= 70) and (lt['RSI'] < 70)
            
            # 1. 익절 알림 (10% 천장 철거, 지표 꺾임 시 전량 매도)
            if profit > 0 and (is_macd_dead or is_rsi_falling):
                st.error("🔥 **[다이내믹 익절 경고]** 추세 꺾임(MACD 데드크로스 또는 RSI 과매수 이탈) 감지! 지금 전량 매도하여 수익을 확정하세요!")
            # 2. 손절 알림 (-7% 룰)
            elif profit <= -0.07:
                st.error("🛑 **[비상 탈출]** 손절선(-7%) 이탈! 추가 하락 방지를 위해 전량 매도하세요!")
            # 3. 2차 매수 알림 (분할 매수)
            elif curr_u == 1 and st_n != "🚀 터틀-상승":
                macd_turn = lt['MACD_Hist'] > lt['MACD_Hist_Prev']
                second_buy = False
                if st_n == "📈 20일-눌림목" and (lt['Close'] <= lt['MA60'] * 1.02) and macd_turn:
                    second_buy = True
                elif st_n == "📉 BB-낙폭과대" and (lt['RSI_Prev'] <= 35) and (lt['RSI'] > 35):
                    second_buy = True
                
                if second_buy:
                    st.success("📍 **[2차 매수 타점 도달]** 바닥 다지기 확인! 남은 비중(50%)을 추가 매수하여 평단가를 낮추세요!")
                else:
                    st.info(f"✅ 순항 중 (수익률: {profit:.2%}) | 2차 매수 타점을 기다리는 중입니다.")
            else:
                 st.info(f"✅ 순항 중 (수익률: {profit:.2%}) | 추세 끝까지 수익 극대화 중!")

            # 차트 (기존 유지)
            c_df = df.reset_index()[['Date', 'Close']].tail(60)
            chart = alt.Chart(c_df).mark_line().encode(x='Date:T', y=alt.Y('Close:Q', scale=alt.Scale(zero=False))).properties(height=200)
            st.altair_chart(chart, use_container_width=True)

            c_p, c_s = st.columns(2)
            u_p = c_p.number_input("단가", value=float(lt['Close']), key=f"up_{tkr}")
            u_s = c_s.number_input("수량", value=1.0, format="%.4f", key=f"us_{tkr}")
            b_a, b_s = st.columns(2)
            if b_a.button("➕ 수기 매수", use_container_width=True, key=f"ba_{tkr}"):
                pos['History'].append({'type': 'Buy', 'price': u_p, 'shares': u_s})
                log_trade(tkr, 'Buy', u_p, u_s)
                st.rerun()
            if b_s.button("➖ 수기 매도", use_container_width=True, key=f"bs_{tkr}"):
                pos['History'].append({'type': 'Sell', 'price': u_p, 'shares': u_s})
                log_trade(tkr, 'Sell', u_p, u_s, (u_p - avg_e) * u_s)
                st.rerun()

    save_data(st.session_state.positions, st.session_state.global_ledger)

# --- 일지 탭 ---
with tabs[2]:
    krw_profit = sum(i.get('realized_profit', 0) for i in st.session_state.global_ledger) * exchange_rate
    st.metric("누적 수익금", f"₩{krw_profit:,.0f}")
    if st.session_state.global_ledger:
        st.dataframe(pd.DataFrame(st.session_state.global_ledger).iloc[::-1], use_container_width=True)

