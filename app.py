import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader
import glob

# --- [Phase 0 ~ 2: 門禁與狀態管理] --- (保持你原本最正確的版本)
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
    st.stop()

TODAY = datetime.now()
st.set_page_config(page_title="專業台股 K 線探測器", layout="wide")

ticker_map = {
    "2330.TW": "台積電 (TSMC)",
    "2317.TW": "鴻海 (Foxconn)",
    "2454.TW": "聯發科 (MediaTek)",
    "3163.TWO": "波若威 (Browave)",
    "NVDA": "輝達 (NVIDIA)",
}

if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = st.query_params.get("ticker", "2330.TW")

def update_from_select():
    val = st.session_state.get("stock_selector")
    if val:
        st.session_state.active_ticker = [k for k, v in ticker_map.items() if v == val][0]
        st.session_state["stock_text"] = ""

def update_from_text():
    text_val = st.session_state.get("stock_text", "")
    if text_val: st.session_state.active_ticker = text_val.strip().upper()

st.sidebar.header("🕹️ 分析設定")
current_ticker = st.session_state.active_ticker
default_idx = list(ticker_map.keys()).index(current_ticker) if current_ticker in ticker_map else 0

st.sidebar.selectbox("1. 選擇股票", options=list(ticker_map.values()), index=default_idx, key="stock_selector", on_change=update_from_select)
st.sidebar.text_input("2. 輸入代號", key="stock_text", on_change=update_from_text)

fm_token = st.sidebar.text_input("💎 FinMind Token (選填)", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
selected_ticker = st.session_state.active_ticker
st.query_params["ticker"] = selected_ticker

# --- [Phase 3: 資料抓取] ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    data = yf.download(ticker, start=TODAY - timedelta(days=360), end=TODAY + timedelta(days=1))
    if data.empty: return data
    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
    # 🌟 強制將股價索引轉為「無時區、純日期」的 DatetimeIndex
    data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
    return data

@st.cache_data(ttl=3600)
def get_institutional_data(ticker, token=""):
    if ".TWO" in ticker.upper(): return pd.DataFrame() 
    dl = DataLoader()
    if token and len(token.strip()) > 5:
        try: dl.login_by_token(api_token=token.strip())
        except: pass
    try:
        df = dl.request_data(dataset='TaiwanStockInstitutionalInvestorsBuySell', 
                             stock_id=ticker.replace('.TW', ''),
                             start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d"),
                             end_date=(TODAY + timedelta(days=1)).strftime("%Y-%m-%d"))
        return df if df is not None else pd.DataFrame()
    except: return pd.DataFrame()

# --- [Phase 4: 主程式數據處理] ---
if selected_ticker:
    st.title(f"📊 {selected_ticker} 診斷儀表板")
    df = get_stock_data(selected_ticker)
    inst_df = get_institutional_data(selected_ticker, token=fm_token)

    if not df.empty:
        # 技術指標計算
        for w in [5, 20, 60]:
            df[f'SMA_{w}'] = df['Close'].rolling(window=w).mean()
        
        # 準備基礎法人 DataFrame (預設全 0)
        df['Foreign'] = 0.0
        df['Trust'] = 0.0

        # --- 🌟 引擎一：上櫃股 (.TWO) 歷史 CSV ---
        if ".TWO" in selected_ticker.upper():
            csv_files = glob.glob("tpex_inst_[0-9]*.csv")
            if csv_files:
                hist_records = []
                for f in csv_files:
                    f_df = pd.read_csv(f)
                    row = f_df[f_df['代號'].astype(str) == selected_ticker.split('.')[0]]
                    if not row.empty:
                        # 檔名轉日期
                        f_date = pd.to_datetime(f[-12:-4]).normalize()
                        hist_records.append({'date': f_date, 'F': row.iloc[0]['外資買賣超'], 'T': row.iloc[0]['投信買賣超']})
                if hist_records:
                    h_df = pd.DataFrame(hist_records).set_index('date')
                    # 將歷史 CSV 數據更新進主 df
                    df.update(h_df.rename(columns={'F': 'Foreign', 'T': 'Trust'}))

        # --- 🌟 引擎二：上市股 (.TW) FinMind ---
        if ".TW" in selected_ticker.upper() and not inst_df.empty:
            inst_df['date'] = pd.to_datetime(inst_df['date']).dt.normalize()
            f_mask = inst_df['name'].str.contains('Foreign_Investor|外資', na=False)
            f_data = inst_df[f_mask].groupby('date')[['buy', 'sell']].sum()
            f_data['Foreign'] = f_data['buy'] - f_data['sell']
            
            t_mask = inst_df['name'].str.contains('Investment_Trust|投信', na=False)
            t_data = inst_df[t_mask].groupby('date')[['buy', 'sell']].sum()
            t_data['Trust'] = t_data['buy'] - t_data['sell']
            
            # 🌟 更新上市股法人數據到主 df
            df.update(f_data[['Foreign']])
            df.update(t_data[['Trust']])

        # --- [Phase 6: 繪圖] ---
        df_plot = df.tail(200).copy()
        fig = go.Figure()
        
        # 1. K線圖
        fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線", yaxis="y1"))
        
        # 🌟 2. 漲停標記 (回歸！)
        limit_up = df_plot[df_plot['Close'] >= (df_plot['Close'].shift(1) * 1.097)]
        if not limit_up.empty:
            fig.add_trace(go.Scatter(x=limit_up.index, y=limit_up['High']*1.03, mode='markers', name='漲停', marker=dict(symbol='star', size=12, color='gold', line=dict(width=1, color='red')), yaxis="y1"))

        # 3. 法人柱狀圖 (外資、投信)
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Foreign'], name="外資", marker_color=np.where(df_plot['Foreign']>=0, 'red', 'green'), yaxis="y2"))
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Trust'], name="投信", marker_color=np.where(df_plot['Trust']>=0, 'red', 'green'), yaxis="y3"))

        fig.update_layout(height=850, template="plotly_white", hovermode="x unified",
                          yaxis1=dict(domain=[0.4, 1.0]), 
                          yaxis2=dict(domain=[0.2, 0.35]), 
                          yaxis3=dict(domain=[0, 0.15]),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

        if st.button("🚀 啟動 AI 趨勢診斷"):
            g_key = st.secrets.get("GEMINI_API_KEY")
            if g_key:
                genai.configure(api_key=g_key)
                model = genai.GenerativeModel('gemini-2.0-flash')
                resp = model.generate_content(f"分析股票 {selected_ticker}，收盤 {df_plot['Close'].iloc[-1]}。")
                st.info(resp.text)