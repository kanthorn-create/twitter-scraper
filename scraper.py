import os
import json
import time
from datetime import datetime, timezone

import anthropic
from apify_client import ApifyClient
import gspread
from google.oauth2.service_account import Credentials

APIFY_TOKEN = os.environ["APIFY_TOKEN"]
ACTOR_ID = "30kuelAvXhDxx4hB8"
COMMUNITY_ID = "1508883951074439169"

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "tweet_id", "created_at", "author_username", "author_name",
    "text", "retweet_count", "reply_count", "like_count", "quote_count",
    "url", "scraped_at",
]


def run_actor():
    client = ApifyClient(APIFY_TOKEN)
    run = client.actor(ACTOR_ID).call(run_input={
        "community_id": COMMUNITY_ID,
        "maxResults": 50,
    })
    items = list(client.dataset(run.default_dataset_id).iterate_items())
    print(f"Fetched {len(items)} tweets from Apify")
    return items


def get_sheet(sheet_name):
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=5000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    return ws


def get_existing_ids(ws):
    try:
        col = ws.col_values(1)[1:]  # skip header
        return set(col)
    except Exception:
        return set()


def classify_treatments(texts):
    """Classify all tweets in a single API call. Returns list of booleans."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                "tweets ต่อไปนี้แต่ละอันเข้าข่ายหัตถการความงามหรือไม่?\n"
                "ให้นับว่าใช่ถ้า tweet พูดถึง:\n"
                "- เครื่องมือหรืออุปกรณ์หัตถการ (เช่น เข็ม, cannula, เครื่อง laser, HIFU, RF)\n"
                "- ชื่อหัตถการเฉพาะ (botox, filler, thread lift, mesotherapy, skinbooster, PRP, fat dissolve ฯลฯ)\n"
                "- คำถามหรือปัญหาที่เกิดจากการทำหัตถการ (เช่น บวม ช้ำ นูน แข็ง หลังทำ)\n"
                "- การแนะนำหรือรีวิวหัตถการ\n\n"
                "ไม่นับถ้าพูดถึงแค่ skincare ทั่วไป ครีม เซรั่ม หรือเมคอัพ\n\n"
                "ตอบเป็นตัวเลขที่ใช่เท่านั้น คั่นด้วย comma เช่น: 1,3,5\n"
                "ถ้าไม่มีเลยให้ตอบ: NONE\n\n"
                + numbered
            )
        }]
    )
    result = msg.content[0].text.strip()
    if result.upper() == "NONE":
        return [False] * len(texts)
    matched = set(int(x.strip()) for x in result.split(",") if x.strip().isdigit())
    return [i + 1 in matched for i in range(len(texts))]


def tweet_to_row(tweet, scraped_at):
    tid = tweet.get("tweet_id", "")
    return [
        tid,
        tweet.get("created_at", ""),
        tweet.get("screen_name", ""),
        tweet.get("author", {}).get("name", ""),
        tweet.get("text", ""),
        tweet.get("retweets", 0),
        tweet.get("replies", 0),
        tweet.get("favorites", 0),
        tweet.get("quotes", 0),
        f"https://twitter.com/i/web/status/{tid}",
        scraped_at,
    ]


def main():
    print("Starting scrape...")
    tweets = run_actor()

    sheet_name = datetime.now(timezone.utc).strftime("%Y-%m")
    ws = get_sheet(sheet_name)
    existing_ids = get_existing_ids(ws)
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    new_rows = []
    for tweet in tweets:
        tid = str(tweet.get("tweet_id", ""))
        if tid and tid not in existing_ids:
            new_rows.append(tweet_to_row(tweet, scraped_at))

    if new_rows:
        start_row = len(ws.get_all_values()) + 1
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Added {len(new_rows)} new tweets to sheet")

        # Classify all tweets in 1 API call then highlight
        texts = [row[4] for row in new_rows]
        results = classify_treatments(texts)
        green = {"red": 0.714, "green": 0.843, "blue": 0.659}
        highlighted = 0
        for i, is_treatment in enumerate(results):
            if is_treatment:
                row_num = start_row + i
                ws.format(f"A{row_num}:K{row_num}", {"backgroundColor": green})
                highlighted += 1
        print(f"Highlighted {highlighted} treatment-related tweets")
    else:
        print("No new tweets to add")


if __name__ == "__main__":
    main()
