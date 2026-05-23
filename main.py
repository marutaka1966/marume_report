import os
import smtplib
from email.mime.text import MIMEText
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

prompt = """
丸目さん専用の投資・世界情勢レポートを作ってください。

監視対象：
日本株：2432, 4784, 6036, 8031, 8424, 8729, 9104, 9331, 9432, NTT
テーマ：AI、半導体、ロボット、銅、LNG、原発、海運、EV、Tesla、データセンター
地政学：イラン、台湾海峡、中国、ウクライナ、米金利、為替、原油

出力：
1. 今日の重要ニュース
2. 保有株への影響
3. 買いチャンス
4. 売り・縮小注意
5. 明日見るべき指標

日本語で、結論を先に、短く実務的に。
"""

response = client.responses.create(
    model="gpt-5.5",
    input=prompt
)

report = response.output_text

msg = MIMEText(report, "plain", "utf-8")
msg["Subject"] = "【丸目投資レポート】"
msg["From"] = os.environ["GMAIL_USER"]
msg["To"] = os.environ["GMAIL_USER"]

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
    server.send_message(msg)

print("メール送信完了")
print(os.environ["GMAIL_USER"])
raise Exception("STOP")
