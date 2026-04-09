import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader
import glob

# =================================================================
# Phase 0: 門禁與狀態管理 (🌟 修正：確保切換個股時密碼狀態不會遺失)
# =================================================================
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# 初始化核心狀態，防止重整後遺失
if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = st.query_params.get("ticker", "2330.TW")

# 驗證流程
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

# =================================================================
# Phase 1: 環境配置
# =================================================================
TODAY = datetime.now()
st.set_page_config(page_title="專業台美股 K 線探測器", layout="wide")

ticker_map = {
    "2330.TW": "台積電 (TSMC)",
    "2317.TW": "鴻海 (Foxconn)",
    "2454.TW": "聯發科 (MediaTek)",
    "3163.TWO": "波若威 (Browave)",
    "NVDA": "輝達 (NVIDIA)",
}

# =================================================================
# Phase 2: 側邊欄與個股控制 (🌟 修正：解決兩次輸入與密碼彈出)
# =================================================================
def update_from_select():
    val = st.session_state.stock_selector
    st.session_state.active_ticker = [k for k, v in ticker_map.items() if v == val][0]
    st.session_state.stock_text = "" # 清空文字框

def update_from_text():
    val = st.session_state.stock_text.strip().upper()
    if val:
        st.session_state.active_ticker = val

st.sidebar.header("🕹️ 分析設定與工具")

# 同步選擇項
current_ticker = st.session_state.active_ticker
default_idx = list(ticker_map.keys()).index(current_ticker) if current_ticker in ticker_map else 0

st.sidebar.selectbox("1. 選擇預設股票", options=list(ticker_map.values()), 
                     index=default_idx, key="stock_selector", on_change=update_from_select)

st.sidebar.text_input("2. 或直接輸入代號", key="stock_text", 
                      on_change=update_from_text, placeholder="例如: 2317.TW")

fm_token = st.sidebar.text_input("💎 FinMind Token (選填)", 
                                value=st.secrets.get("FINMIND_TOKEN", ""), type="password")

selected_ticker = st.session_state.active_ticker
st.query_params["ticker"] = selected_ticker

# =================================================================
# Phase 3: 資料函數
# =================================================================
@st.cache_data(ttl=3600)
def get_all_data(ticker, token):
    # 1. 抓取股價
    df = yf.download(ticker, start=TODAY - timedelta(days=360), end=TODAY + timedelta(days=1))
    if df.empty: return df, pd.DataFrame(), pd.DataFrame()
    
    # 🌟 關鍵修正：將股價索引強制轉為「純日期字串」，這是咬合成功的唯一途徑
    df.index = pd.to_datetime(df.index).strftime('%Y-%m-%d')
    
    # 2. 抓取上市法人數據
    inst_df = pd.DataFrame()
    if ".TW" in ticker.upper():
        dl = DataLoader()
        if token: dl.login_by_token(api_token=token.strip())
        try:
            inst_df = dl.request_data(
                dataset='TaiwanStockInstitutionalInvestorsBuySell', 
                stock_id=ticker.replace('.TW', ''),
                start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d")
            )
        except: pass
    
    return df, inst_df

# =================================================================
# Phase 4: 資料處理與咬合
# =================================================================
df, inst_raw = get_all_data(selected_ticker, fm_token)

if not df.empty:
    st.title(f"📊 {selected_ticker} 專業籌碼診斷儀表板")
    
    # 初始化法人欄位
    df['Foreign'] = 0.0
    df['Trust'] = 0.0

    # A. 處理上市股資料 (.TW)
    if ".TW" in selected_ticker.upper() and not inst_raw.empty:
        # 將 API 日期也轉成字串
        inst_raw['date'] = pd.to_datetime(inst_raw['date']).dt.strftime('%Y-%m-%d')
        # 外資
        f_mask = inst_raw['name'].str.contains('Foreign_Investor|外資', na=False)
        f_data = inst_raw[f_mask].groupby('date')[['buy', 'sell']].sum()
        df['Foreign'] = (f_data['buy'] - f_data['sell']).reindex(df.index).fillna(0)
        # 投信
        t_mask = inst_raw['name'].str.contains('Investment_Trust|投信', na=False)
        t_data = inst_raw[t_mask].groupby('date')[['buy', 'sell']].sum()
        df['Trust'] = (t_data['buy'] - t_data['sell']).reindex(df.index).fillna(0)

    # B. 處理上櫃股資料 (.TWO)
    if ".TWO" in selected_ticker.upper():
        csv_files = glob.glob("tpex_inst_[0-9]*.csv")
        if csv_files:
            hist_list = []
            for f in csv_files:
                d_str = f[-12:-4]
                fmt_date = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                t_df = pd.read_csv(f)
                row = t_df[t_df['代號'].astype(str) == selected_ticker.split('.')[0]]
                if not row.empty:
                    hist_list.append({'date': fmt_date, 'F': row.iloc[0]['外資買賣超'], 'T': row.iloc[0]['投信買賣超']})
            
            if hist_list:
                h_df = pd.DataFrame(hist_list).set_index('date')
                df['Foreign'] = h_df['F'].reindex(df.index).fillna(df['Foreign'])
                df['Trust'] = h_df['T'].reindex(df.index).fillna(df['Trust'])

    # =================================================================
    # Phase 6: 專業六層畫布 (還原華麗比例與標籤)
    # =================================================================
    df_plot = df.tail(200).copy()
    
    # 技術指標
    df_plot['EMA12'] = df_plot['Close'].ewm(span=12).mean()
    df_plot['EMA26'] = df_plot['Close'].ewm(span=26).mean()
    df_plot['MACD'] = df_plot['EMA12'] - df_plot['EMA26']
    df_plot['Signal'] = df_plot['MACD'].ewm(span=9).mean()
    df_plot['Hist'] = df_plot['MACD'] - df_plot['Signal']

    col_chart, col_ctrl = st.columns([5, 1])
    with col_ctrl:
        st.subheader("分析工具箱")
        show_limit = st.checkbox("標示漲停 (10%)", value=True)
        ai_clicked = st.button("🚀 啟動 AI 趨勢診斷", use_container_width=True)
        cur_p = df_plot['Close'].iloc[-1]
        st.markdown(f"最新價格: <h2 style='color:red;'>{cur_p:,.2f}</h2>", unsafe_allow_html=True)

    with col_chart:
        fig = go.Figure()
        # 1. K線
        fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線", yaxis="y1"))
        
        # 2. 漲停星星
        if show_limit:
            limit_up = df_plot[df_plot['Close'] >= (df_plot['Close'].shift(1) * 1.097)]
            if not limit_up.empty:
                fig.add_trace(go.Scatter(x=limit_up.index, y=limit_up['High']*1.03, mode='markers', name='漲停', marker=dict(symbol='star', size=12, color='gold'), yaxis="y1"))

        # 3. 法人柱狀圖 (🌟 修正：顏色與數值)
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Foreign'], name="外資", marker_color=np.where(df_plot['Foreign']>=0, 'red', 'green'), yaxis="y3"))
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Trust'], name="投信", marker_color=np.where(df_plot['Trust']>=0, 'red', 'green'), yaxis="y4"))
        
        # 4. 指標
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Hist'], name="MACD柱", marker_color=np.where(df_plot['Hist']>=0, 'red', 'green'), yaxis="y5"))

        # 佈局設定 (還原六層比例)
        fig.update_layout(
            height=1000, template="plotly_white", hovermode="x unified",
            xaxis=dict(type='category', dtick=20),
            yaxis1=dict(domain=[0.6, 1.0]), # K線
            yaxis3=dict(domain=[0.35, 0.5]), # 外資
            yaxis4=dict(domain=[0.18, 0.33]), # 投信
            yaxis5=dict(domain=[0, 0.15]), # MACD
            showlegend=False
        )
        # 加上垂直文字標註
        fig.add_annotation(text="價<br>格", x=0, xref="paper", y=0.8, yref="paper", showarrow=False)
        fig.add_annotation(text="外<br>資", x=0, xref="paper", y=0.42, yref="paper", showarrow=False)
        fig.add_annotation(text="投<br>信", x=0, xref="paper", y=0.25, yref="paper", showarrow=False)
        
        st.plotly_chart(fig, use_container_width=True)

    if ai_clicked:
        st.info("AI 分析生成中...")