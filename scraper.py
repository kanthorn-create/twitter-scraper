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
        "maxResults": 200,
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


def is_about_treatment(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{
            "role": "user",
            "content": f"tweet นี้เกี่ยวกับหัตถการความงาม (เช่น botox, filler, laser, mesotherapy, thread lift, hifu, skinbooster ฯลฯ) หรือไม่? ตอบแค่ YES หรือ NO\n\n{text}"
        }]
    )
    return msg.content[0].text.strip().upper() == "YES"


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

        # Highlight rows about treatments in green
        green = {"red": 0.714, "green": 0.843, "blue": 0.659}
        for i, row in enumerate(new_rows):
            text = row[4]  # text column
            if is_about_treatment(text):
                row_num = start_row + i
                ws.format(f"A{row_num}:K{row_num}", {"backgroundColor": green})
                print(f"  Highlighted row {row_num} (treatment-related)")
    else:
        print("No new tweets to add")


if __name__ == "__main__":
    main()
