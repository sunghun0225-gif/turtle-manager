import streamlit as st
import yfinance as yf
import pandas as pd
import os
import time
import requests
import json
from datetime import datetime

# --- 위키백과 스크래핑 차단 방지용 SSL 우회 ---
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ==========================================
# 1. 기본 설정 및 데이터 로드
# ==========================================
DB_FILE = 'internal_memory.csv' # 내부 기억장치 파일명 단순화
MAX_TOTAL_UNITS = 10       
MAX_UNIT_PER_STOCK = 3     

@st.cache_data(ttl=86400) 
def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        html = requests.get(url, headers=headers).text
        table = pd.read_html(html)[0]
        tickers = table['Symbol'].tolist()
        return [ticker.replace('.', '-') for ticker in tickers]
    except Exception as e:
        st.error(f"⚠️ S&P 500 리스트 로드 실패. 비상용 10종목 대체. (사유: {e})")
        return ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B', 'JNJ', 'JPM']

TICKERS = get_sp500_tickers()

def load_data():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE)
        positions = {}
        for _, row in df.iterrows():
            history = json.loads(row['History']) if pd.notna(row['History']) else []
            positions[row['Ticker']] = {
                'Units': row['Units'],
                'Highest': row['Highest'],
                'History': history
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
                'History': json.dumps(data.get('History', []))
            })
        df = pd.DataFrame(rows)
        df.to_csv(DB_FILE, index=False)
    else:
        if os.path.exists(DB_FILE): os.remove(DB_FILE)

# ==========================================
# 2. 분석 엔진
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
        
        df['TR'] = df[['High', 'Low', 'Close']].apply(
            lambda x: max(x['High']-x['Low'], abs(x['High']-df['Close'].shift(1).loc[x.name]), abs(x['Low']-df['Close'].shift(1).loc[x.name])) 
            if pd.notna(df['Close'].shift(1).loc[x.name]) else x['High']-x['Low'], axis=1
        )
        df['N'] = df['TR'].rolling(20).mean()
        df['High55'] = df['High'].rolling(55).max().shift(1)
        df['Low20'] = df['Low'].rolling(20).min().shift(1)
        return df 
    except: return None

# ==========================================
# 3. 앱 UI 및 메인 로직
# ==========================================
st.set_page_config(page_title="Turtle System Pro", layout="centered", page_icon="🐢")

if "positions" not in st.session_state:
    st.session_state.positions = load_data()
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None 

# --- 사이드바 ---
st.sidebar.header("⚙️ 리스크 설정")
total_capital = st.sidebar.number_input("운용 시드머니 (₩)", min_value=1000000, value=2000000, step=500000)
risk_per_unit = st.sidebar.slider("1 Unit 당 위험 감수율 (%)", 1.0, 5.0, 2.0, 0.5) / 100
exchange_rate = st.sidebar.number_input("현재 환율 (₩/$)", min_value=1000, value=1350, step=10)
st.sidebar.caption(f"💡 1회 매수 시 감수 위험액: ₩ {int(total_capital * risk_per_unit):,}")

st.sidebar.divider()
st.sidebar.header("💾 데이터 복구 (업로드)")
st.sidebar.caption("서버 초기화 시 안드로이드 다운로드 폴더에 있는 백업 CSV를 올려주세요.")
uploaded_file = st.sidebar.file_uploader("백업 CSV 선택", type=['csv'])

if uploaded_file is not None:
    if st.sidebar.button("데이터 복구 실행", type="primary"):
        try:
            df = pd.read_csv(uploaded_file)
            restored = {}
            for _, row in df.iterrows():
                history = json.loads(row['History']) if pd.notna(row['History']) else []
                restored[row['Ticker']] = {'Units': row['Units'], 'Highest': row['Highest'], 'History': history}
            st.session_state.positions = restored
            save_data(st.session_state.positions)
            st.sidebar.success("✅ 매매 기록 복구 완료!")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.sidebar.error("❌ 복구 실패 (잘못된 파일 포맷)")

st.title("🐢 Turtle System Pro")

is_bull_market = check_market_filter()
if is_bull_market: st.success("🟢 **시장 필터 통과 (대세 상승장)** | 신규 진입 가능")
else: st.error("🔴 **시장 필터 경고 (대세 하락장)** | 신규 진입 중단 권장")

current_total_units = sum([pos['Units'] for pos in st.session_state.positions.values()])
col_u1, col_u2 = st.columns(2)
col_u1.metric("사용 중인 관리 유닛", f"{current_total_units} / {MAX_TOTAL_UNITS} U")
col_u2.metric("현재 계좌 위험도", f"{current_total_units * (risk_per_unit * 100):.1f}%")

st.divider()

tab1, tab2 = st.tabs(["🔭 1. S&P 500 돌파 스캐너", "📋 2. 포지션 관리 및 매매 기록"])

# ------------------------------------------
# 탭 1: 스캐너
# ------------------------------------------
with tab1:
    st.subheader("🔍 55일 신고가 돌파 종목 찾기")
    if st.button("🚀 스캐너 작동", type="primary"):
        if not is_bull_market: st.warning("하락장입니다. 매수는 권장하지 않습니다.")
            
        my_bar = st.progress(0, text="종목 데이터 분석을 시작합니다...")
        temp_results = []
        for i, tkr in enumerate(TICKERS):
            my_bar.progress((i + 1) / len(TICKERS), text=f"[{i+1}/{len(TICKERS)}] {tkr} 분석 중...")
            data = analyze_ticker(tkr)
            if data is not None:
                latest = data.iloc[-1]
                if latest['Close'] > latest['High55']:
                    n_val = latest['N']
                    unit_shares = int((total_capital * risk_per_unit) / (n_val * exchange_rate)) if n_val > 0 else 0
                    if unit_shares > 0:
                        temp_results.append({"Ticker": tkr, "Price": latest['Close'], "N": n_val, "Rec_Shares": unit_shares})
        
        my_bar.empty()
        st.session_state.scan_results = temp_results

    if st.session_state.scan_results is not None:
        if len(st.session_state.scan_results) > 0:
            st.success(f"🎉 **{len(st.session_state.scan_results)}개의 돌파 종목을 발견했습니다!**")
            for stock in st.session_state.scan_results:
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
                                st.error("총 Unit 한도를 초과했습니다.")
                            else:
                                st.session_state.positions[tkr] = {
                                    'Units': 1, 
                                    'Highest': stock['Price'],
                                    'History': [{'price': stock['Price'], 'shares': stock['Rec_Shares']}]
                                }
                                save_data(st.session_state.positions)
                                st.rerun() 
        else:
            st.info("💤 오늘은 55일 신고가를 돌파한 종목이 없습니다.")

# ------------------------------------------
# 탭 2: 포지션 관리, 수동 등록 및 세부 지표
# ------------------------------------------
with tab2:
    st.subheader("📋 내 보유 종목 현황")
    
    with st.expander("➕ 새로운 종목 수동으로 등록하기"):
        with st.form("manual_add_form", clear_on_submit=True):
            new_tkr = st.text_input("종목 코드 (예: AAPL)").upper()
            c_m1, c_m2 = st.columns(2)
            with c_m1:
                new_price = st.number_input("1회차 체결 평단가 ($)", min_value=0.0)
                new_shares = st.number_input("1회차 매수 수량 (주)", min_value=1, value=1)
            with c_m2:
                new_units = st.number_input("해당 종목 관리 유닛 (1~3 U)", min_value=1, max_value=3, value=1)
            
            if st.form_submit_button("신규 포지션 수동 등록"):
                if current_total_units + new_units > MAX_TOTAL_UNITS: st.error("총 Unit 한도를 초과합니다!")
                elif new_tkr in st.session_state.positions: st.warning("이미 등록된 종목입니다.")
                else:
                    st.session_state.positions[new_tkr] = {
                        'Units': new_units, 
                        'Highest': new_price,
                        'History': [{'price': new_price, 'shares': new_shares}]
                    }
                    save_data(st.session_state.positions)
                    st.rerun()

    if not st.session_state.positions:
        st.info("보유 중인 매매 기록이 없습니다.")
    else:
        for tkr, pos in list(st.session_state.positions.items()):
            data = analyze_ticker(tkr)
            if data is None: continue
            
            latest = data.iloc[-1]
            curr_price = latest['Close']
            n_val = latest['N']
            
            units = pos['Units']
            history = pos.get('History', [])
            
            total_shares = sum(h['shares'] for h in history)
            if total_shares == 0: continue 
            avg_entry = sum(h['price'] * h['shares'] for h in history) / total_shares
            
            if curr_price > pos.get('Highest', avg_entry):
                st.session_state.positions[tkr]['Highest'] = curr_price
                save_data(st.session_state.positions)
            highest = pos.get('Highest', avg_entry)
            
            stop_loss = avg_entry - (2 * n_val)
            trailing_stop = highest - (3 * n_val)
            exit_price = max(stop_loss, trailing_stop)
            donchian_exit = latest['Low20']
            next_add_price = avg_entry + (0.5 * n_val)

            with st.container(border=True):
                c_title, c_del = st.columns([4, 1])
                c_title.markdown(f"#### **{tkr}** (관리: {units} U / 총 보유: {total_shares}주)")
                if c_del.button("매매 종료", key=f"del_pos_{tkr}"):
                    del st.session_state.positions[tkr]
                    save_data(st.session_state.positions)
                    st.rerun()

                c1, c2, c3 = st.columns(3)
                c1.metric("현재가 ($)", f"{curr_price:.2f}")
                c2.metric("내 가중평단가 ($)", f"{avg_entry:.2f}")
                profit_pct = (curr_price / avg_entry) - 1
                c3.metric("수익률", f"{profit_pct:.2%}")

                if curr_price < exit_price or curr_price < donchian_exit:
                    st.error(f"🚨 **즉시 전량 매도 (청산)** | 가장 높은 방어선(${max(exit_price, donchian_exit):.2f})이 깨졌습니다.")
                elif curr_price >= next_add_price and units < MAX_UNIT_PER_STOCK:
                    st.success(f"🔥 **불타기 찬스!** | 목표가 도달. 1 Unit 추가 매수를 권장합니다.")
                    unit_shares = int((total_capital * risk_per_unit) / (n_val * exchange_rate)) if n_val > 0 else 0
                    if st.button(f"{unit_shares}주 자동 추가 매수 기록", key=f"add_pos_{tkr}"):
                        if current_total_units >= MAX_TOTAL_UNITS: st.error("총 Unit 한도 초과!")
                        else:
                            st.session_state.positions[tkr]['History'].append({'price': curr_price, 'shares': unit_shares})
                            st.session_state.positions[tkr]['Units'] += 1
                            save_data(st.session_state.positions)
                            st.rerun()
                else:
                    st.info("✅ **홀딩 (관망)** | 추세가 진행 중입니다.")

                with st.expander("📝 회차별 매수 내역 관리 (수동 입력)"):
                    if history:
                        df_history = pd.DataFrame(history)
                        df_history.index = [f"{i+1}회차" for i in range(len(history))]
                        df_history.columns = ['체결 단가 ($)', '매수 수량 (주)']
                        st.table(df_history.style.format({'체결 단가 ($)': '{:.2f}'}))
                    
                    st.markdown("---")
                    st.caption("새로운 분할 매수를 직접 진행했다면 아래에 추가하세요.")
                    with st.form(f"manual_round_add_{tkr}", clear_on_submit=True):
                        c_r1, c_r2 = st.columns(2)
                        with c_r1:
                            round_price = st.number_input("매수 단가 ($)", min_value=0.0, format="%.2f")
                        with c_r2:
                            round_shares = st.number_input("매수 수량 (주)", min_value=1, step=1)
                        
                        if st.form_submit_button("내역에 추가하기"):
                            st.session_state.positions[tkr]['History'].append({'price': round_price, 'shares': round_shares})
                            st.session_state.positions[tkr]['Units'] = min(MAX_UNIT_PER_STOCK, units + 1)
                            save_data(st.session_state.positions)
                            st.rerun()

                with st.expander("📊 터틀 세부 지표 및 차트 확인"):
                    st.markdown(f"**현재 변동성 (1N):** ${n_val:.2f}")
                    c_ind1, c_ind2 = st.columns(2)
                    with c_ind1:
                        st.caption("🔴 하방 방어선 (청산 마지노선)")
                        st.write(f"- 초기 방어선 (원금 손절): **${stop_loss:.2f}**")
                        st.write(f"- 고점 추적 익절선 (수익 보존): **${trailing_stop:.2f}** (최고점 ${highest:.2f} 기준)")
                        st.write(f"- 추세 붕괴 마지노선: **${donchian_exit:.2f}**")
                    with c_ind2:
                        st.caption("🟢 상방 공격선 (불타기)")
                        if units < MAX_UNIT_PER_STOCK:
                            st.write(f"- 다음 추가 매수 목표가: **${next_add_price:.2f}**")
                        else:
                            st.write("- 🛑 최대 보유 한도 도달 (매수 불가)")

                    st.caption("📈 6개월 터틀 채널 (파란선: 현재가 / 상단: 55일선 / 하단: 20일선)")
                    chart_data = data[['Close', 'High55', 'Low20']].copy()
                    st.line_chart(chart_data)

        # 💡 스마트폰 다운로드 폴더로 들어갈 YYMMDD_position.csv 파일 자동 생성
        st.divider()
        if st.session_state.positions:
            backup_rows = []
            for tkr, p_data in st.session_state.positions.items():
                backup_rows.append({
                    'Ticker': tkr,
                    'Units': p_data['Units'],
                    'Highest': p_data['Highest'],
                    'History': json.dumps(p_data.get('History', []))
                })
            
            csv_data = pd.DataFrame(backup_rows).to_csv(index=False).encode('utf-8-sig')
            
            today_str = datetime.now().strftime("%y%m%d")
            file_name = f"{today_str}_position.csv"
            
            st.download_button(
                label=f"💾 안드로이드 기기에 매매 기록 백업하기 ({file_name})", 
                data=csv_data, 
                file_name=file_name, 
                mime="text/csv",
                use_container_width=True
            )
