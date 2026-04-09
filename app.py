import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader
import glob

# --- [Phase 0: 門禁與初始設定] ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.set_page_config(page_title="🔒 登入驗證", layout="centered")
    with st.form("login_form"):
        pwd = st.text_input("請輸入密碼：", type="password")
        if st.form_submit_button("解鎖進入"):
            if pwd == st.secrets.get("APP_PASSWORD", "admin"):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤！")
    st.stop()

# --- [Phase 1: 環境配置] ---
TODAY = datetime.now()
st.set_page_config(page_title="專業台股診斷儀表板", layout="wide")

ticker_map = {
    "2330.TW": "台積電 (TSMC)",
    "2317.TW": "鴻海 (Foxconn)",
    "2454.TW": "聯發科 (MediaTek)",
    "3163.TWO": "波若威 (Browave)",
    "NVDA": "輝達 (NVIDIA)",
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
    val = st.session_state.get("stock_text", "")
    if val: st.session_state.active_ticker = val.strip().upper()

st.sidebar.header("🕹️ 分析設定")
current_ticker = st.session_state.active_ticker
default_idx = list(ticker_map.keys()).index(current_ticker) if current_ticker in ticker_map else 0

st.sidebar.selectbox("1. 選擇股票", options=list(ticker_map.values()), index=default_idx, key="stock_selector", on_change=update_from_select)
st.sidebar.text_input("2. 直接輸入代號", key="stock_text", on_change=update_from_text, placeholder="例如: 2317.TW")

fm_token = st.sidebar.text_input("💎 FinMind Token (必填)", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
st.query_params["ticker"] = st.session_state.active_ticker

# --- [Phase 3: 加強型數據引擎] ---
@st.cache_data(ttl=3600)
def get_full_data(ticker, token):
    # 1. 抓取股價 (yfinance)
    df = yf.download(ticker, start=TODAY - timedelta(days=360), end=TODAY + timedelta(days=1))
    if df.empty: return None, None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).strftime('%Y-%m-%d')
    
    # 2. 抓取上市法人 (FinMind)
    inst_df = pd.DataFrame()
    if ".TW" in ticker.upper() and ".TWO" not in ticker.upper():
        dl = DataLoader()
        if token and len(token.strip()) > 10:
            try:
                dl.login_by_token(api_token=token.strip())
                inst_df = dl.request_data(
                    dataset='TaiwanStockInstitutionalInvestorsBuySell', 
                    stock_id=ticker.replace('.TW', ''),
                    start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d")
                )
            except: pass
    return df, inst_df

# --- [Phase 4: 主程式執行與診斷] ---
df, inst_raw = get_full_data(st.session_state.active_ticker, fm_token)

if df is not None:
    st.title(f"📊 {st.session_state.active_ticker} 專業籌碼診斷儀表板")
    
    # 數據偵錯室
    with st.expander("🛠️ API 診斷中心 (若圖表沒資料請點開)"):
        col_d1, col_d2 = st.columns(2)
        col_d1.write(f"當前 Token 長度: {len(fm_token) if fm_token else 0}")
        col_d2.write(f"FinMind 原始回傳筆數: {len(inst_raw) if inst_raw is not None else 0}")
        if st.button("🔥 強制重整數據 (清除快取)"):
            st.cache_data.clear()
            st.rerun()

    # 資料處理與咬合
    df['Foreign'] = 0.0
    df['Trust'] = 0.0

    # 上市股處理
    if inst_raw is not None and not inst_raw.empty:
        inst_raw['date'] = pd.to_datetime(inst_raw['date']).dt.strftime('%Y-%m-%d')
        # 外資
        f_mask = inst_raw['name'].str.contains('Foreign_Investor|外資', na=False)
        f_data = inst_raw[f_mask].groupby('date')[['buy', 'sell']].sum()
        df['Foreign'] = (f_data['buy'] - f_data['sell']).reindex(df.index).fillna(0)
        # 投信
        t_mask = inst_raw['name'].str.contains('Investment_Trust|投信', na=False)
        t_data = inst_raw[t_mask].groupby('date')[['buy', 'sell']].sum()
        df['Trust'] = (t_data['buy'] - t_data['sell']).reindex(df.index).fillna(0)

    # 上櫃股 CSV 處理
    if ".TWO" in st.session_state.active_ticker:
        csv_files = glob.glob("tpex_inst_[0-9]*.csv")
        hist = []
        for f in csv_files:
            try:
                d_str = f[-12:-4]
                fmt_date = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                t_df = pd.read_csv(f)
                row = t_df[t_df['代號'].astype(str) == st.session_state.active_ticker.split('.')[0]]
                if not row.empty:
                    hist.append({'date': fmt_date, 'F': row.iloc[0]['外資買賣超'], 'T': row.iloc[0]['投信買賣超']})
            except: pass
        if hist:
            h_df = pd.DataFrame(hist).set_index('date')
            df['Foreign'] = h_df['F'].reindex(df.index).fillna(df['Foreign'])
            df['Trust'] = h_df['T'].reindex(df.index).fillna(df['Trust'])

    # --- [Phase 6: 繪圖] ---
    df_plot = df.tail(200).copy()
    
    # 確保有價格才進行分析，解決 TypeError
    if not df_plot.empty:
        # 指標計算
        df_plot['EMA12'] = df_plot['Close'].ewm(span=12).mean()
        df_plot['EMA26'] = df_plot['Close'].ewm(span=26).mean()
        df_plot['MACD'] = df_plot['EMA12'] - df_plot['EMA26']
        df_plot['Signal'] = df_plot['MACD'].ewm(9).mean()
        df_plot['Hist'] = df_plot['MACD'] - df_plot['Signal']

        col_chart, col_ctrl = st.columns([5, 1])
        with col_ctrl:
            st.subheader("分析工具箱")
            show_star = st.checkbox("標示漲停", value=True)
            ai_btn = st.button("🚀 AI 分析")
            latest_p = df_plot['Close'].iloc[-1]
            st.markdown(f"最新價格: <h2 style='color:red;'>{latest_p:,.2f}</h2>", unsafe_allow_html=True)

        with col_chart:
            fig = go.Figure()
            #