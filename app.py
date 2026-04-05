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

# 시스템에 따라 한글 요일이 깨질 수 있으므로 예외 처리
try:
    locale.setlocale(locale.LC_TIME, 'ko_KR.UTF-8')
except:
    pass

# ==========================================
# 1. 설정 및 리스크 파라미터
# ==========================================
DB_FILE = 'internal_memory.csv'
MAX_TOTAL_UNITS = 10

STRATEGY_CONFIG = {
    "🚀 터틀-상승": {"risk_pct": 1.0, "max_unit_per_stock": 2},
    "📈 20일-눌림목": {"risk_pct": 2.5, "max_unit_per_stock": 2},
    "📉 BB-낙폭과대": {"risk_pct": 1.5, "max_unit_per_stock": 2}
}

strategy_desc = {
    "🚀 터틀-상승": "20일 고점 돌파 및 200일선 위에서 강한 상승 추세를 타는 종목입니다. (SPY 강세장 전용)",
    "📈 20일-눌림목": "우상향 중인 우량주가 건강한 조정을 받고 RSI 40에서 턴어라운드 합니다. (1, 2차 분할 권장)",
    "📉 BB-낙폭과대": "단기 이격도 과다 및 RSI 35 이하 극단적 공포에서 턴어라운드 합니다. (1, 2차 분할 권장)"
}

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
# 2. 데이터 다운로드 로직 (유지)
# ==========================================
def safe_download_single(ticker_symbol, period="1y", retries=3):
    for attempt in range(retries):
        try:
            tkr = yf.Ticker(ticker_symbol)
            df = tkr.history(period=period)
            if len(df) > 20:
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index)
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                return df
        except Exception:
            pass
        
        try:
            df = yf.download(ticker_symbol, period=period, progress=False, timeout=15)
            if len(df) > 20:
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                return df
        except Exception:
            pass
        time.sleep(1.5 ** attempt)
    return None

@st.cache_data(ttl=1800, show_spinner=False)
def bulk_download_all():
    chunks = [TICKERS[i:i+50] for i in range(0, len(TICKERS), 50)]
    all_data = {}
    pb = st.progress(0, text="📥 야후 파이낸스 대량 데이터 수집 중...")

    for idx, chunk in enumerate(chunks):
        chunk_ok = False
        try:
            data = yf.download(
                chunk, period="1y", progress=False,
                timeout=25, threads=True, repair=True,
                group_by='ticker'
            )
            if isinstance(data.columns, pd.MultiIndex):
                for ticker in chunk:
                    try:
                        if ticker in data.columns.get_level_values(0):
                            df = data[ticker].dropna(how='all')
                            if len(df) > 20:
                                all_data[ticker] = df
                                chunk_ok = True
                    except Exception:
                        pass
            else:
                if len(data) > 20 and len(chunk) == 1:
                    all_data[chunk[0]] = data.dropna(how='all')
                    chunk_ok = True
        except Exception:
            chunk_ok = False

        if not chunk_ok:
            for ticker in chunk:
                try:
                    df = safe_download_single(ticker)
                    if df is not None:
                        all_data[ticker] = df
                except Exception:
                    pass
                time.sleep(0.3)

        pb.progress((idx + 1) / len(chunks))
        time.sleep(1.5)

    pb.empty()
    return all_data

# ==========================================
# 3. 데이터 기록 함수
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
                'Strategy': row.get('Strategy', '🚀 터틀-상승')
            }
    return positions, global_ledger

def save_data(positions, global_ledger):
    rows = [{'Ticker': k, 'Units': v.get('Units', 1), 'Highest': v['Highest'],
             'History': json.dumps(v.get('History', [])),
             'Strategy': v.get('Strategy', '🚀 터틀-상승')}
            for k, v in positions.items()]
    rows.append({'Ticker': '_GLOBAL_LEDGER_', 'Units': 0, 'Highest': 0.0,
                 'History': json.dumps(global_ledger), 'Strategy': 'SYSTEM'})
    pd.DataFrame(rows).to_csv(DB_FILE, index=False)

def log_trade(tkr, trade_type, price, shares, profit=0.0):
    st.session_state.global_ledger.append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ticker': tkr, 'type': trade_type, 'price': float(price),
        'shares': float(shares), 'realized_profit': float(profit)
    })
    save_data(st.session_state.positions, st.session_state.global_ledger)

# ==========================================
# 4. 분석 엔진 (다이내믹 지표 추가)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def check_market_filter():
    try:
        spy = safe_download_single("SPY", period="1y")
        if spy is None or len(spy) < 20:
            return True, 0.0, 0.0, False, "데이터 수집 실패"

        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)

        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_spy = float(spy['Close'].iloc[-1])
        ma200_now = float(spy['MA200'].iloc[-1])
        is_trending_up = all(
            spy['MA200'].tail(6).iloc[i] > spy['MA200'].tail(6).iloc[i - 1]
            for i in range(1, 6)
        )
        last_date_str = spy.index[-1].strftime('%Y-%m-%d (%A)')
        return (curr_spy > ma200_now), curr_spy, ma200_now, is_trending_up, last_date_str

    except Exception as e:
        return True, 0.0, 0.0, False, f"오류: {str(e)[:40]}"

def compute_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(lambda x: max(
        x['High'] - x['Low'],
        abs(x['High'] - x['prev_close']) if pd.notna(x['prev_close']) else 0,
        abs(x['Low'] - x['prev_close']) if pd.notna(x['prev_close']) else 0), axis=1)
    df['N'] = df['TR'].rolling(20).mean()

    df['High20'] = df['High'].rolling(20).max().shift(1)
    
    # 이평선 추가 (60일선 분할매수용)
    df['MA200'] = df['Close'].rolling(200).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    df['MA20'] = df['Close'].rolling(20).mean()

    # 볼린저 밴드
    df['MA18'] = df['Close'].rolling(18).mean()
    df['Std18'] = df['Close'].rolling(18).std()
    df['BB_Lower_18'] = df['MA18'] - (df['Std18'] * 2)

    # RSI (14일) 및 전일 RSI (턴어라운드 확인용)
    delta = df['Close'].diff()
    avg_gain = delta.where(delta > 0, 0).ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = -delta.where(delta < 0, 0).ewm(alpha=1 / 14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / (avg_loss + 1e-9))))
    df['RSI_Prev'] = df['RSI'].shift(1)

    # MACD (12, 26, 9) 및 전일 히스토그램 (모멘텀 전환 확인용)
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    df['MACD_Hist_Prev'] = df['MACD_Hist'].shift(1)

    df = df.drop(columns=['prev_close']) if 'prev_close' in df.columns else df
    return df

def analyze_ticker_from_bulk(ticker, all_data):
    if ticker not in all_data: return None
    df = all_data[ticker].copy()
    if len(df) < 60: return None
    return compute_indicators(df)

@st.cache_data(ttl=1800, show_spinner=False)
def analyze_ticker(ticker):
    df = safe_download_single(ticker)
    if df is None or len(df) < 60: return None
    return compute_indicators(df)

# ==========================================
# 5. 매니저 공통 함수
# ==========================================
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
    if lt['Close'] > pos['Highest']:
        pos['Highest'] = lt['Close']
    return pos, avg_e, total_s, lt

# ==========================================
# 6. 메인 UI
# ==========================================
st.set_page_config(page_title="Turtle Pro V7.70 (Dynamic Edition)", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions, st.session_state.global_ledger = load_data()

st.sidebar.header("⚙️ 시스템 설정")
if st.sidebar.button("♻️ 데이터 캐시 강제 초기화", type="primary"):
    st.cache_data.clear()
    st.sidebar.success("✅ 캐시가 삭제되었습니다.")
st.sidebar.markdown("---")

total_capital = int(st.sidebar.number_input("시드머니 (만원)", value=200, step=50) * 10000)
exchange_rate = st.sidebar.number_input("현재환율 (₩/$)", value=1450, step=10)
st.sidebar.info(f"💡 **현재 유니버스:**\n총 **{len(TICKERS)}개** 종목 무필터 스캔 중.")

st.title("🐢 Turtle System Pro V7.70")
st.caption("✅ 1/2차 분할 매수 및 다이내믹 익절 엔진 탑재 완료")

is_bull, spy_val, ma200_val, is_trending, last_date = check_market_filter()
st.caption(f"📅 **데이터 기준일:** {last_date}")

if is_bull:
    st.success(f"🟢 시장 통과 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | {'📈 상승 추세' if is_trending else '➡️ 횡보'}")
else:
    st.error(f"🔴 시장 경고 | SPY: ${spy_val:.2f} / MA200: ${ma200_val:.2f} | 📉 하락/역배열")

with st.expander("💡 현재 SPY 필터 맞춤 트레이딩 가이드", expanded=True):
    if is_bull and is_trending:
        st.markdown("#### 🌞 [강세장] 터틀 추세추종 유리\n- 스캐너가 **🚀 터틀-상승** 종목 위주로 추천합니다.")
    elif is_bull and not is_trending:
        st.markdown("#### ⛅ [횡보장] 눌림목 유리\n- 스캐너가 **📈 20일-눌림목** 종목 위주로 추천합니다.")
    else:
        st.markdown("#### ⛈️ [약세장] 낙폭과대 유리\n- 스캐너가 **📉 BB-낙폭과대** 패닉셀 종목 위주로 추천합니다.")

tabs = st.tabs(["🔎 스캐너", "📋 매니저", "🇺🇸 분석", "📊 일지"])

# ==========================================
# 7. 스캐너 탭 (통합 필터링)
# ==========================================
with tabs[0]:
    st.info("💡 **스마트 스캐너:** SPY 시장 상황을 분석하여 현재 가장 승률이 높은 타점의 종목만 추천합니다.")
    
    if st.button(f"🔎 스마트 스캔 실행 (총 {len(TICKERS)}개)", use_container_width=True):
        res = []
        all_data = bulk_download_all()

        if len(all_data) == 0:
            st.error("🚨 데이터를 불러오지 못했습니다. 캐시 초기화 후 다시 시도해주세요.")
            st.stop()

        pb = st.progress(0, text="종목 분석 및 타점 계산 중...")

        for idx, tkr in enumerate(TICKERS):
            pb.progress((idx + 1) / len(TICKERS))
            df = analyze_ticker_from_bulk(tkr, all_data)

            if df is not None:
                lt = df.iloc[-1]
                
                # 공통 턴어라운드 조건 (MACD 히스토그램이 어제보다 상승)
                macd_turnaround = lt['MACD_Hist'] > lt.get('MACD_Hist_Prev', 0)
                # 허들 완화된 RSI 조건
                rsi_pullback = (lt.get('RSI_Prev', 100) <= 40) and (lt['RSI'] > 40)
                rsi_oversold = (lt.get('RSI_Prev', 100) <= 35) and (lt['RSI'] > 35)
                
                cond = False
                rec_strategy = ""

                # 시장 상황(SPY)에 따른 맞춤 전략 자동 선택
                if is_bull and is_trending:
                    if (lt['Close'] > lt['High20']) and (lt['Close'] > lt.get('MA200', 0)) and (lt['MACD_Hist'] > 0):
                        cond, rec_strategy = True, "🚀 터틀-상승"
                elif is_bull and not is_trending:
                    if rsi_pullback and macd_turnaround and (lt['Close'] > lt.get('MA200', 0)):
                        cond, rec_strategy = True, "📈 20일-눌림목"
                else:
                    if rsi_oversold and macd_turnaround and (lt['Close'] <= lt.get('BB_Lower_18', 0)):
                        cond, rec_strategy = True, "📉 BB-낙폭과대"

                if cond:
                    cash_sh = (total_capital / 5) / (lt['Close'] * exchange_rate) # 5슬롯 집중투자 기준
                    final_sh = round(cash_sh / 2, 4) if "터틀" not in rec_strategy else round(cash_sh, 4) # 터틀은 100%, 나머진 1차(50%)만
                    
                    if final_sh >= 0.0001:
                        res.append({"tkr": tkr, "p": lt['Close'], "sh": final_sh, "st": rec_strategy})

        pb.empty()

        if not res:
            st.warning("📢 현재 시장 상황에 딱 맞는 추천 종목이 없습니다. 관망을 추천합니다.")
        else:
            st.success(f"🎯 총 {len(res)}개 맞춤 종목 포착!")

        for r in res:
            with st.container(border=True):
                l_col, r_col = st.columns([3, 1])
                sh_txt = "1차 매수(50%)" if "터틀" not in r['st'] else "전체 매수(100%)"
                l_col.write(f"### {r['tkr']} {r['st']}\n현재가: **${r['p']:.2f}** | 추천 수량: **{r['sh']:.4f}주** ({sh_txt})")
                
                if r_col.button("➕ 매니저 등록", key=f"reg_{r['tkr']}"):
                    st.session_state.positions[r['tkr']] = {
                        'Units': 1, 'Highest': r['p'],
                        'History': [{'type': 'Buy', 'price': r['p'], 'shares': r['sh']}],
                        'Strategy': r['st']
                    }
                    log_trade(r['tkr'], 'Buy', r['p'], r['sh'])
                    st.rerun()

# ==========================================
# 8. 매니저 탭 (다이내믹 관리)
# ==========================================
with tabs[1]:
    with st.expander("✍️ 수기 등록", expanded=False):
        mc1, mc2, mc3, mc4 = st.columns(4)
        m_t = mc1.text_input("티커").upper()
        m_s = mc2.selectbox("전략", ["🚀 터틀-상승", "📈 20일-눌림목", "📉 BB-낙폭과대"])
        m_p = mc3.number_input("진입가", value=0.0)
        m_h = mc4.number_input("수량", value=1.0, min_value=0.0001, format="%.4f")
        if st.button("➕ 수기 등록", use_container_width=True) and m_t:
            st.session_state.positions[m_t] = {
                'Units': 1, 'Highest': m_p,
                'History': [{'type': 'Buy', 'price': m_p, 'shares': m_h}],
                'Strategy': m_s
            }
            log_trade(m_t, 'Buy', m_p, m_h)
            st.rerun()

    for tkr, pos in list(st.session_state.positions.items()):
        df = analyze_ticker(tkr)
        if df is None: continue
        
        st_n = pos['Strategy']
        updated = update_position_state(tkr, pos, df)
        if updated is None:
            del st.session_state.positions[tkr]
            save_data(st.session_state.positions, st.session_state.global_ledger)
            st.rerun()
            continue

        pos, avg_e, total_s, lt = updated
        profit_pct = (lt['Close'] / avg_e - 1) * 100 if avg_e > 0 else 0.0

        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            h1.markdown(f"#### {tkr} :{'blue' if '터틀' in st_n else ('green' if '눌림목' in st_n else 'red')}[({st_n})] - {total_s:.4f}주")
            h1.caption(f"📊 **표준 지표** | RSI: **{lt.get('RSI', 0):.1f}** | MACD: **{lt.get('MACD', 0):.2f}**")
            
            if h2.button("전량 매도", key=f"ex_{tkr}"):
                del st.session_state.positions[tkr]
                log_trade(tkr, 'Sell (All)', lt['Close'], total_s, (lt['Close'] - avg_e) * total_s)
                st.rerun()

            curr_u = pos['Units']
            
            # --- 🛑 다이내믹 알림 엔진 ---
            is_macd_dead = lt.get('MACD_Hist', 0) < 0
            is_rsi_falling = (lt.get('RSI_Prev', 0) >= 70) and (lt.get('RSI', 0) < 70)
            
            if profit_pct > 0 and (is_macd_dead or is_rsi_falling):
                st.success(f"🔥 **다이내믹 익절 타이밍!** (추세 꺾임 포착) 👉 즉시 **전량 매도**하여 수익({profit_pct:.2f}%)을 확정하세요!")
            elif profit_pct <= -7.0:
                st.error(f"🛑 **비상 탈출 방어막 도달!** (-7% 손절선 붕괴) 👉 즉시 **전량 매도**하여 계좌를 방어하세요!")
            else:
                # 2차 추가매수 알림 (터틀 제외)
                if curr_u == 1 and "터틀" not in st_n:
                    scale_signal = False
                    if "눌림목" in st_n and (lt['Close'] <= lt.get('MA60', 0) * 1.02) and (lt.get('MACD_Hist', 0) > lt.get('MACD_Hist_Prev', 0)):
                        st.warning("💡 **2차 추가 매수 타점 포착!** (60일선 지지 + MACD 턴어라운드) 👉 남은 50% 비중을 추가 매수하세요.")
                        scale_signal = True
                    elif "낙폭과대" in st_n and (lt.get('RSI_Prev', 100) <= 35) and (lt.get('RSI', 0) > 35):
                        st.warning("💡 **2차 추가 매수 타점 포착!** (RSI 쌍바닥 확인) 👉 남은 50% 비중을 추가 매수하세요.")
                        scale_signal = True
                    
                    if not scale_signal:
                        st.info(f"✅ 1차 진입 완료. 순항 중 (수익률: {profit_pct:.2f}%) | 2차 타점 또는 익절 대기 중")
                else:
                    st.info(f"✅ 비중 탑재 완료. 순항 중 (수익률: {profit_pct:.2f}%) | 다이내믹 익절 대기 중")

            # --- 📊 차트 그리기 ---
            lvls = [{'val': avg_e, 'name': '평단가', 'col': 'gray'}]
            lvls.append({'val': avg_e * 0.93, 'name': '비상탈출(-7%)', 'col': 'red'})
            if curr_u == 1 and "눌림목" in st_n:
                lvls.append({'val': lt.get('MA60'), 'name': '2차 타점(60일선)', 'col': 'orange'})
            lvls.append({'val': lt['Close'], 'name': '현재가', 'col': 'purple'})

            c_df = df.reset_index()[['Date', 'Close']].tail(60)
            chart = alt.layer(
                alt.Chart(c_df).mark_line(color='#1f77b4').encode(
                    x=alt.X('Date:T', title=None),
                    y=alt.Y('Close:Q', scale=alt.Scale(zero=False))
                ),
                *[alt.layer(
                    alt.Chart(pd.DataFrame({'y': [l['val']]})).mark_rule(strokeDash=[5, 5], color=l['col']).encode(y='y:Q'),
                    alt.Chart(pd.DataFrame({'Date': [c_df['Date'].max()], 'y': [l['val']], 't': [f"{l['name']}: ${l['val']:.2f}"]})).mark_text(
                        align='left', dx=5, dy=-4, color=l['col'], fontWeight='bold').encode(x='Date:T', y='y:Q', text='t:N')
                ) for l in lvls if not pd.isna(l['val'])]
            ).properties(height=320)
            st.altair_chart(chart, use_container_width=True)

            c_p, c_s = st.columns(2)
            u_p = c_p.number_input("단가", value=float(lt['Close']), key=f"up_{tkr}")
            u_s = c_s.number_input("수량", value=total_s if curr_u == 1 else 0.0, min_value=0.0000, format="%.4f", key=f"us_{tkr}")
            b_a, b_s, b_d = st.columns(3)

            if b_a.button("➕ 추가 매수", key=f"ba_{tkr}", use_container_width=True):
                pos['History'].append({'type': 'Buy', 'price': u_p, 'shares': u_s})
                log_trade(tkr, 'Buy', u_p, u_s)
                st.rerun()
            if b_s.button("➖ 부분 매도", key=f"bs_{tkr}", use_container_width=True):
                pos['History'].append({'type': 'Sell', 'price': u_p, 'shares': u_s})
                log_trade(tkr, 'Sell (Partial)', u_p, u_s, (u_p - avg_e) * u_s)
                st.rerun()
            if b_d.button("🔙 방금 거래 취소", key=f"bd_{tkr}", use_container_width=True):
                if pos['History']: pos['History'].pop()
                for idx in range(len(st.session_state.global_ledger) - 1, -1, -1):
                    if st.session_state.global_ledger[idx]['ticker'] == tkr:
                        st.session_state.global_ledger.pop(idx)
                        break
                save_data(st.session_state.positions, st.session_state.global_ledger)
                st.rerun()

    save_data(st.session_state.positions, st.session_state.global_ledger)

# ==========================================
# 9. 분석 / 일지 탭
# ==========================================
with tabs[2]:
    t_in = st.text_input("티커 분석 (예: AAPL)").strip().upper()
    if st.button("분석 실행") and t_in:
        with st.spinner(f"'{t_in}' 종목 데이터 수집 중..."):
            d = analyze_ticker(t_in)
            if d is not None:
                st.info(f"**[{t_in}]** 종가: **${d['Close'].iloc[-1]:.2f}** | RSI: **{d['RSI'].iloc[-1]:.1f}**")
                news = [{"title": e.title, "link": e.link} for e in feedparser.parse(f"https://news.google.com/rss/search?q={t_in}+stock&hl=en-US&gl=US&ceid=US:en").entries[:5]]
                for n in news: st.write(f"- [{n['title']}]({n['link']})")
            else:
                st.error("데이터를 불러올 수 없습니다.")

with tabs[3]:
    krw_profit = sum(i.get('realized_profit', 0) for i in st.session_state.global_ledger) * exchange_rate
    st.metric("누적 실현 수익금", f"₩{krw_profit:,.0f}")
    if st.session_state.global_ledger:
        st.dataframe(pd.DataFrame(st.session_state.global_ledger).iloc[::-1], use_container_width=True)

