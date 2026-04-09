import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader
import glob

# --- [Phase 0: 門禁系統] ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.set_page_config(page_title="🔒 登入驗證", layout="centered")
    st.warning("🔒 這是私人專屬的 AI 看盤系統，請輸入通關密碼。")
    with st.form("login_form"):
        pwd = st.text_input("請輸入密碼：", type="password")
        submit = st.form_submit_button("解鎖進入")
        if submit:
            correct_password = st.secrets.get("APP_PASSWORD", "admin")
            if pwd == correct_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤！")
    st.stop()

# --- [Phase 1: 環境與全局設定] ---
TODAY = datetime.now()
st.set_page_config(page_title="專業台美股 K 線探測器", layout="wide")

ticker_map = {
    "2330.TW": "台積電 (TSMC)",
    "2317.TW": "鴻海 (Foxconn)",
    "2454.TW": "聯發科 (MediaTek)",
    "3163.TWO": "波若威 (Browave)",
    "NVDA": "輝達 (NVIDIA)",
    "AAPL": "蘋果 (Apple)",
    "TSLA": "特斯拉 (Tesla)",
    "0050.TW": "元大台灣50",
}

# --- [Phase 2: 狀態管理 - 🌟 強化防彈邏輯] ---
if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = st.query_params.get("ticker", "2330.TW")

def update_from_select():
    # 使用 .get 避免 AttributeError
    selector_val = st.session_state.get("stock_selector")
    if selector_val:
        new_ticker = [k for k, v in ticker_map.items() if v == selector_val][0]
        st.session_state.active_ticker = new_ticker
        st.session_state["stock_text"] = "" # 強制同步清空

def update_from_text():
    # 🌟 關鍵修正：使用 .get 讀取，就算變數消失也不會崩潰
    text_val = st.session_state.get("stock_text", "")
    val = text_val.strip().upper()
    if val:
        st.session_state.active_ticker = val

st.sidebar.header("🕹️ 分析設定與工具")

current_ticker = st.session_state.active_ticker
default_idx = list(ticker_map.keys()).index(current_ticker) if current_ticker in ticker_map else 0

st.sidebar.selectbox("1. 選擇預設股票", options=list(ticker_map.values()), index=default_idx, key="stock_selector", on_change=update_from_select)
st.sidebar.text_input("2. 或直接輸入代號", key="stock_text", on_change=update_from_text, placeholder="例如: 2317.TW")

fm_token = st.sidebar.text_input("💎 FinMind Token (選填)", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
selected_ticker = st.session_state.active_ticker
st.query_params["ticker"] = selected_ticker

# --- [Phase 3: 資料函數] ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    data = yf.download(ticker, start=TODAY - timedelta(days=540), end=TODAY + timedelta(days=1))
    if data.empty: return data
    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
    data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
    return data

@st.cache_data(ttl=3600)
def get_institutional_data(ticker, token=""):
    if ".TWO" in ticker.upper(): return pd.DataFrame() 
    dl = DataLoader()
    if token: dl.login_by_token(api_token=token.strip())
    try:
        fm_df = dl.request_data(dataset='TaiwanStockInstitutionalInvestorsBuySell', stock_id=ticker.replace('.TW', ''),
                                start_date=(TODAY - timedelta(days=540)).strftime("%Y-%m-%d"),
                                end_date=(TODAY + timedelta(days=1)).strftime("%Y-%m-%d"))
        return fm_df if fm_df is not None else pd.DataFrame()
    except: return pd.DataFrame()

st.title(f"📊 {selected_ticker} 專業籌碼診斷儀表板")
st.markdown("---")

# --- [Phase 4: 主程式數據處理] ---
if selected_ticker:
    with st.spinner("正在讀取數據..."):
        df = get_stock_data(selected_ticker)
        inst_df = get_institutional_data(selected_ticker, token=fm_token)

    if not df.empty:
        # 均線計算
        for window in [5, 10, 20, 60, 120]:
            df[f'SMA_{window}'] = df['Close'].rolling(window=window).mean()
        
        foreign_df = pd.DataFrame(columns=['Foreign'])
        trust_df = pd.DataFrame(columns=['Trust'])

        # --- 🌟 上櫃股 (.TWO) 專用資料與縫合 ---
        if ".TWO" in selected_ticker.upper():
            csv_files = glob.glob("tpex_inst_[0-9]*.csv")
            if csv_files:
                latest_file = sorted(csv_files)[-1]
                t_df = pd.read_csv(latest_file)
                stock_id = selected_ticker.split('.')[0]
                target_data = t_df[t_df['代號'].astype(str) == stock_id]
                
                if not target_data.empty:
                    st.info(f"💡 最新交易日 ({latest_file[-12:-4]}) 數據已自動載入。")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("外資買賣超", f"{target_data.iloc[0]['外資買賣超']:,}")
                    c2.metric("投信買賣超", f"{target_data.iloc[0]['投信買賣超']:,}")
                    c3.metric("三大法人合計", f"{target_data.iloc[0]['三大法人買賣超']:,}")

                hist_list = []
                for f in csv_files:
                    try:
                        f_date = f[-12:-4]
                        f_df = pd.read_csv(f)
                        f_row = f_df[f_df['代號'].astype(str) == stock_id]
                        if not f_row.empty:
                            hist_list.append({'date': pd.to_datetime(f_date).strftime('%Y-%m-%d'),
                                              'Foreign': f_row.iloc[0]['外資買賣超'], 'Trust': f_row.iloc[0]['投信買賣超']})
                    except: pass
                if hist_list:
                    h_df = pd.DataFrame(hist_list).set_index('date')
                    foreign_df, trust_df = h_df[['Foreign']], h_df[['Trust']]

        # --- [2. 上市股 FinMind 處理] ---
        if ".TW" in selected_ticker.upper():
            if inst_df.empty:
                st.warning("⚠️ FinMind 未回傳資料，請點擊右上角 ⋮ -> Clear cache。")
            else:
                inst_df['date'] = pd.to_datetime(inst_df['date']).dt.strftime('%Y-%m-%d')
                f_mask = inst_df['name'].str.contains('Foreign_Investor|外資', na=False, regex=True)
                foreign_df = inst_df[f_mask].groupby('date')[['buy', 'sell']].sum()
                foreign_df['Foreign'] = foreign_df['buy'] - foreign_df['sell']
                t_mask = inst_df['name'].str.contains('Investment_Trust|投信', na=False, regex=True)
                trust_df = inst_df[t_mask].groupby('date')[['buy', 'sell']].sum()
                trust_df['Trust'] = trust_df['buy'] - trust_df['sell']

        # --- [3. 數據合併] ---
        df.index = pd.to_datetime(df.index).strftime('%Y-%m-%d')
        df = df.join(foreign_df[['Foreign']], how='left').fillna({'Foreign': 0})
        df = df.join(trust_df[['Trust']], how='left').fillna({'Trust': 0})

        # 指標計算
        df_plot = df.tail(252).copy()
        # MACD
        df_plot['EMA12'] = df_plot['Close'].ewm(span=12, adjust=False).mean()
        df_plot['EMA26'] = df_plot['Close'].ewm(span=26, adjust=False).mean()
        df_plot['MACD'] = df_plot['EMA12'] - df_plot['EMA26']
        df_plot['Signal'] = df_plot['MACD'].ewm(span=9, adjust=False).mean()
        df_plot['Hist'] = df_plot['MACD'] - df_plot['Signal']
        # KD
        m9, x9 = df_plot['Low'].rolling(9).min(), df_plot['High'].rolling(9).max()
        df_plot['RSV'] = (df_plot['Close'] - m9) / (x9 - m9) * 100
        df_plot['K'] = df_plot['RSV'].fillna(50).ewm(com=2, adjust=False).mean()
        df_plot['D'] = df_plot['K'].ewm(com=2, adjust=False).mean()

        col_chart, col_ctrl = st.columns([5, 1])
        with col_ctrl:
            st.subheader("工具箱")
            active_smas = [w for w in [5, 10, 20, 60, 120] if st.checkbox(f"{w}MA", value=w in [5, 20, 60])]
            ai_clicked = st.button("🚀 AI 趨勢診斷", use_container_width=True)
            try:
                p = df_plot['Close'].iloc[-1]; diff = p - df_plot['Close'].iloc[-2]
                st.markdown(f"<h2 style='color:{'red' if diff>=0 else 'green'};'>{p:,.2f}</h2>", unsafe_allow_html=True)
            except: pass

        # --- [Phase 6: 專業六層視覺畫布] ---
        with col_chart:
            fig = go.Figure()
            # 1. K線
            fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線", yaxis="y1", increasing_line_color='red', decreasing_line_color='green'))
            for w in active_smas:
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'SMA_{w}'], name=f'{w}MA', yaxis="y1"))
            # 2. 成交量
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], name="成交量", yaxis="y2", marker_color='rgba(128,128,128,0.2)'))
            # 3. 外資/投信
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Foreign'], name="外資", marker_color=np.where(df_plot['Foreign']>=0, 'red', 'green'), yaxis="y3"))
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Trust'], name="投信", marker_color=np.where(df_plot['Trust']>=0, 'red', 'green'), yaxis="y4"))
            # 4. MACD
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Hist'], name="MACD柱", marker_color=np.where(df_plot['Hist']>=0, 'red', 'green'), yaxis="y5"))
            # 5. KD
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K'], name="K", line=dict(color='orange'), yaxis="y6"))
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D'], name="D", line=dict(color='blue'), yaxis="y6"))

            fig.update_layout(
                height=1100, template="plotly_white", hovermode="x unified",
                xaxis=dict(type='category', dtick=20),
                yaxis1=dict(domain=[0.65, 1.0]), yaxis2=dict(domain=[0.53, 0.63]),
                yaxis3=dict(domain=[0.41, 0.51]), yaxis4=dict(domain=[0.29, 0.39]),
                yaxis5=dict(domain=[0.12, 0.27]), yaxis6=dict(domain=[0.0, 0.10]),
                showlegend=False
            )
            # 輔助線與標註
            for y_r in ["y3", "y4", "y5"]: fig.add_hline(y=0, line_dash="dot", yref=y_r)
            fig.add_annotation(text="價<br>格", x=0, xref="paper", y=0.8, yref="paper", showarrow=False)
            fig.add_annotation(text="外<br>資", x=0, xref="paper", y=0.45, yref="paper", showarrow=False)
            fig.add_annotation(text="投<br>信", x=0, xref="paper", y=0.35, yref="paper", showarrow=False)
            st.plotly_chart(fig, use_container_width=True)

        if ai_clicked:
            g_key = st.secrets.get("GEMINI_API_KEY")
            if g_key:
                genai.configure(api_key=g_key)
                model = genai.GenerativeModel('gemini-2.0-flash')
                resp = model.generate_content(f"分析股票 {selected_ticker}，收盤 {p:,.2f}。請給出投資建議。")
                st.info(resp.text)