import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader
import glob

# ==========================================
# Phase 0: 門禁系統 (Gatekeeper) - 🌟 強化穩定性
# ==========================================
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
                st.error("❌ 密碼錯誤，請重新輸入！")
    st.stop()

# ==========================================
# Phase 1: 環境與全局設定
# ==========================================
TODAY = datetime.now()
st.set_page_config(page_title="專業台美股 K 線探測器", layout="wide")

ticker_map = {
    "2330.TW": "台積電 (TSMC)",
    "2317.TW": "鴻海 (Foxconn)",
    "2454.TW": "聯發科 (MediaTek)",
    "3163.TWO": "波若威 (Browave)",
    "NVDA": "輝達 (NVIDIA)",
    "AAPL": "蘋果 (Apple)",
}

# ==========================================
# Phase 2: 狀態管理與側邊欄 (🌟 解決切換個股登出問題)
# ==========================================
if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = st.query_params.get("ticker", "2330.TW")

def update_from_select():
    val = st.session_state.get("stock_selector")
    if val:
        new_ticker = [k for k, v in ticker_map.items() if v == val][0]
        st.session_state.active_ticker = new_ticker
        st.session_state["stock_text"] = ""

def update_from_text():
    val = st.session_state.get("stock_text", "")
    if val:
        st.session_state.active_ticker = val.strip().upper()

st.sidebar.header("🕹️ 分析設定與工具")

current_ticker = st.session_state.active_ticker
default_idx = list(ticker_map.keys()).index(current_ticker) if current_ticker in ticker_map else 0

st.sidebar.selectbox("1. 選擇預設股票", options=list(ticker_map.values()), index=default_idx, key="stock_selector", on_change=update_from_select)
st.sidebar.text_input("2. 或直接輸入代號", key="stock_text", on_change=update_from_text, placeholder="例如: 2317.TW")

fm_token = st.sidebar.text_input("💎 FinMind Token (選填)", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
selected_ticker = st.session_state.active_ticker
st.query_params["ticker"] = selected_ticker

# ==========================================
# Phase 3: 強力數據抓取函數
# ==========================================
@st.cache_data(ttl=3600)
def get_data_engine(ticker, token):
    # 1. 股價
    raw_df = yf.download(ticker, start=TODAY - timedelta(days=360), end=TODAY + timedelta(days=1))
    if raw_df.empty: return None, None
    if isinstance(raw_df.columns, pd.MultiIndex): raw_df.columns = raw_df.columns.get_level_values(0)
    # 🌟 關鍵：強制索引轉字串 YYYY-MM-DD
    raw_df.index = pd.to_datetime(raw_df.index).strftime('%Y-%m-%d')
    
    # 2. 法人 (上市 .TW + 上櫃 .TWO 皆可抓取)
    inst_df = pd.DataFrame()
    # 🌟 代號清洗：去除 .TWO 再去除 .TW（順序重要，先長後短）
    clean_id = ticker.upper().replace('.TWO', '').replace('.TW', '')
    is_tw_stock = ticker.upper().endswith('.TW') or ticker.upper().endswith('.TWO')
    if is_tw_stock:
        dl = DataLoader()
        if token: dl.login_by_token(api_token=token.strip())
        try:
            inst_df = dl.taiwan_stock_institutional_investors(
                stock_id=clean_id,
                start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d")
            )
        except Exception as e:
            st.sidebar.warning(f"FinMind 呼叫失敗: {e}")
    return raw_df, inst_df

# ==========================================
# Phase 4: 主數據處理邏輯 (還原華麗功能)
# ==========================================
df, inst_raw = get_data_engine(selected_ticker, fm_token)

# 🌟 Sidebar 診斷區
st.sidebar.markdown("---")
st.sidebar.subheader("📡 數據診斷")
if inst_raw is not None:
    st.sidebar.write(f"API 抓取筆數: {len(inst_raw)}")
    if not inst_raw.empty:
        st.sidebar.write(f"日期範圍: {inst_raw['date'].iloc[0]} ~ {inst_raw['date'].iloc[-1]}")
        st.sidebar.write(f"欄位: {list(inst_raw.columns)}")
    else:
        st.sidebar.warning("FinMind API 回傳空資料 (0 筆)")
else:
    st.sidebar.info("非台股標的，不抓法人資料")

if df is not None:
    # 🌟 從 ticker_map 抓取中文名稱，如果抓不到就顯示代號
    display_name = ticker_map.get(selected_ticker, selected_ticker)
    st.title(f"📊 {display_name} 專業籌碼診斷儀表板")
    st.markdown("---")
    
    # A. 數據對齊與合併
    df['Foreign'] = 0.0
    df['Trust'] = 0.0

    # 🌟 法人數據對齊（上市 + 上櫃皆適用）
    if inst_raw is not None and not inst_raw.empty:
        # 關鍵：統一日期格式為 YYYY-MM-DD 字串，與 df.index 一致
        inst_raw['date'] = pd.to_datetime(inst_raw['date']).dt.strftime('%Y-%m-%d')
        
        # 外資
        f_mask = inst_raw['name'].str.contains('Foreign_Investor|外資', na=False)
        f_val = inst_raw[f_mask].groupby('date')[['buy', 'sell']].sum()
        f_net = f_val['buy'] - f_val['sell']
        df['Foreign'] = f_net.reindex(df.index).fillna(0).astype(float)
        
        # 投信
        t_mask = inst_raw['name'].str.contains('Investment_Trust|投信', na=False)
        t_val = inst_raw[t_mask].groupby('date')[['buy', 'sell']].sum()
        t_net = t_val['buy'] - t_val['sell']
        df['Trust'] = t_net.reindex(df.index).fillna(0).astype(float)
        
        # 診斷：合併後非零筆數
        f_nonzero = (df['Foreign'] != 0).sum()
        t_nonzero = (df['Trust'] != 0).sum()
        st.sidebar.write(f"外資有數據天數: {f_nonzero} / {len(df)}")
        st.sidebar.write(f"投信有數據天數: {t_nonzero} / {len(df)}")

    # 上櫃股 CSV 縫合
    if ".TWO" in selected_ticker:
        csv_files = glob.glob("tpex_inst_[0-9]*.csv")
        hist_list = []
        for f in csv_files:
            try:
                d_str = f[-12:-4]
                fmt_date = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                t_df = pd.read_csv(f)
                row = t_df[t_df['代號'].astype(str) == selected_ticker.split('.')[0]]
                if not row.empty:
                    hist_list.append({'date': fmt_date, 'F': row.iloc[0]['外資買賣超'], 'T': row.iloc[0]['投信買賣超']})
            except: pass
        if hist_list:
            h_df = pd.DataFrame(hist_list).set_index('date')
            df['Foreign'] = h_df['F'].reindex(df.index).fillna(df['Foreign'])
            df['Trust'] = h_df['T'].reindex(df.index).fillna(df['Trust'])

    # 技術指標
    for w in [5, 10, 20, 60, 120]:
        df[f'SMA_{w}'] = df['Close'].rolling(w).mean()
    df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(9).mean()
    df['Hist'] = df['MACD'] - df['Signal']

    # 截取繪圖段
    df_plot = df.tail(200).copy()

    # ==========================================
    # Phase 5 & 6: 專業六層畫布與工具箱
    # ==========================================
    col_chart, col_ctrl = st.columns([5, 1])
    
    with col_ctrl:
        st.subheader("分析工具箱")
        active_smas = [w for w in [5, 10, 20, 60, 120] if st.checkbox(f"{w}日線", value=w in [5, 20, 60])]
        show_limit = st.checkbox("標示漲停 (10%)", value=True)
        ai_clicked = st.button("🚀 啟動 AI 診斷", use_container_width=True)
        
        # 🌟 修正 TypeError：確保有數據才顯示價格
        if not df_plot.empty:
            cur_p = df_plot['Close'].iloc[-1]
            pre_p = df_plot['Close'].iloc[-2]
            diff = cur_p - pre_p
            p_color = "red" if diff >= 0 else "green"
            st.markdown(f"**最新價格**")
            st.markdown(f"<h2 style='color:{p_color};'>{cur_p:,.2f}</h2>", unsafe_allow_html=True)
            st.markdown(f"<p style='color:{p_color};'>{diff:+.2f} ({ (diff/pre_p)*100:+.2f}%)</p>", unsafe_allow_html=True)

    with col_chart:
        fig = go.Figure()
        # 1. K線
        fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線", yaxis="y1", increasing_line_color='red', decreasing_line_color='green'))
        
        # 2. 漲停星星
        if show_limit:
            limit_up = df_plot[df_plot['Close'] >= (df_plot['Close'].shift(1) * 1.097)]
            if not limit_up.empty:
                fig.add_trace(go.Scatter(x=limit_up.index, y=limit_up['High']*1.02, mode='markers', name='漲停', marker=dict(symbol='star', size=12, color='gold'), yaxis="y1"))
        
        # 3. 均線
        colors = {5: "#FFC107", 10: "#E91E63", 20: "#2196F3", 60: "#4CAF50", 120: "#FF5722"}
        for w in active_smas:
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'SMA_{w}'], name=f'{w}MA', line=dict(color=colors[w], width=1.5), yaxis="y1"))

        # 4. 成交量、外資、投信、MACD
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], name="量", marker_color='rgba(128,128,128,0.2)', yaxis="y2"))
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Foreign'], name="外", marker_color=np.where(df_plot['Foreign']>=0, 'red', 'green'), yaxis="y3"))
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Trust'], name="投", marker_color=np.where(df_plot['Trust']>=0, 'red', 'green'), yaxis="y4"))
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Hist'], name="M", marker_color=np.where(df_plot['Hist']>=0, 'red', 'green'), yaxis="y5"))

        # 佈局設定 (還原六層比例)
        fig.update_layout(
            height=1100, template="plotly_white", hovermode="x unified",
            xaxis=dict(type='category', dtick=20),
            yaxis1=dict(domain=[0.65, 1.0]), yaxis2=dict(domain=[0.55, 0.63]),
            yaxis3=dict(domain=[0.40, 0.52]), yaxis4=dict(domain=[0.25, 0.37]),
            yaxis5=dict(domain=[0, 0.22]),
            showlegend=False
        )
        # ==========================================
        # 🌟 找回左側說明標籤 (直書文字：價格、量、外資、投信、MACD、KD)
        # ==========================================
        # 修正後的標籤配置
        label_config = dict(
            x=0,              # 強制定位在畫布最左端
            xref="paper", 
            xanchor="right",  # 以文字右側為準向左對齊
            xshift=-15,       # 向左方邊界推移，避免重疊到 Y 軸數字
            showarrow=False, 
            align="center", 
            font=dict(size=14)
        )

        fig.add_annotation(text="價<br>格", y=0.82, yref="paper", **label_config)
        fig.add_annotation(text="成<br>交<br>量", y=0.58, yref="paper", **label_config)
        fig.add_annotation(text="外<br>資", y=0.46, yref="paper", **label_config)
        fig.add_annotation(text="投<br>信", y=0.34, yref="paper", **label_config)
        fig.add_annotation(text="M<br>A<br>C<br>D", y=0.19, yref="paper", **label_config)
        fig.add_annotation(text="K<br>D", y=0.05, yref="paper", **label_config)
        
        st.plotly_chart(fig, use_container_width=True)

    if ai_clicked:
        st.info("💡 AI 診斷生成中... 請確認 API KEY 已設定。")

else:
    st.error("⚠️ 無法取得數據，請確認代號或 API 連線。")