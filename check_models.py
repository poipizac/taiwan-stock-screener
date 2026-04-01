import google.generativeai as genai

# 替換成你的真實 API Key (保留雙引號)
API_KEY = "你的_API_KEY" 

genai.configure(api_key=API_KEY)

print("🔍 正在連線 Google 伺服器，掃描支援的模型...")
print("-" * 50)

# 呼叫 ListModels 並篩選出支援文字生成的模型
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ 找到可用模型: {m.name}")
    print("-" * 50)
    print("掃描完成！請把上面顯示的其中一個名字複製下來。")
except Exception as e:
    print(f"❌ 掃描失敗，錯誤訊息: {e}")