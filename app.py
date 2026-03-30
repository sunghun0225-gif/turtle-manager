import streamlit as st
import yfinance as yf
import pandas as pd
import os

# --- 1. 설정 및 데이터 관리 ---
DB_FILE = 'portfolio_v2.csv'
MAX_TOTAL_UNITS = 10  # 계좌 전체 최대 Unit 한도
MAX_UNIT_PER_STOCK = 3 # 단일 종목 최대 Unit 한도

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

# --- 2. 시장 필터(SPY) 확인 함수 ---
@st.cache_data(ttl=3600) # 1시간 동안 결과 캐싱 (속도 향상)
def check_market_filter():
    try:
        spy = yf.Ticker("SPY").history(period="1y")
        spy['MA200'] = spy['Close'].rolling(200).mean()
        curr_close = spy['Close'].iloc[-1]
        ma200 = spy['MA200'].iloc[-1]
        return curr_close > ma200, curr_close, ma200
    except:
        return True, 0, 0 # 에러 시 기본적으로 매매 허용

# --- 3. 개별 종목 분석 함수 ---
@st.cache_data(ttl=3600)
def analyze_ticker(ticker):
    try:
        df = yf.Ticker(ticker).history(period="1y")
        if len(df) < 60: return None
        
        # N(ATR 20), 55일 고점, 20일 저점 계산
        df['TR'] = df[['High', 'Low', 'Close']].apply(
            lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) 
            if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1
        )
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        
        return df.iloc[-1] # 가장 최근(오늘 아침) 데이터 반환
    except:
        return None

# ==========================================
# 🖥️ 앱 UI 시작
# ==========================================
st.set_page_config(page_title="Turtle Manager Pro", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions = load_data()

# --- 사이드바: 자금 및 리스크 설정 ---
st.sidebar.header("⚙️ 리스크 설정")
total_capital = st.sidebar.number_input("운용 시드머니 (₩)", min_value=1000000, value=2000000, step=500000)
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 감수율 (%)", 1.0, 5.0, 2.0, 0.5) / 100

st.sidebar.caption(f"💡 1회 매매 시 감수 위험액: ₩ {int(total_capital * risk_per_unit):,}")

# --- 메인 대시보드: 리스크 신호등 ---
st.title("🐢 Turtle Manager Pro")

# 1. 시장 필터 상태
is_bull_market, spy_price, spy_ma200 = check_market_filter()
if is_bull_market:
    st.success(f"🟢 **시장 필터 통과 (대세 상승장)** | SPY가 200일선 위에 있습니다. (신규 진입 가능)")
else:
    st.error(f"🔴 **시장 필터 경고 (대세 하락장)** | SPY가 200일선 아래에 있습니다! **신규 진입을 멈추고 현금을 보호하세요.**")

# 2. 계좌 리스크 한도 현황
current_total_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
current_risk_pct = current_total_units * (risk_per_unit * 100)
max_risk_pct = MAX_TOTAL_UNITS * (risk_per_unit * 100)

col1, col2 = st.columns(2)
col1.metric("사용 중인 Total Units", f"{current_total_units} / {MAX_TOTAL_UNITS} U")
col2.metric("현재 계좌 위험도 (Risk)", f"{current_risk_pct:.1f}%", f"한도: {max_risk_pct:.1f}%", delta_color="off")

if current_total_units >= MAX_TOTAL_UNITS:
    st.warning("⚠️ **총 Unit 한도 초과!** 새로운 종목을 매수하거나 불타기를 할 수 없습니다.")

st.divider()

# --- 포지션 신규 등록 ---
with st.expander("➕ 새로운 매수 신호(55일 신고가) 등록"):
    with st.form("add_form", clear_on_submit=True):
        new_tkr = st.text_input("종목 코드 (Ticker)").upper()
        new_price = st.number_input("진입 체결가 ($)", min_value=0.0)
        
        submitted = st.form_submit_button("1 Unit 매수 등록")
        if submitted and new_tkr:
            if not is_bull_market:
                st.error("하락장입니다! SPY 필터에 의해 신규 진입이 차단되었습니다.")
            elif current_total_units >= MAX_TOTAL_UNITS:
                st.error("계좌의 총 Unit 한도(10 U)가 꽉 찼습니다!")
            elif new_tkr in st.session_state.positions:
                st.warning("이미 보유 중인 종목입니다. 아래 관리 카드에서 '불타기'를 이용하세요.")
            else:
                st.session_state.positions[new_tkr] = {'EntryPrice': new_price, 'Units': 1, 'Highest': new_price}
                save_data(st.session_state.positions)
                st.rerun()

# --- 보유 종목 관리 (오늘의 Action) ---
st.subheader("📋 포지션 관리 및 오늘의 행동 지침")

if not st.session_state.positions:
    st.info("현재 보유 중인 종목이 없습니다. 스캐너에서 55일 신고가 종목을 찾아 등록하세요.")
else:
    for tkr, pos in list(st.session_state.positions.items()):
        data = analyze_ticker(tkr)
        if data is None: continue
        
        curr_price = data['Close']
        n_val = data['N']
        units = pos['Units']
        avg_entry = pos['EntryPrice']
        
        # 트레일링 스탑을 위한 최고점 업데이트
        if curr_price > pos.get('Highest', avg_entry):
            st.session_state.positions[tkr]['Highest'] = curr_price
            save_data(st.session_state.positions)
            
        highest = pos.get('Highest', avg_entry)

        # 1 Unit 권장 주식 수 계산 (환율 1350원 가정)
        unit_shares = int((total_capital * risk_per_unit) / (n_val * 1350)) if n_val > 0 else 0
        
        # 청산 조건 계산
        stop_loss = avg_entry - (2 * n_val)
        trailing_stop = highest - (3 * n_val)
        exit_price = max(stop_loss, trailing_stop)
        donchian_exit = data['Low20']
        
        # 피라미딩(불타기) 조건 계산
        next_add_price = avg_entry + (0.5 * n_val)

        # --- 상태 카드 UI ---
        with st.container(border=True):
            c_title, c_del = st.columns([4, 1])
            c_title.markdown(f"### **{tkr}** ({units} Unit 보유 중)")
            if c_del.button("종료(삭제)", key=f"del_{tkr}"):
                del st.session_state.positions[tkr]
                save_data(st.session_state.positions)
                st.rerun()

            c1, c2, c3 = st.columns(3)
            c1.metric("현재가 ($)", f"{curr_price:.2f}")
            c2.metric("내 평단가 ($)", f"{avg_entry:.2f}")
            c3.metric("1 Unit 권장량", f"{unit_shares} 주", f"N={n_val:.2f}")

            # 🚨 오늘 아침의 행동 지침 판별 🚨
            action_msg = "✅ **홀딩 (관망)**: 추세가 진행 중입니다."
            action_color = "normal"
            
            if curr_price < exit_price or curr_price < donchian_exit:
                action_msg = f"🚨 **즉시 전량 매도 (청산)**: 방어선(${max(exit_price, donchian_exit):.2f})이 깨졌습니다!"
                st.error(action_msg)
            elif curr_price >= next_add_price and units < MAX_UNIT_PER_STOCK:
                action_msg = f"🔥 **피라미딩 (불타기) 찬스!**: 가격이 충분히 올랐습니다. 1 Unit 추가 매수를 권장합니다."
                st.success(action_msg)
                
                # 불타기 버튼
                if st.button(f"1 Unit 추가 매수 반영 (현재가 ${curr_price:.2f})", key=f"add_{tkr}"):
                    if current_total_units >= MAX_TOTAL_UNITS:
                        st.error("총 Unit 한도 초과로 추가 매수할 수 없습니다.")
                    else:
                        # 평단가 재계산
                        new_avg = ((avg_entry * units) + curr_price) / (units + 1)
                        st.session_state.positions[tkr]['EntryPrice'] = new_avg
                        st.session_state.positions[tkr]['Units'] += 1
                        save_data(st.session_state.positions)
                        st.rerun()
            else:
                st.info(action_msg)
                
            with st.expander("세부 방어선 및 지표 확인"):
                st.write(f"- 1차 손절선 (-2N): **${stop_loss:.2f}**")
                st.write(f"- 트레일링 스탑 (-3N): **${trailing_stop:.2f}** (최고점 ${highest:.2f} 기준)")
                st.write(f"- 20일 저점 이탈선: **${donchian_exit:.2f}**")
                if units < MAX_UNIT_PER_STOCK:
                    st.write(f"- 다음 불타기 목표가 (+0.5N): **${next_add_price:.2f}**")
                else:
                    st.write(f"- 🛑 개별 종목 최대 Unit({MAX_UNIT_PER_STOCK} U) 도달. 더 이상 추가 매수 불가.")
