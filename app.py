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
}

# --- [Phase 2: 狀態管理] ---
if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = st.query_params.get("ticker", "2330.TW")

def update_from_select():
    val = st.session_state.get("stock_selector")
    if val:
        st.session_state.active_ticker = [k for k, v in ticker_map.items() if v == val][0]
        st.session_state["stock_text"] = ""

def update_from_text():
    text_val = st.session_state.get("stock_text", "")
    if text_val:
        st.session_state.active_ticker = text_val.strip().upper()

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
    data = yf.download(ticker, start=TODAY - timedelta(days=360), end=TODAY + timedelta(days=1))
    if data.empty: return data
    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
    # 強制格式化索引為字串 YYYY-MM-DD
    data.index = pd.to_datetime(data.index).strftime('%Y-%m-%d')
    return data

@st.cache_data(ttl=3600)
def get_institutional_data(ticker, token=""):
    if ".TWO" in ticker.upper(): return pd.DataFrame() 
    dl = DataLoader()
    if token: dl.login_by_token(api_token=token.strip())
    try:
        fm_df = dl.request_data(dataset='TaiwanStockInstitutionalInvestorsBuySell', stock_id=ticker.replace('.TW', ''),
                                start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d"))
        return fm_df if fm_df is not None else pd.DataFrame()
    except: return pd.DataFrame()

# --- [Phase 4: 主程式數據處理] ---
if selected_ticker:
    st.title(f"📊 {selected_ticker} 專業籌碼診斷儀表板")
    st.markdown("---")
    
    with st.spinner("數據雷達掃描中..."):
        df = get_stock_data(selected_ticker)
        inst_df = get_institutional_data(selected_ticker, token=fm_token)

    if not df.empty:
        # 技術指標計算
        for window in [5, 10, 20, 60, 120]:
            df[f'SMA_{window}'] = df['Close'].rolling(window=window).mean()
        
        # 建立空的法人容器
        df['Foreign'] = 0.0
        df['Trust'] = 0.0

        # --- 🌟 引擎 A：上櫃股 (.TWO) CSV 縫合 ---
        if ".TWO" in selected_ticker.upper():
            csv_files = glob.glob("tpex_inst_[0-9]*.csv")
            if csv_files:
                latest_f = sorted(csv_files)[-1]
                st.info(f"💡 上櫃籌碼已從本地資料庫載入 (最新日期: {latest_f[-12:-4]})")
                
                # 歷史數據對齊
                for f in csv_files:
                    date_str = f[-12:-4]
                    fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    if fmt_date in df.index:
                        t_df = pd.read_csv(f)
                        row = t_df[t_df['代號'].astype(str) == selected_ticker.split('.')[0]]
                        if not row.empty:
                            df.at[fmt_date, 'Foreign'] = float(row.iloc[0]['外資買賣超'])
                            df.at[fmt_date, 'Trust'] = float(row.iloc[0]['投信買賣超'])
                
                # Metric 顯示
                t_df_latest = pd.read_csv(latest_f)
                latest_row = t_df_latest[t_df_latest['代號'].astype(str) == selected_ticker.split('.')[0]]
                if not latest_row.empty:
                    st.markdown(f"### 🎯 最新交易日法人動向")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("外資買賣超", f"{latest_row.iloc[0]['外資買賣超']:,}")
                    c2.metric("投信買賣超", f"{latest_row.iloc[0]['投信買賣超']:,}")
                    c3.metric("三大法人合計", f"{latest_row.iloc[0]['三大法人買賣超']:,}")
                    st.divider()

        # --- 🌟 引擎 B：上市股 (.TW) FinMind 處理 ---
        if ".TW" in selected_ticker.upper():
            if inst_df.empty:
                st.warning("⚠️ FinMind 未回傳資料，請點擊右上角 ⋮ -> Clear cache。")
            else:
                inst_df['date'] = pd.to_datetime(inst_df['date']).dt.strftime('%Y-%m-%d')
                for _, row in inst_df.iterrows():
                    d = row['date']
                    if d in df.index:
                        if '外資' in row['name'] or 'Foreign' in row['name']:
                            df.at[d, 'Foreign'] += (row['buy'] - row['sell'])
                        if '投信' in row['name'] or 'Trust' in row['name']:
                            df.at[d, 'Trust'] += (row['buy'] - row['sell'])

        # 準備繪圖數據
        df_plot = df.tail(200).copy()
        
        # 指標計算 (MACD/KD)
        df_plot['EMA12'] = df_plot['Close'].ewm(span=12).mean()
        df_plot['EMA26'] = df_plot['Close'].ewm(span=26).mean()
        df_plot['MACD'] = df_plot['EMA12'] - df_plot['EMA26']
        df_plot['Signal'] = df_plot['MACD'].ewm(span=9).mean()
        df_plot['Hist'] = df_plot['MACD'] - df_plot['Signal']
        m9, x9 = df_plot['Low'].rolling(9).min(), df_plot['High'].rolling(9).max()
        df_plot['RSV'] = (df_plot['Close'] - m9) / (x9 - m9) * 100
        df_plot['K'] = df_plot['RSV'].fillna(50).ewm(com=2).mean()
        df_plot['D'] = df_plot['K'].ewm(com=2).mean()

        col_chart, col_ctrl = st.columns([5, 1])

        # --- [Phase 5: 工具面版] ---
        with col_ctrl:
            st.subheader("分析工具箱")
            active_smas = [w for w in [5, 10, 20, 60, 120] if st.checkbox(f"{w}日線", value=w in [5, 20, 60])]
            show_limit_up = st.checkbox("標示漲停 (10%)", value=True)
            ai_clicked = st.button("🚀 啟動 AI 趨勢診斷", use_container_width=True)
            try:
                p = df_plot['Close'].iloc[-1]; diff = p - df_plot['Close'].iloc[-2]
                st.markdown(f"<h2 style='color:{'red' if diff>=0 else 'green'};'>{p:,.2f}</h2>", unsafe_allow_html=True)
            except: pass

        # --- [Phase 6: 專業六層垂直畫布] ---
        with col_chart:
            fig = go.Figure()
            # 1. K線
            fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線", yaxis="y1", increasing_line_color='red', decreasing_line_color='green'))
            sma_colors = {5: "#FFC107", 10: "#E91E63", 20: "#2196F3", 60: "#4CAF50", 120: "#FF5722"}
            for w in active_smas:
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'SMA_{w}'], name=f'{w}MA', line=dict(color=sma_colors[w], width=1.5), yaxis="y1"))
            
            # 漲停星星
            if show_limit_up:
                limit_up_df = df_plot[df_plot['Close'] >= (df_plot['Close'].shift(1) * 1.097)]
                if not limit_up_df.empty:
                    fig.add_trace(go.Scatter(x=limit_up_df.index, y=limit_up_df['High'] * 1.03, mode='markers', name='漲停', marker=dict(symbol='star', size=12, color='gold', line=dict(width=1, color='red')), yaxis="y1"))

            # 2. 成交量
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], name="成交量", marker_color='gray', opacity=0.3, yaxis="y2"))
            
            # 3. 法人
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Foreign'], name="外資", marker_color=np.where(df_plot['Foreign']>=0, 'red', 'green'), yaxis="y3"))
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Trust'], name="投信", marker_color=np.where(df_plot['Trust']>=0, 'red', 'green'), yaxis="y4"))
            
            # 4. 指標
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Hist'], name="MACD柱", marker_color=np.where(df_plot['Hist']>=0, 'red', 'green'), yaxis="y5"))
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
            for y_r in ["y3", "y4", "y5"]: fig.add_hline(y=0, line_dash="dot", yref=y_r)
            fig.add_annotation(text="價<br>格", x=0, xref="paper", y=0.8, yref="paper", showarrow=False)
            fig.add_annotation(text="外<br>資", x=0, xref="paper", y=0.45, yref="paper", showarrow=False)
            fig.add_annotation(text="投<br>信", x=0, xref="paper", y=0.35, yref="paper", showarrow=False)

            st.plotly_chart(fig, use_container_width=True)

        # AI 診斷
        if ai_clicked:
            g_key = st.secrets.get("GEMINI_API_KEY")
            if g_key:
                genai.configure(api_key=g_key)
                model = genai.GenerativeModel('gemini-2.0-flash')
                resp = model.generate_content(f"分析股票 {selected_ticker}。收盤 {p:,.2f}。")
                st.info(resp.text)