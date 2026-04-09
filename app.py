@st.cache_data(ttl=3600)
def get_institutional_data(ticker, token=""):
    # 診斷 A：確認進入函數
    # st.write(f"🔍 開始抓取法人資料：{ticker}") 
    
    if ".TWO" in ticker.upper():
        return pd.DataFrame() 
        
    dl = DataLoader()
    
    # 診斷 B：確認 Token 有沒有進來
    if token:
        # st.write(f"🔑 Token 已偵測，嘗試登入...")
        try:
            dl.login_by_token(api_token=token.strip())
        except Exception as e:
            st.error(f"❌ Token 登入失敗：{e}")
    else:
        st.warning("⚠️ 目前處於「匿名模式」，未偵測到 Token。")

    try:
        # 診斷 C：確認傳給 FinMind 的代號
        clean_id = ticker.replace('.TW', '')
        # st.write(f"🚀 正向 FinMind 請求代號：{clean_id}")
        
        df = dl.request_data(
            dataset='TaiwanStockInstitutionalInvestorsBuySell', 
            stock_id=clean_id,
            start_date=(TODAY - timedelta(days=360)).strftime("%Y-%m-%d"),
            end_date=TODAY.strftime("%Y-%m-%d")
        )
        
        if df is None or df.empty:
            st.error("📉 API 回傳了空盒子（None 或 Empty）。")
            return pd.DataFrame()
            
        # st.success(f"✅ 成功抓到 {len(df)} 筆法人資料！")
        return df
    except Exception as e:
        st.error(f"❌ API 請求過程發生崩潰：{e}")
        return pd.DataFrame()