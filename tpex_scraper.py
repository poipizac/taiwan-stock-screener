import requests
import pandas as pd
from datetime import datetime, timedelta
import urllib3

# 忽略不安全連線警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def scrape_tpex_institutional():
    print("🚀 啟動櫃買中心爬蟲機器人...")
    
    # 🌟 測試完畢，把日期改回「自動抓昨天」
    target_date = datetime.now() - timedelta(days=1)
    roc_year = target_date.year - 1911
    date_str = f"{roc_year}/{target_date.strftime('%m/%d')}"
    print(f"📅 準備抓取日期：{date_str}")

    url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={date_str}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, verify=False)
        data = response.json()

        if 'tables' in data and len(data['tables']) > 0:
            raw_data = data['tables'][0]['data']
            print(f"✅ 成功連線！共抓到 {len(raw_data)} 檔上櫃股票資料。")
            
            df = pd.DataFrame(raw_data)
            
            # 1. 挑選正確的欄位
            cleaned_df = df.iloc[:, [0, 1, 10, 13, 23]].copy()
            cleaned_df.columns = ['代號', '名稱', '外資買賣超', '投信買賣超', '三大法人買賣超']
            
            # 🌟 2. 關鍵清洗：把數字裡的「逗號」拿掉，並強制轉為整數 (整骨手術)
            for col in ['外資買賣超', '投信買賣超', '三大法人買賣超']:
                cleaned_df[col] = cleaned_df[col].astype(str).str.replace(',', '', regex=False).astype(int)
            
            # 3. 存檔
            filename = f"tpex_inst_{target_date.strftime('%Y%m%d')}.csv"
            cleaned_df.to_csv(filename, index=False, encoding='utf-8-sig')
            
            print(f"🎉 完美落地！資料已成功清洗並儲存為：{filename}")
        else:
            print("⚠️ 找不到 tables 資料，可能是今天沒開盤。")

    except Exception as e:
        print(f"❌ 抓取失敗，錯誤訊息：{e}")

if __name__ == "__main__":
    scrape_tpex_institutional()