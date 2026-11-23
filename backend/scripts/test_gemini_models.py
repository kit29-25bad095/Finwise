from dotenv import dotenv_values
import os
from google import genai

envs = dotenv_values(".env")
key = envs.get("GEMINI_API_KEY") or envs.get("AI_API_KEY") or os.getenv("GEMINI_API_KEY")
print("Has key:", bool(key))
if key:
    client = genai.Client(api_key=key)
    for model_name in ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash", "gemini-3.1-flash-lite"]:
        try:
            resp = client.models.generate_content(model=model_name, contents="hello")
            print(f"{model_name} SUCCESS: {resp.text.strip()[:40]}")
        except Exception as e:
            print(f"{model_name} ERROR: {e}")
