import os
import json
import time
from datetime import datetime, timezone

from apify_client import ApifyClient
import gspread
from google.oauth2.service_account import Credentials

APIFY_TOKEN = os.environ["APIFY_TOKEN"]
ACTOR_ID = "30kuelAvXhDxx4hB8"
COMMUNITY_ID = "1508883951074439169"

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "Tweets"

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
        "communityIds": [COMMUNITY_ID],
        "maxTweets": 200,
        "addUserInfo": True,
    })
    items = list(client.dataset(run.default_dataset_id).iterate_items())
    print(f"Fetched {len(items)} tweets from Apify")
    return items


def get_sheet():
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=5000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    return ws


def get_existing_ids(ws):
    try:
        col = ws.col_values(1)[1:]  # skip header
        return set(col)
    except Exception:
        return set()


def tweet_to_row(tweet, scraped_at):
    author = tweet.get("author", {})
    return [
        tweet.get("id", ""),
        tweet.get("createdAt", ""),
        author.get("userName", ""),
        author.get("name", ""),
        tweet.get("text", ""),
        tweet.get("retweetCount", 0),
        tweet.get("replyCount", 0),
        tweet.get("likeCount", 0),
        tweet.get("quoteCount", 0),
        tweet.get("url", f"https://twitter.com/i/web/status/{tweet.get('id', '')}"),
        scraped_at,
    ]


def main():
    print("Starting scrape...")
    tweets = run_actor()

    ws = get_sheet()
    existing_ids = get_existing_ids(ws)
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    new_rows = []
    for tweet in tweets:
        tid = str(tweet.get("id", ""))
        if tid and tid not in existing_ids:
            new_rows.append(tweet_to_row(tweet, scraped_at))

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Added {len(new_rows)} new tweets to sheet")
    else:
        print("No new tweets to add")


if __name__ == "__main__":
    main()
