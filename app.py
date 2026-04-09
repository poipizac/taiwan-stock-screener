import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader
import glob

# --- [Phase 0: 門禁] ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.set_page_config(page_title="🔒 登入驗證", layout="centered")
    with st.form("login_form"):
        pwd = st.text_input("請輸入密碼：", type="password")
        if st.form_submit_button("解鎖"):
            if pwd == st.secrets.get("APP_PASSWORD", "admin"):
                st.session_state.authenticated = True
                st.rerun()
    st.stop()

# --- [Phase 1: 環境設定] ---
st.set_page_config(page_title="專業台股診斷", layout="wide")
TODAY = datetime.now()

# --- [Phase 2: 側邊欄控制] ---
st.sidebar.header("🕹️ 分析設定")
selected_ticker = st.sidebar.text_input("請輸入股票代號 (如: 2330.TW 或 3163.TWO)", value="2330.TW").upper()
fm_token = st.sidebar.text_input("💎 FinMind Token (選填)", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")

# --- [Phase 3: 資料抓取] ---
@st.cache_data(ttl=3600)
def fetch_data(ticker, token):
    # 1. 抓取股價
    df = yf.download(ticker, start=TODAY - timedelta(days=360), end=TODAY + timedelta(days=1))
    if df.empty: return df
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    
    # 強制將股價索引轉為字串格式 'YYYY-MM-DD'，徹底解決咬合問題
    df.index = df.index.strftime('%Y-%m-%d')
    
    # 2. 準備法人欄位
    df['Foreign'] = 0.0
    df['Trust'] = 0.0
    
    # 3. 處理法人資料
    if ".TWO" in ticker:
        # 上櫃路徑 (CSV)
        csv_files = glob.glob("tpex_inst_[0-9]*.csv")
        for f in csv_files:
            try:
                date_str = f[-12:-4] # 擷取 YYYYMMDD
                formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                if formatted_date in df.index:
                    f_df = pd.read_csv(f)
                    row = f_df[f_df['代號'].astype(str) == ticker.split('.')[0]]
                    if not row.empty:
                        df.at[formatted_date, 'Foreign'] = float(row.iloc[0]['外資買賣超'])
                        df.at[formatted_date, 'Trust'] = float(row.iloc[0]['投信買賣超'])
            except: pass
    else:
        # 上市路徑 (FinMind)
        dl = DataLoader()
        if token: dl.login_by_token(api_token=token.strip())
        try:
            inst_df = dl.request_data(dataset='TaiwanStockInstitutionalInvestorsBuySell', 
                                      stock_id=ticker.replace('.TW', ''),
                                      start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d"))
            if inst_df is not None and not inst_df.empty:
                inst_df['date'] = pd.to_datetime(inst_df['date']).dt.strftime('%Y-%m-%d')
                for _, row in inst_df.iterrows():
                    d = row['date']
                    if d in df.index:
                        if '外資' in row['name'] or 'Foreign' in row['name']:
                            df.at[d, 'Foreign'] += (row['buy'] - row['sell'])
                        if '投信' in row['name'] or 'Trust' in row['name']:
                            df.at[d, 'Trust'] += (row['buy'] - row['sell'])
        except: pass
    return df

# --- [Phase 4: 執行與畫圖] ---
df = fetch_data(selected_ticker, fm_token)

if not df.empty:
    st.title(f"📊 {selected_ticker} 診斷儀表板")
    
    # 計算漲停標記 (漲幅 > 9.7%)
    df['Pct_Chg'] = df['Close'].pct_change()
    limit_up = df[df['Pct_Chg'] >= 0.097]

    # 設定畫布
    df_plot = df.tail(200)
    fig = go.Figure()

    # 1. K線
    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線", yaxis="y1"))
    
    # 2. 漲停星星 (這次絕對會出現)
    if not limit_up.empty:
        fig.add_trace(go.Scatter(x=limit_up.index, y=limit_up['High']*1.03, mode='markers', name='漲停', marker=dict(symbol='star', size=12, color='gold'), yaxis="y1"))

    # 3. 法人柱狀圖
    fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Foreign'], name="外資", marker_color=np.where(df_plot['Foreign']>=0, 'red', 'green'), yaxis="y2"))
    fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Trust'], name="投信", marker_color=np.where(df_plot['Trust']>=0, 'red', 'green'), yaxis="y3"))

    fig.update_layout(height=800, template="plotly_white", hovermode="x unified",
                      yaxis1=dict(domain=[0.4, 1.0]), 
                      yaxis2=dict(domain=[0.2, 0.35]), 
                      yaxis3=dict(domain=[0, 0.15]),
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    if st.button("🚀 AI 趨勢分析"):
        st.info("AI 分析中...") # 簡化版 AI 呼叫