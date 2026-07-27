import openai
import os
import sys

client = openai.OpenAI(
    api_key="sk-TA_CLE_API_ICI",
    base_url="https://api.moonshot.cn/v1"
)

# Lire le contexte Titanium V12
with open("CLAUDE.md", "r", encoding="utf-8") as f:
    context = f.read()

# Prompt de l'utilisateur
prompt = sys.argv[1] if len(sys.argv) > 1 else "Analyse le projet Titanium V12"

response = client.chat.completions.create(
    model="kimi-latest",
    messages=[
        {"role": "system", "content": f"Tu es un expert en architecture logicielle et mathématiques financières. Contexte du projet :\\n{context[:100000]}"},
        {"role": "user", "content": prompt}
    ]
)
print(response.choices[0].message.content)
