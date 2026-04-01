import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import google.generativeai as genai
from FinMind.data import DataLoader

# --- [Phase 1: 環境與全局設定] ---
# 1. 全局時間錨點 (確保數據同步)
TODAY = datetime.now()
IS_TESTING = False  # 是否進入模擬模式

# 2. 專業頁面配置 (台股主題)
st.set_page_config(page_title="專業台美股 K 線探測器", layout="wide")

# 3. 股票快速選單 (繁體中文)
ticker_map = {
    "2330.TW": "台積電 (TSMC)",
    "2317.TW": "鴻海 (Foxconn)",
    "2454.TW": "聯發科 (MediaTek)",
    "NVDA": "輝達 (NVIDIA)",
    "AAPL": "蘋果 (Apple)",
    "TSLA": "特斯拉 (Tesla)",
    "0050.TW": "元大台灣50",
    "0056.TW": "元大高股息"
}

# --- [Phase 2: 狀態管理與側邊欄] ---
# 1. 讀取 URL 參數作為初期種子
params = st.query_params
qp_ticker = params.get("ticker", "2330.TW")

# 2. 初始化核心 Session State (Ground Truth)
if 'active_ticker' not in st.session_state:
    st.session_state.active_ticker = qp_ticker

# 3. 定義狀態同步 Callbacks (這會在 Rerun 前優先執行，解決兩次 Enter 問題)
def update_from_select():
    """下拉選單變更時，由名稱對應回代號並更新主狀態"""
    # 從名稱找回代號 (例如 "台積電 (TSMC)" -> "2330.TW")
    new_ticker = [k for k, v in ticker_map.items() if v == st.session_state.stock_selector][0]
    st.session_state.active_ticker = new_ticker
    st.session_state.stock_text = "" # 同步時清空手動輸入框

def update_from_text():
    """手動輸入變更時，清理空格並更新主狀態"""
    val = st.session_state.stock_text.strip().upper()
    if val:
        st.session_state.active_ticker = val

st.sidebar.header("🕹️ 分析設定與工具")

# 4. 決定元件初始顯示值 (由 active_ticker 驅動)
current_ticker = st.session_state.active_ticker
if current_ticker in ticker_map:
    default_idx = list(ticker_map.keys()).index(current_ticker)
    default_manual = ""
else:
    default_idx = 0 # 若不在地圖內，選單預設第一個
    default_manual = current_ticker

# 5. 渲染 UI 元件 (綁定 Key 與 on_change)
st.sidebar.selectbox(
    "1. 選擇預設股票",
    options=list(ticker_map.values()),
    index=default_idx,
    key="stock_selector",
    on_change=update_from_select
)

st.sidebar.text_input(
    "2. 或直接輸入代號",
    value=default_manual,
    placeholder="例如: 2317.TW 或 MSFT",
    key="stock_text",
    on_change=update_from_text
)

# 6. FinMind Token 與最終代碼決議
default_fm_token = st.secrets.get("FINMIND_TOKEN", "")
fm_token = st.sidebar.text_input("💎 FinMind Token (選填)", value=default_fm_token, type="password")

# 最終確定的股票資訊
selected_ticker = st.session_state.active_ticker
if selected_ticker in ticker_map:
    selected_display_name = ticker_map[selected_ticker]
else:
    selected_display_name = selected_ticker

# 7. 同步至 URL
st.query_params["ticker"] = selected_ticker

# --- [Phase 3: 資料抓取函數] ---
@st.cache_data(ttl=86400) # 快取一天，避免重複請求拖慢速度
def get_chinese_stock_name(ticker_symbol):
    try:
        # 從代號中提取純數字 (例如 '2615.TW' -> '2615')
        stock_id = ticker_symbol.split('.')[0]
        
        from FinMind.data import DataLoader
        import streamlit as st # 確保有引入 st
        
        dl_info = DataLoader()
        
        # 🌟 關鍵修復：讓查名字的動作也掛上你的 VIP 金鑰
        token = st.secrets.get("FINMIND_TOKEN", "")
        if token:
            dl_info.login_by_token(api_token=token)
            
        info_df = dl_info.taiwan_stock_info()
        
        # 比對並取出繁體中文名稱
        match = info_df[info_df['stock_id'] == stock_id]
        if not match.empty:
            return match['stock_name'].iloc[0]
    except Exception:
        pass
    return ""

@st.cache_data(ttl=3600)
def get_institutional_data(ticker, token=""):
    """從 FinMind 抓取法人籌碼數據"""
    end_date = TODAY + timedelta(days=1) # 同步推移確保資料對齊
    start_date = TODAY - timedelta(days=540)
    clean_ticker = ticker.replace('.TW', '').replace('.TWO', '')
    dl = DataLoader()
    if token: dl.login_by_token(api_token=token.strip())
    try:
        fm_df = dl.taiwan_stock_institutional_investors(
            stock_id=clean_ticker,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        return fm_df if fm_df is not None and not fm_df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# 均線顏色常數
sma_colors = {5: "#FFC107", 10: "#E91E63", 20: "#2196F3", 60: "#4CAF50", 120: "#FF5722"}

# --- 建立快取的中文名稱查詢器 ---
@st.cache_data(ttl=86400) # 快取一天，避免重複請求
def get_chinese_stock_name(ticker_symbol):
    try:
        # 從代號中提取純數字 (例如 '2317.TW' -> '2317')
        stock_id = ticker_symbol.split('.')[0]
        from FinMind.data import DataLoader
        dl_info = DataLoader()
        info_df = dl_info.taiwan_stock_info()
        
        # 比對並取出繁體中文名稱
        match = info_df[info_df['stock_id'] == stock_id]
        if not match.empty:
            return match['stock_name'].iloc[0]
    except Exception:
        pass
    return ""

# 程式主標題 (動態抓取繁體中文)
stock_chinese_name = ""
if selected_ticker:
    # 僅針對手動輸入或尚未在 Map 中有中文名的台股進行抓取
    if selected_ticker == selected_display_name and ".TW" in selected_ticker:
        stock_chinese_name = get_chinese_stock_name(selected_ticker)
    else:
        stock_chinese_name = ""

# 組合最終顯示標題
if stock_chinese_name:
    full_title = f"📊 {selected_ticker} {stock_chinese_name} 專業籌碼診斷儀表板"
else:
    # 若抓不到中文(如美股)或已在地圖內，則使用解析出的 display_name
    full_title = f"📊 {selected_display_name} 專業籌碼診斷儀表板"

st.title(full_title)
st.markdown("---")

# --- [Phase 4: 主程式數據處理] ---
if selected_ticker:
    with st.spinner(f"正在分析 {selected_ticker} 數據..."):
        df = get_stock_data(selected_ticker)
        inst_df = get_institutional_data(selected_ticker, token=fm_token)

    if not df.empty and len(df) > 0:
        # [1. 初始化與均線計算]
        foreign_df = pd.DataFrame()
        trust_df = pd.DataFrame()
        for window in [5, 10, 20, 60, 120]:
            df[f'SMA_{window}'] = df['Close'].rolling(window=window).mean()
        
        # [2. 法人數據處理與字串對齊]
        if not inst_df.empty:
            try:
                st.write(f"📈 系統診斷 - 法人數據筆數: {len(inst_df)}")
                if 'date' not in inst_df.columns:
                    inst_df = inst_df.reset_index()
                
                # 統一轉為 'YYYY-MM-DD' 字串
                inst_df['date'] = pd.to_datetime(inst_df['date']).dt.strftime('%Y-%m-%d')
                
                # 強制轉換名稱為字串防錯
                inst_df['name'] = inst_df['name'].astype(str)
                
                # 外資：Regex 同時比對英文與中文
                f_mask = inst_df['name'].str.contains('Foreign_Investor|外資', na=False, regex=True)
                foreign_df = inst_df[f_mask].groupby('date')[['buy', 'sell']].sum()
                if not foreign_df.empty:
                    foreign_df['Foreign'] = foreign_df['buy'] - foreign_df['sell']
                    foreign_df.index = pd.to_datetime(foreign_df.index).strftime('%Y-%m-%d')

                # 投信：Regex 同時比對英文與中文
                t_mask = inst_df['name'].str.contains('Investment_Trust|投信', na=False, regex=True)
                trust_df = inst_df[t_mask].groupby('date')[['buy', 'sell']].sum()
                if not trust_df.empty:
                    trust_df['Trust'] = trust_df['buy'] - trust_df['sell']
                    trust_df.index = pd.to_datetime(trust_df.index).strftime('%Y-%m-%d')
            except Exception as e:
                st.warning(f"⚠️ 法人資料處理中斷，將略過分析: {e}")

        # [3. 安全數據合併]
        df.index = pd.to_datetime(df.index).strftime('%Y-%m-%d')
        if not foreign_df.empty:
            df = df.join(foreign_df[['Foreign']], how='left')
        else:
            df['Foreign'] = 0
            
        if not trust_df.empty:
            df = df.join(trust_df[['Trust']], how='left')
        else:
            df['Trust'] = 0

        # 精準填補 0：只補法人，防止傷及股價
        df['Foreign'] = df['Foreign'].fillna(0)
        df['Trust'] = df['Trust'].fillna(0)
        
        # 數據清洗：刪除價格異常點
        df = df.dropna(subset=['Close'])
        df = df[df['Close'] > 0]
        
        if (df['Foreign'] == 0).all() and (df['Trust'] == 0).all():
            st.info("💡 目前查無近期法人買賣超數據。")

        # 截取近期交易資料 (並計算指標)
        df_plot = df.tail(252).copy()
        
        # --- [a. 計算 MACD] ---
        df_plot['EMA12'] = df_plot['Close'].ewm(span=12, adjust=False).mean()
        df_plot['EMA26'] = df_plot['Close'].ewm(span=26, adjust=False).mean()
        df_plot['MACD'] = df_plot['EMA12'] - df_plot['EMA26']
        df_plot['Signal'] = df_plot['MACD'].ewm(span=9, adjust=False).mean()
        df_plot['Hist'] = df_plot['MACD'] - df_plot['Signal']

        # --- [b. 計算 KD] ---
        min9 = df_plot['Low'].rolling(window=9).min()
        max9 = df_plot['High'].rolling(window=9).max()
        df_plot['RSV'] = (df_plot['Close'] - min9) / (max9 - min9) * 100
        df_plot['RSV'] = df_plot['RSV'].fillna(50)
        df_plot['K'] = df_plot['RSV'].ewm(com=2, adjust=False).mean()
        df_plot['D'] = df_plot['K'].ewm(com=2, adjust=False).mean()
        
        col_chart, col_ctrl = st.columns([5, 1])

        # --- [Phase 5: 工具面版] ---
        with col_ctrl:
            st.subheader("分析工具箱")
            st.write("**均線顯示設定**")
            
            # 從 URL 恢復 MA 狀態
            if "ma" in params:
                try: qp_smas = [int(x) for x in params.get_all("ma")]
                except: qp_smas = [5, 20, 60]
            else: qp_smas = [5, 20, 60]

            active_smas = []
            if st.checkbox("5日 (週線)", value=(5 in qp_smas)): active_smas.append(5)
            if st.checkbox("10日 (雙週)", value=(10 in qp_smas)): active_smas.append(10)
            if st.checkbox("20日 (月線)", value=(20 in qp_smas)): active_smas.append(20)
            if st.checkbox("60日 (季線)", value=(60 in qp_smas)): active_smas.append(60)
            if st.checkbox("120日線", value=(120 in qp_smas)): active_smas.append(120)
            st.query_params["ma"] = [str(x) for x in active_smas]
            
            st.write("---")
            st.write("**特殊標記**")
            show_limit_up = st.checkbox("標示漲停 (10%)", value=True)
            
            st.divider()
            st.write("**AI 智能分析**")
            ai_clicked = st.button("🚀 啟動趨勢診斷", use_container_width=True)
            
            st.divider()
            # 最新收盤資訊
            try:
                latest = df_plot[df_plot['Close'] > 0]
                cur_p = latest['Close'].iloc[-1].item()
                pre_p = latest['Close'].iloc[-2].item()
                p_diff = cur_p - pre_p
                p_pct = (p_diff / pre_p) * 100
                p_color = "#FF3333" if p_diff >= 0 else "#00AA00"
                
                st.write("**最新價格**")
                st.markdown(f"<h2 style='color:{p_color}; margin-top:-15px;'>{cur_p:,.2f}</h2>", unsafe_allow_html=True)
                st.markdown(f"<p style='color:{p_color}; margin-top:-15px;'>{p_diff:+.2f} ({p_pct:+.2f}%)</p>", unsafe_allow_html=True)
            except: pass

        # --- [Phase 6: 專業四層視覺畫布] ---
        with col_chart:
            fig = go.Figure()
            # 1. K線主圖
            fig.add_trace(go.Candlestick(
                x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'],
                name="K線", yaxis="y1",
                increasing_line_color='red',    # 台股：上漲紅
                decreasing_line_color='green',  # 台股：下跌綠
                hovertemplate='<b>日期</b>: %{x}<br><b>開盤</b>: %{open:.2f}<br><b>最高</b>: %{high:.2f}<br><b>最低</b>: %{low:.2f}<br><b>收盤</b>: %{close:.2f}<extra></extra>'
            ))
            # 2. 動態均線
            for window in active_smas:
                fig.add_trace(go.Scatter(
                    x=df_plot.index, y=df_plot[f'SMA_{window}'], mode='lines', 
                    name=f'{window}MA', line=dict(color=sma_colors[window], width=1.5), yaxis="y1",
                    hovertemplate=f'<b>{window}日線</b>: %{{y:.2f}}<extra></extra>'
                ))

            # 2.5 標示漲停 (特殊功能)
            if show_limit_up:
                # 計算漲停板 (約 10%，考量進位與台股實況取 9.8%)
                limit_up_mask = (df_plot['Close'] / df_plot['Close'].shift(1) - 1) >= 0.098
                limit_up_dates = df_plot[limit_up_mask]
                
                if not limit_up_dates.empty:
                    fig.add_trace(go.Scatter(
                        x=limit_up_dates.index,
                        y=limit_up_dates['High'] * 1.02, # 標註在最高價上方 2%
                        mode='markers',
                        name='漲停',
                        marker=dict(symbol='star-triangle-up', size=12, color='gold', line=dict(width=1, color='red')),
                        yaxis="y1",
                        hovertemplate='<b>日期</b>: %{x}<br><b>狀態</b>: 漲停板 (10%)<extra></extra>'
                    ))
            
            # 3. 交易量圖
            fig.add_trace(go.Bar(
                x=df_plot.index, y=df_plot['Volume'], name="成交量", 
                marker=dict(color=np.where(df_plot['Close'] >= df_plot['Open'], '#FFCDD2', '#C8E6C9')), 
                yaxis="y2",
                hovertemplate='<b>日期</b>: %{x}<br><b>成交量</b>: %{y:,.0f}<extra></extra>'
            ))
            
            # 4. 法人淨買賣超 (台股紅綠習慣)
            fig.add_trace(go.Bar(
                x=df_plot.index, y=df_plot['Foreign'], name="外資買超", 
                marker_color=np.where(df_plot['Foreign'] >= 0, 'red', 'green'),
                yaxis="y3",
                hovertemplate='<b>外資買賣超</b>: %{y:,.0f}<extra></extra>'
            ))
            fig.add_trace(go.Bar(
                x=df_plot.index, y=df_plot['Trust'], name="投信買超", 
                marker_color=np.where(df_plot['Trust'] >= 0, 'red', 'green'),
                yaxis="y4",
                hovertemplate='<b>投信買賣超</b>: %{y:,.0f}<extra></extra>'
            ))

            # 5. MACD 動能 (台股紅綠習慣)
            fig.add_trace(go.Bar(
                x=df_plot.index, y=df_plot['Hist'], name="MACD柱", 
                marker_color=np.where(df_plot['Hist'] >= 0, 'red', 'green'),
                yaxis="y5",
                hovertemplate='<b>MACD柱</b>: %{y:.2f}<extra></extra>'
            ))
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], name="MACD線", line=dict(color='orange', width=1), yaxis="y5"))
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Signal'], name="Signal線", line=dict(color='blue', width=1), yaxis="y5"))

            # 6. KD 隨機指標
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K'], name="K值", line=dict(color='orange', width=1.5), yaxis="y6"))
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D'], name="D值", line=dict(color='blue', width=1.5), yaxis="y6"))

            # 六層垂直 Domain 配置 (重新平衡比例)
            fig.update_layout(
                height=1100, hovermode="x unified", dragmode="zoom", 
                showlegend=True,
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, 
                    xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)"
                ),
                hoverlabel=dict(
                    bgcolor="rgba(17, 20, 27, 0.7)", font_size=12,
                    font_family="sans-serif", bordercolor="rgba(255, 255, 255, 0.2)",
                    align="left"
                ),
                xaxis=dict(rangeslider=dict(visible=False), type='category', dtick=20),
                yaxis1=dict(title="", domain=[0.65, 1.0], showgrid=True, gridcolor='rgba(128, 128, 128, 0.2)'),
                yaxis2=dict(title="", domain=[0.53, 0.63], showgrid=True, gridcolor='rgba(128, 128, 128, 0.2)'),
                yaxis3=dict(title="", domain=[0.41, 0.51], showgrid=True, gridcolor='rgba(128, 128, 128, 0.2)'),
                yaxis4=dict(title="", domain=[0.29, 0.39], showgrid=True, gridcolor='rgba(128, 128, 128, 0.2)'),
                yaxis5=dict(title="", domain=[0.12, 0.27], showgrid=True, gridcolor='rgba(128, 128, 128, 0.2)'),
                yaxis4_zeroline=True, yaxis4_zerolinecolor='rgba(255, 255, 255, 0.6)', yaxis4_zerolinewidth=1.5,
                yaxis6=dict(title="", domain=[0.0, 0.10], showgrid=True, gridcolor='rgba(128, 128, 128, 0.2)'),
                template="plotly_white"
            )
            
            # 1. 強制開啟原生 0 軸設定 (穩定路徑)
            fig.update_layout(
                yaxis3_zeroline=True, yaxis3_zerolinecolor='rgba(255, 255, 255, 0.6)', yaxis3_zerolinewidth=1.5,
                yaxis4_zeroline=True, yaxis4_zerolinecolor='rgba(255, 255, 255, 0.6)', yaxis4_zerolinewidth=1.5,
                yaxis5_zeroline=True, yaxis5_zerolinecolor='rgba(255, 255, 255, 0.6)', yaxis5_zerolinewidth=1.5,
            )
            # 2. 雙重保險：強制在籌碼 Y=0 處畫出虛線 + KD 輔助線
            fig.add_hline(y=0, line_dash="dot", line_color="rgba(255, 255, 255, 0.6)", line_width=1.5, yref="y3")
            fig.add_hline(y=0, line_dash="dot", line_color="rgba(255, 255, 255, 0.6)", line_width=1.5, yref="y4")
            fig.add_hline(y=0, line_dash="dot", line_color="rgba(255, 255, 255, 0.6)", line_width=1.5, yref="y5")
            # KD 超買超賣線
            fig.add_hline(y=20, line_dash="dot", line_color="rgba(255, 255, 255, 0.3)", line_width=1, yref="y6")
            fig.add_hline(y=80, line_dash="dot", line_color="rgba(255, 255, 255, 0.3)", line_width=1, yref="y6")

            # === [視覺優化補充：Annotation 垂直標題與 Crosshair] ===
            # 1. 喚醒 Y 軸水平追蹤虛線 (Crosshair Spikes) 並解除磁吸
            fig.update_yaxes(
                showspikes=True, spikemode="across", spikesnap="cursor",
                spikethickness=1, spikedash="dot", spikecolor="rgba(128, 128, 128, 0.5)"
            )
            # 2. 使用 Annotation 達成「正向直書」文字 (避開 Plotly 固定 90 度旋轉問題)
            fig.add_annotation(text="價<br>格", x=0, xref="paper", xanchor="right", xshift=-45, y=0.5, yref="y domain", showarrow=False, align="center")
            fig.add_annotation(text="成<br>交<br>量", x=0, xref="paper", xanchor="right", xshift=-45, y=0.5, yref="y2 domain", showarrow=False, align="center")
            fig.add_annotation(text="外<br>資", x=0, xref="paper", xanchor="right", xshift=-45, y=0.5, yref="y3 domain", showarrow=False, align="center")
            fig.add_annotation(text="投<br>信", x=0, xref="paper", xanchor="right", xshift=-45, y=0.5, yref="y4 domain", showarrow=False, align="center")
            fig.add_annotation(text="M<br>A<br>C<br>D", x=0, xref="paper", xanchor="right", xshift=-45, y=0.5, yref="y5 domain", showarrow=False, align="center")
            fig.add_annotation(text="K<br>D", x=0, xref="paper", xanchor="right", xshift=-45, y=0.5, yref="y6 domain", showarrow=False, align="center")

            st.plotly_chart(fig, use_container_width=True)

        # --- [Phase 7: AI 智能趨勢診斷] ---
        if ai_clicked:
            st.divider()
            with st.status("正在融合多維度數據進行 AI 趨勢分析...", expanded=True) as status:
                # 分析數據打包
                d_sum = df_plot.tail(14)[['Open', 'High', 'Low', 'Close', 'Volume']].to_string()
                i_sum = df_plot.tail(5)[['Foreign', 'Trust']].to_string()
                
                ma_stat = "均線交疊"
                try:
                    last_r = df_plot.iloc[-1]
                    s5, s20, s60 = last_r['SMA_5'], last_r['SMA_20'], last_r['SMA_60']
                    if s5 > s20 > s60: ma_stat = "多頭排列 (強勢多頭)"
                    elif s5 < s20 < s60: ma_stat = "空頭排列 (弱勢空頭)"
                except: pass

                report_text = ""
                try:
                    if IS_TESTING:
                        report_text = "### 🚀 台股趨勢分析 (模擬)\n目前技術面呈現穩定態勢，外資小幅買超。"
                        status.update(label="✅ [模擬] 生成完畢！", state="complete")
                    else:
                        g_key = st.secrets.get("GEMINI_API_KEY", "").strip()
                        if not g_key: 
                            status.update(label="❌ 缺少 API 金鑰", state="error")
                        else:
                            genai.configure(api_key=g_key)
                            # 首選穩定版 gemini-pro 以防 404
                            try: model = genai.GenerativeModel('gemini-2.5-flash')
                            except: model = genai.GenerativeModel('gemini-2.5-flash')
                            
                            p_msg = f"""
                            你是一位專精台股的資深證券分析師。請分析對象：{selected_display_name}
                            
                            1. 技術趨勢：目前均線狀態為 {ma_stat}。近期數據：\n{d_sum}
                            2. 籌碼動態：近五日法人買賣超：\n{i_sum}
                            
                            請提供專業分析回報：
                            - 【技術診斷】：分析短中長期趨勢與關鍵支撐壓力。
                            - 【籌碼面報告】：解讀外資與投信的主力心態。
                            - 【操作建議】：給出具體的投資防守策略。
                            """
                            resp = model.generate_content(p_msg)
                            report_text = resp.text
                            status.update(label="✅ AI 診斷報告已生成！", state="complete")
                            
                except Exception as e:
                    report_text = f"分析過程出錯：{e}"
                    status.update(label="❌ 分析中斷", state="error")
                
                if report_text:
                    st.info(report_text)

    else:
        st.warning(f"⚠️ 無法取得代碼【{selected_ticker}】的有效歷史數據，請確認格式。")
else:
    st.info("💡 請在側邊欄選擇股票，或手動輸入代號進行全方位籌碼分析。")

# 側邊欄腳注 (繁體中文)
st.sidebar.markdown("---")
st.sidebar.info("💡 **分析師提醒：**\n技術指標與 AI 分析僅供決策參考，投資請務必維持獨立思考並嚴格執行分批佈局。")
