import os
import smtplib
import feedparser

from urllib.parse import quote
from email.mime.text import MIMEText
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def get_news():
    queries = [
        "イラン 原油 LNG",
        "台湾海峡 半導体",
        "AI 半導体 データセンター",
        "Tesla EV",
        "海運 紅海 ホルムズ海峡",
        "銅価格 商社",
        "日本株 三井物産 商船三井 NTT"
    ]

    news_items = []

    for q in queries:
        try:
            encoded_q = quote(q)

            url = (
                f"https://news.google.com/rss/search?"
                f"q={encoded_q}&hl=ja&gl=JP&ceid=JP:ja"
            )

            feed = feedparser.parse(url)

            news_items.append(f"\n【検索テーマ】{q}")

            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                published = entry.get("published", "")
                link = entry.get("link", "")

                news_items.append(
                    f"- {title}\n"
                    f"  {published}\n"
                    f"  {link}"
                )

        except Exception as e:
            news_items.append(
                f"【検索テーマ】{q} 取得失敗: {e}"
            )

    return "\n".join(news_items)


news_data = get_news()

prompt = f"""
丸目さん専用の投資・世界情勢レポートを作成してください。

以下のニュースを最優先で分析してください。
一般論は禁止です。

ニュース:
{news_data}

監視対象

保有株:
2432
4784
6036
8031
8424
8729
9104
9331
9432
NTT

テーマ:
AI
半導体
ロボット
銅
LNG
原発
海運
EV
Tesla
データセンター

地政学:
イラン
台湾海峡
中国
ウクライナ
米金利
為替
原油

出力:

1. 今日の重要ニュース
2. 保有株への影響
3. 買いチャンス
4. 売り・縮小注意
5. 明日見るべき指標

日本語で。
結論を最初に。
短く実務的に。
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
    server.login(
        os.environ["GMAIL_USER"],
        os.environ["GMAIL_APP_PASSWORD"]
    )
    server.send_message(msg)

print("メール送信完了")
print(os.environ["GMAIL_USER"])
