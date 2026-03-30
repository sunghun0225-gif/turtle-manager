import streamlit as st
import yfinance as yf
import pandas as pd
import os
import time
import requests

# --- 위키백과 스크래핑 차단 방지용 SSL 우회 ---
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 기본 설정 및 데이터 로드 함수
# ==========================================
DB_FILE = 'portfolio_v4.csv'
MAX_TOTAL_UNITS = 10       # 계좌 전체 최대 Unit 한도
MAX_UNIT_PER_STOCK = 3     # 단일 종목 최대 Unit 한도 (밸런스형)

@st.cache_data(ttl=86400) # 하루 한 번만 위키백과에서 리스트를 갱신합니다.
def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        # 💡 봇(Bot) 차단을 막기 위해 평범한 크롬 브라우저인 것처럼 신분증(User-Agent) 위장
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        html = requests.get(url, headers=headers).text
        table = pd.read_html(html)[0]
        tickers = table['Symbol'].tolist()
        # 야후 파이낸스 형식에 맞게 특수기호 변환 (예: BRK.B -> BRK-B)
        return [ticker.replace('.', '-') for ticker in tickers]
    except Exception as e:
        # 스크래핑 실패 시 빨간 에러 메시지를 띄우고 비상용 우량주 리스트 반환
        st.error(f"⚠️ S&P 500 리스트 로드 실패. 비상용 10종목으로 대체합니다. (사유: {e})")
        return ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B', 'JNJ', 'JPM']

TICKERS = get_sp500_tickers()

def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE).set_index('Ticker').to_dict('index')
    return {}

def save_data(positions):
    if positions:
        df = pd.DataFrame.from_dict(positions, orient='index').reset_index()
        df.rename(columns={'index': 'Ticker'}, inplace=True)
        df.to_csv(DB_FILE, index=False)
    else:
        if os.path.exists(DB_FILE): os.remove(DB_FILE)

# ==========================================
# 2. 분석 엔진 (시장 필터 및 종목 지표)
# ==========================================
@st.cache_data(ttl=3600)
def check_market_filter():
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy['MA200'] = spy['Close'].rolling(200).mean()
        return spy['Close'].iloc[-1] > spy['MA200'].iloc[-1]
    except: return True

@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="6mo")
        if len(df) < 60: return None
        
        # N(ATR 20), 55일 고점, 20일 저점 계산
        df['TR'] = df[['High', 'Low', 'Close']].apply(
            lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) 
            if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1
        )
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        
        return df # 차트 그리기를 위해 데이터프레임 전체 반환
    except: return None

# ==========================================
# 3. 앱 UI 및 메인 로직
# ==========================================
st.set_page_config(page_title="Turtle System V4", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions = load_data()

# --- 사이드바 ---
st.sidebar.header("⚙️ 리스크 설정")
total_capital = st.sidebar.number_input("운용 시드머니 (₩)", min_value=1000000, value=2000000, step=500000)
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 감수율 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", min_value=1000, value=1350, step=10)

st.sidebar.caption(f"💡 1회 매수 시 감수 위험액: ₩ {int(total_capital * risk_per_unit):,}")

st.title("🐢 Turtle System V4")

# --- 시장 필터 및 계좌 위험도 ---
is_bull_market = check_market_filter()
if is_bull_market: 
    st.success("🟢 **시장 필터 통과 (대세 상승장)** | SPY가 200일선 위에 있어 신규 진입이 가능합니다.")
else: 
    st.error("🔴 **시장 필터 경고 (대세 하락장)** | SPY가 200일선 아래에 있습니다. 신규 진입을 멈추세요.")

current_total_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
col_u1, col_u2 = st.columns(2)
col_u1.metric("사용 중인 Total Units", f"{current_total_units} / {MAX_TOTAL_UNITS} U")
col_u2.metric("현재 계좌 위험도", f"{current_total_units * (risk_per_unit * 100):.1f}%")

st.divider()

# --- 탭 구성 ---
tab1, tab2 = st.tabs(["🔭 1. S&P 500 돌파 스캐너", "📋 2. 포지션 관리 및 차트"])

# ------------------------------------------
# 탭 1: 스캐너 로직
# ------------------------------------------
with tab1:
    st.subheader("🔍 55일 신고가 돌파 종목 찾기")
    st.write(f"S&P 500 전체 종목({len(TICKERS)}개)을 스캔합니다. (약 1~2분 소요)")
    
    if st.button("🚀 스캐너 작동", type="primary"):
        if not is_bull_market:
            st.warning("현재 하락장입니다. 스캐너 결과가 나오더라도 매수는 권장하지 않습니다.")
            
        my_bar = st.progress(0, text="종목 데이터 분석을 시작합니다...")
        found_stocks = []
        
        for i, tkr in enumerate(TICKERS):
            my_bar.progress((i + 1) / len(TICKERS), text=f"[{i+1}/{len(TICKERS)}] {tkr} 분석 중...")
            
            data = analyze_ticker(tkr)
            if data is not None:
                latest = data.iloc[-1]
                # 55일 신고가 돌파 확인
                if latest['Close'] > latest['High55']:
                    n_val = latest['N']
                    unit_shares = int((total_capital * risk_per_unit) / (n_val * exchange_rate)) if n_val > 0 else 0
                    
                    if unit_shares > 0:
                        found_stocks.append({
                            "Ticker": tkr, "Price": latest['Close'], "N": n_val, "Rec_Shares": unit_shares
                        })
        
        my_bar.empty()
        
        if found_stocks:
            st.success(f"🎉 **{len(found_stocks)}개의 돌파 종목을 발견했습니다!**")
            for stock in found_stocks:
                tkr = stock['Ticker']
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 2])
                    c1.markdown(f"### {tkr}")
                    c2.metric("현재가", f"${stock['Price']:.2f}")
                    c3.metric("권장 매수량", f"{stock['Rec_Shares']} 주")
                    
                    if tkr in st.session_state.positions:
                        st.info("✅ 이미 보유 중인 종목입니다.")
                    else:
                        if st.button(f"➕ 내 포지션에 등록", key=f"add_scan_{tkr}"):
                            if current_total_units >= MAX_TOTAL_UNITS:
                                st.error("계좌 총 Unit 한도(10 U) 초과로 등록할 수 없습니다.")
                            else:
                                st.session_state.positions[tkr] = {'EntryPrice': stock['Price'], 'Units': 1, 'Highest': stock['Price']}
                                save_data(st.session_state.positions)
                                st.rerun()
        else:
            st.info("💤 오늘은 55일 신고가를 돌파한 종목이 없습니다. 관망하세요.")

# ------------------------------------------
# 탭 2: 포지션 관리, 수동 등록 및 차트
# ------------------------------------------
with tab2:
    st.subheader("📋 내 보유 종목 현황")
    
    # --- 수동 등록 UI ---
    with st.expander("➕ 수동으로 내 보유 종목 등록하기"):
        with st.form("manual_add_form", clear_on_submit=True):
            new_tkr = st.text_input("종목 코드 (예: AAPL)").upper()
            new_price = st.number_input("나의 체결 평단가 ($)", min_value=0.0)
            new_units = st.number_input("현재 보유 Unit 수", min_value=1, max_value=3, value=1)
            
            if st.form_submit_button("포지션 수동 등록"):
                if current_total_units + new_units > MAX_TOTAL_UNITS:
                    st.error("총 Unit 한도(10 U)를 초과합니다!")
                elif new_tkr in st.session_state.positions:
                    st.warning("이미 등록된 종목입니다.")
                else:
                    st.session_state.positions[new_tkr] = {'EntryPrice': new_price, 'Units': new_units, 'Highest': new_price}
                    save_data(st.session_state.positions)
                    st.rerun()

    if not st.session_state.positions:
        st.info("보유 중인 종목이 없습니다. 스캐너를 돌리거나 수동으로 등록해 보세요.")
    else:
        for tkr, pos in list(st.session_state.positions.items()):
            data = analyze_ticker(tkr)
            if data is None: continue
            
            latest = data.iloc[-1]
            curr_price = latest['Close']
            n_val = latest['N']
            units = pos['Units']
            avg_entry = pos['EntryPrice']
            
            # 트레일링 스탑 최고점 갱신
            if curr_price > pos.get('Highest', avg_entry):
                st.session_state.positions[tkr]['Highest'] = curr_price
                save_data(st.session_state.positions)
            highest = pos.get('Highest', avg_entry)
            
            # 지표 계산
            stop_loss = avg_entry - (2 * n_val)
            trailing_stop = highest - (3 * n_val)
            exit_price = max(stop_loss, trailing_stop)
            donchian_exit = latest['Low20']
            next_add_price = avg_entry + (0.5 * n_val)

            # --- 카드 UI ---
            with st.container(border=True):
                c_title, c_del = st.columns([4, 1])
                c_title.markdown(f"#### **{tkr}** ({units} U)")
                if c_del.button("매매 종료", key=f"del_pos_{tkr}"):
                    del st.session_state.positions[tkr]
                    save_data(st.session_state.positions)
                    st.rerun()

                c1, c2, c3 = st.columns(3)
                c1.metric("현재가 ($)", f"{curr_price:.2f}")
                c2.metric("내 평단가 ($)", f"{avg_entry:.2f}")
                
                profit_pct = (curr_price / avg_entry) - 1
                c3.metric("수익률", f"{profit_pct:.2%}")

                # 🚨 행동 지침 (Action) 🚨
                if curr_price < exit_price or curr_price < donchian_exit:
                    st.error(f"🚨 **즉시 전량 매도 (손절/익절)** | 방어선(${max(exit_price, donchian_exit):.2f})이 깨졌습니다!")
                elif curr_price >= next_add_price and units < MAX_UNIT_PER_STOCK:
                    st.success(f"🔥 **불타기 찬스!** | 가격이 충분히 올랐습니다. 1 Unit 추가 매수를 권장합니다.")
                    
                    unit_shares = int((total_capital * risk_per_unit) / (n_val * exchange_rate)) if n_val > 0 else 0
                    if st.button(f"{unit_shares}주 추가 매수 반영", key=f"add_pos_{tkr}"):
                        if current_total_units >= MAX_TOTAL_UNITS:
                            st.error("총 Unit 한도 초과!")
                        else:
                            st.session_state.positions[tkr]['EntryPrice'] = ((avg_entry * units) + curr_price) / (units + 1)
                            st.session_state.positions[tkr]['Units'] += 1
                            save_data(st.session_state.positions)
                            st.rerun()
                else:
                    st.info(f"✅ **홀딩 (관망)** | 다음 불타기 목표가: ${next_add_price:.2f}")

                # 📈 6개월 채널 차트 시각화
                with st.expander("📈 터틀 채널 차트 확인 (6개월)"):
                    st.caption("파란선: 현재가 / 상단선: 55일 돌파 기준선 / 하단선: 20일 신저가 방어선")
                    # 차트에 그릴 핵심 데이터 3개만 추출
                    chart_data = data[['Close', 'High55', 'Low20']].copy()
                    st.line_chart(chart_data)
