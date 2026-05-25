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
        "日本株 三井物産 商船三井 NTT",
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

重要ルール：
- ニュースの日付が古いものは「過去材料」と明記する。
- 本日または直近24〜72時間のニュースを優先する。
- 確認できない事実を断定しない。
- 「攻撃」「封鎖」「急騰」など市場影響が大きい表現は、ニュース本文に明示がある場合だけ使う。
- ニュースタイトルだけで断定せず、保有株への影響は慎重に書く。
- 最後に「今日の実務判断」を必ず書く。

ニュース:
{news_data}

保有株：
2432 DeNA
4784 GMO系
6036 KeePer技研
8031 三井物産
8424 芙蓉総合リース
8729 ソニーFG
9104 商船三井
9331 キャスター
9432 NTT

重点テーマ：
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

地政学：
イラン
台湾海峡
中国
ウクライナ
米金利
為替
原油

出力形式：

# 結論

# 1. 今日の重要ニュース

# 2. 保有株への影響

# 3. 買いチャンス

# 4. 売り・縮小注意

# 5. 明日見るべき指標

# 6. 今日の実務判断

# 7. 保有株別サマリー

以下の表形式で必ず出力してください。

| No | コード | 略称 | 判断 | サマリー |
|----|------|------|------|------|

判断は必ず
- 買い
- 継続
- 縮小
- 売り注意

のいずれか。

サマリーは20文字以内で簡潔に。

対象銘柄：

1. 2432 DeNA
2. 4784 GMO系
3. 6036 KeePer
4. 8031 三井物産
5. 8424 芙蓉リース
6. 8729 ソニーFG
7. 9104 商船三井
8. 9331 キャスター
9. 9432 NTT

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
