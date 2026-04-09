import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import glob
from datetime import datetime, timedelta

# ==========================================
# 1. 網頁初始設定 (寬版、標題)
# ==========================================
st.set_page_config(layout="wide", page_title="AI 籌碼診斷儀表板")

# ==========================================
# 2. 側邊欄 UI 設定
# ==========================================
with st.sidebar:
    st.markdown("### 🕹️ 分析設定與工具")
    
    # 預設股票選單
    default_tickers = {
        "台積電 (TSMC)": "2330.TW",
        "波若威 (Browave)": "3163.TWO",
        "元大台灣50": "0050.TW"
    }
    selected_name = st.selectbox("1. 選擇預設股票", list(default_tickers.keys()))
    
    # 讓使用者輸入代號 (如果有輸入，就覆蓋預設值)
    manual_ticker = st.text_input("2. 或直接輸入代號 (例如 3163.TWO)", value=default_tickers[selected_name])
    selected_ticker = manual_ticker.upper() if manual_ticker else default_tickers[selected_name]
    
    finmind_token = st.text_input("💎 FinMind Token (上市籌碼用，選填)", type="password")
    
    st.info("💡 分析師提醒：技術指標與 AI 分析僅供決策參考，投資請務必維持獨立思考並嚴格執行分批佈局。")

# ==========================================
# 3. 獲取核心股價資料 (yfinance)
# ==========================================
@st.cache_data(ttl=3600) # 快取 1 小時，避免一直重複抓
def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="1y") # 抓過去一年
    if not df.empty:
        # 計算均線
        for window in [5, 10, 20, 60, 120]:
            df[f'{window}MA'] = df['Close'].rolling(window=window).mean()
        
        # 計算 MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['Hist'] = df['MACD'] - df['Signal']
        
        # 計算 KD
        df['Min_9'] = df['Low'].rolling(window=9).min()
        df['Max_9'] = df['High'].rolling(window=9).max()
        df['RSV'] = 100 * (df['Close'] - df['Min_9']) / (df['Max_9'] - df['Min_9'])
        df['K'] = df['RSV'].ewm(alpha=1/3, adjust=False).mean()
        df['D'] = df['K'].ewm(alpha=1/3, adjust=False).mean()
        
        # 預設籌碼欄位為 0
        df['外資買賣超'] = 0
        df['投信買賣超'] = 0
    return df, stock.info

df, stock_info = get_stock_data(selected_ticker)

if df.empty:
    st.error(f"找不到 {selected_ticker} 的資料，請確認代號是否正確。")
    st.stop()

# 取得股票名稱
stock_name = stock_info.get('shortName', selected_ticker.split('.')[0])
st.markdown(f"## 📊 {selected_ticker} {stock_name} 專業籌碼診斷儀表板")

# ==========================================
# 4. 籌碼資料處理 (雙引擎：FinMind / 本地 CSV)
# ==========================================
stock_id = selected_ticker.split('.')[0]

# --- 引擎 A：上市股票 (.TW) 使用 FinMind API ---
if ".TW" in selected_ticker and finmind_token:
    st.success("✅ 上市籌碼已透過 FinMind API 即時連線。")
    # 這裡保留你原本 FinMind 的抓取邏輯 (以下為概念簡化版)
    # df['外資買賣超'] = finmind_data['外資買賣超']
    # df['投信買賣超'] = finmind_data['投信買賣超']

# --- 引擎 B：上櫃股票 (.TWO) 使用專屬 GitHub 爬蟲 CSV ---
elif ".TWO" in selected_ticker:
    st.info("💡 上櫃籌碼由專屬 GitHub 爬蟲每日自動提供。")
    
    # 1. 尋找並過濾正式的 CSV 檔案
    csv_files = glob.glob("tpex_inst_[0-9]*.csv")
    
    if csv_files:
        # 取出最新一天的檔案顯示在儀表板
        latest_file = sorted(csv_files)[-1]
        tpex_df = pd.read_csv(latest_file)
        tpex_df['代號'] = tpex_df['代號'].astype(str)
        target_data = tpex_df[tpex_df['代號'] == stock_id]
        
        if not target_data.empty:
            date_str = latest_file.replace('tpex_inst_', '').replace('.csv', '')
            st.markdown(f"### 🎯 最新交易日 ({date_str}) 法人動向")
            col1, col2, col3 = st.columns(3)
            col1.metric("外資買賣超 (張)", f"{target_data.iloc[0]['外資買賣超']:,}")
            col2.metric("投信買賣超 (張)", f"{target_data.iloc[0]['投信買賣超']:,}")
            col3.metric("三大法人合計 (張)", f"{target_data.iloc[0]['三大法人買賣超']:,}")
            st.divider()
        
        # 2. 歷史資料縫合術 (一天一天拼湊起來餵給線圖)
        history_records = []
        for file in csv_files:
            try:
                d_str = file.replace('tpex_inst_', '').replace('.csv', '')
                date_obj = pd.to_datetime(d_str, format='%Y%m%d')
                temp_df = pd.read_csv(file)
                temp_df['代號'] = temp_df['代號'].astype(str)
                t_row = temp_df[temp_df['代號'] == stock_id]
                
                if not t_row.empty:
                    history_records.append({
                        'Date': date_obj,
                        'Foreign_Buy': t_row.iloc[0]['外資買賣超'],
                        'Trust_Buy': t_row.iloc[0]['投信買賣超']
                    })
            except Exception as e:
                pass # 解析失敗跳過
        
        # 將收集到的歷史籌碼塞進主 DataFrame (df)
        if history_records:
            history_df = pd.DataFrame(history_records)
            history_df.set_index('Date', inplace=True)
            
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
                
            df = df.join(history_df[['Foreign_Buy', 'Trust_Buy']], how='left')
            df['外資買賣超'] = df['Foreign_Buy'].fillna(0)
            df['投信買賣超'] = df['Trust_Buy'].fillna(0)
    else:
        st.warning("⚠️ 尚未抓取到上櫃籌碼 CSV 資料，圖表將暫時顯示為 0。")

# ==========================================
# 5. 繪製專業子圖表 (Plotly Subplots)
# ==========================================
# 建立 5 個子圖 (K線、成交量、外資、投信、MACD)
fig = make_subplots(rows=5, cols=1, shared_xaxes=True, 
                    vertical_spacing=0.02, 
                    row_heights=[0.5, 0.1, 0.1, 0.1, 0.2])

# (1) K線圖
fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['5MA'], name='5MA', line=dict(color='orange', width=1)), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['20MA'], name='20MA', line=dict(color='blue', width=1)), row=1, col=1)

# (2) 成交量
colors = ['red' if close >= open else 'green' for close, open in zip(df['Close'], df['Open'])]
fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

# (3) 外資買賣超
foreign_colors = ['red' if val > 0 else 'green' for val in df['外資買賣超']]
fig.add_trace(go.Bar(x=df.index, y=df['外資買賣超'], name='外資', marker_color=foreign_colors), row=3, col=1)

# (4) 投信買賣超
trust_colors = ['red' if val > 0 else 'green' for val in df['投信買賣超']]
fig.add_trace(go.Bar(x=df.index, y=df['投信買賣超'], name='投信', marker_color=trust_colors), row=4, col=1)

# (5) MACD
macd_colors = ['red' if val > 0 else 'green' for val in df['Hist']]
fig.add_trace(go.Bar(x=df.index, y=df['Hist'], name='MACD柱', marker_color=macd_colors), row=5, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], name='MACD線', line=dict(color='blue', width=1)), row=5, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['Signal'], name='Signal線', line=dict(color='orange', width=1)), row=5, col=1)

# 圖表版面設定
fig.update_layout(
    height=900, 
    template="plotly_dark", # 帥氣的深色主題
    margin=dict(l=0, r=0, t=30, b=0),
    xaxis_rangeslider_visible=False # 關閉下方的捲動條，讓畫面更簡潔
)

# 將圖表顯示在網頁上
st.plotly_chart(fig, use_container_width=True)