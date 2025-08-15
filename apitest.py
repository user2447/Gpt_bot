from openai import OpenAI

# 🔹 API kalitingni shu yerga yoz
client = OpenAI(api_key="SENING_API_KEYINGNI_BU_YERGA_YOZ")

try:
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",  # Xohlasang "gpt-4o-mini" qilsa ham bo‘ladi
        messages=[
            {"role": "user", "content": "Salom, sen meni eshityapsanmi?"}
        ]
    )

    print("✅ API ishlayapti!")
    print("Javob:", response.choices[0].message.content)

except Exception as e:
    print("❌ Xato:", e)
