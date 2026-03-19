"""
Shared utilities for AFL predictor Lambdas.
Handles secrets, DynamoDB, Squiggle API, and Discord webhooks.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import boto3
import requests

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ── Cached clients (survive warm Lambda invocations) ──────────────────────────
_secrets_cache: Optional[dict] = None
_dynamodb_table = None

# Discord colour constants (decimal)
COLOUR_BLUE   = 0x3B82F6   # predictions
COLOUR_GREEN  = 0x22C55E   # correct prediction
COLOUR_RED    = 0xEF4444   # wrong prediction
COLOUR_GOLD   = 0xF59E0B   # round opener / summary


def get_secrets() -> dict:
    global _secrets_cache
    if _secrets_cache:
        return _secrets_cache
    client = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
    response = client.get_secret_value(SecretId=os.environ["SECRET_ARN"])
    _secrets_cache = json.loads(response["SecretString"])
    logger.info("Loaded secrets from Secrets Manager")
    return _secrets_cache


def get_dynamodb_table():
    global _dynamodb_table
    if _dynamodb_table:
        return _dynamodb_table
    dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
    _dynamodb_table = dynamodb.Table(os.environ["TABLE_NAME"])
    return _dynamodb_table


# ── Squiggle AFL API ───────────────────────────────────────────────────────────
def get_upcoming_games(year: int, round_number: int) -> list[dict]:
    secrets = get_secrets()
    base_url = secrets.get("afl_api_base_url", "https://api.squiggle.com.au")
    url = f"{base_url}/?q=games;year={year};round={round_number}"
    headers = {"User-Agent": "afl-predictor-bot/1.0 (contact via github)"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json().get("games", [])


def get_completed_games(year: int, round_number: int) -> list[dict]:
    return get_upcoming_games(year, round_number)


def get_current_round(year: int) -> int:
    secrets = get_secrets()
    base_url = secrets.get("afl_api_base_url", "https://api.squiggle.com.au")
    url = f"{base_url}/?q=games;year={year};complete=!100"
    headers = {"User-Agent": "afl-predictor-bot/1.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    games = resp.json().get("games", [])
    if not games:
        return 1
    return min(g["round"] for g in games)


# ── DynamoDB helpers ───────────────────────────────────────────────────────────
def save_prediction(year: int, round_num: int, match: dict, prediction: dict, message_id: Optional[str] = None):
    table = get_dynamodb_table()
    ttl = int(time.time()) + (90 * 24 * 60 * 60)
    item = {
        "pk": f"PREDICTION#{year}#R{round_num}",
        "sk": f"MATCH#{match['hteam']}#{match['ateam']}",
        "round_year": f"{year}#R{round_num}",
        "year": year,
        "round": round_num,
        "home": match["hteam"],
        "away": match["ateam"],
        "venue": match.get("venue", ""),
        "date": match.get("date", ""),
        "predicted_winner": prediction["winner"],
        "confidence": prediction["confidence"],
        "margin_estimate": prediction.get("margin_estimate", ""),
        "reasoning": prediction["reasoning"],
        "discord_message_id": message_id or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": ttl,
    }
    table.put_item(Item=item)
    logger.info("Saved prediction: %s vs %s -> %s", match["hteam"], match["ateam"], prediction["winner"])


def get_predictions_for_round(year: int, round_num: int) -> list[dict]:
    table = get_dynamodb_table()
    response = table.query(
        IndexName="round-year-index",
        KeyConditionExpression="round_year = :ry",
        ExpressionAttributeValues={":ry": f"{year}#R{round_num}"},
    )
    return [item for item in response["Items"] if item["pk"].startswith("PREDICTION")]


def save_result(year: int, round_num: int, game: dict, prediction_correct: bool, message_id: Optional[str] = None):
    table = get_dynamodb_table()
    ttl = int(time.time()) + (90 * 24 * 60 * 60)
    hscore = int(game.get("hscore") or 0)
    ascore = int(game.get("ascore") or 0)
    if hscore > ascore:
        winner = game["hteam"]
    elif ascore > hscore:
        winner = game["ateam"]
    else:
        winner = "Draw"
    item = {
        "pk": f"RESULT#{year}#R{round_num}",
        "sk": f"MATCH#{game['hteam']}#{game['ateam']}",
        "round_year": f"{year}#R{round_num}",
        "year": year,
        "round": round_num,
        "home": game["hteam"],
        "away": game["ateam"],
        "home_score": str(hscore),
        "away_score": str(ascore),
        "actual_winner": winner,
        "prediction_correct": prediction_correct,
        "discord_message_id": message_id or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": ttl,
    }
    table.put_item(Item=item)


# ── Discord webhook helpers ────────────────────────────────────────────────────
def _post_to_discord(webhook_url: str, payload: dict, retries: int = 3) -> Optional[str]:
    """POST to a Discord webhook. Returns the message ID if wait=true is set."""
    url = webhook_url.rstrip("/") + "?wait=true"
    for attempt in range(retries):
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 1.0)
            logger.warning("Discord rate limited. Waiting %.1fs", retry_after)
            time.sleep(retry_after + 0.1)
            continue
        if resp.status_code in (200, 204):
            try:
                return str(resp.json().get("id", ""))
            except Exception:
                return None
        logger.error("Discord webhook error %s: %s", resp.status_code, resp.text[:200])
        return None
    logger.error("Discord webhook failed after %d retries", retries)
    return None


def post_embed(webhook_key: str, embed: dict, content: Optional[str] = None) -> Optional[str]:
    """Post a rich embed to Discord. webhook_key is the secrets dict key."""
    secrets = get_secrets()
    webhook_url = secrets.get(webhook_key, "")
    if not webhook_url:
        logger.error("No webhook URL for key: %s", webhook_key)
        return None
    payload: dict = {"embeds": [embed]}
    if content:
        payload["content"] = content
    message_id = _post_to_discord(webhook_url, payload)
    time.sleep(0.5)  # stay well under Discord's 5 req/s limit per webhook
    return message_id


def post_plain(webhook_key: str, content: str) -> Optional[str]:
    """Post a plain-text message to Discord."""
    secrets = get_secrets()
    webhook_url = secrets.get(webhook_key, "")
    if not webhook_url:
        logger.error("No webhook URL for key: %s", webhook_key)
        return None
    message_id = _post_to_discord(webhook_url, {"content": content})
    time.sleep(0.5)
    return message_id


# ── Embed builders ─────────────────────────────────────────────────────────────
def build_prediction_embed(
    home: str, away: str, venue: str, date: str,
    prediction: dict, match_num: int, total: int,
) -> dict:
    """Build a Discord embed for a single match prediction."""
    confidence = prediction["confidence"]
    filled = round(confidence / 20)
    bar = "🟦" * filled + "⬜" * (5 - filled)
    return {
        "title": f"🏉  {home}  vs  {away}",
        "color": COLOUR_BLUE,
        "fields": [
            {"name": "📍 Venue", "value": venue or "TBA", "inline": True},
            {"name": "📅 Date",  "value": date  or "TBA", "inline": True},
            {"name": "\u200b",   "value": "\u200b",        "inline": False},
            {
                "name": "🎯 Predicted winner",
                "value": f"**{prediction['winner']}** — {prediction.get('margin_estimate', '')}",
                "inline": False,
            },
            {
                "name": f"Confidence  {bar}  {confidence}%",
                "value": prediction["reasoning"],
                "inline": False,
            },
        ],
        "footer": {"text": f"Match {match_num} of {total}"},
    }


def build_result_embed(
    home: str, away: str,
    home_score: int, away_score: int,
    actual_winner: str,
    predicted_winner: Optional[str],
    correct: bool,
) -> dict:
    """Build a Discord embed for a single match result."""
    margin = abs(home_score - away_score)
    tick = "✅" if correct else "❌"
    colour = COLOUR_GREEN if correct else COLOUR_RED
    pred_text = (
        f"{tick} **{predicted_winner}** ({'correct!' if correct else 'wrong'})"
        if predicted_winner else "⚠️ No prediction on record"
    )
    return {
        "title": f"🏉  {home}  {home_score}  –  {away_score}  {away}",
        "color": colour,
        "fields": [
            {"name": "🏆 Winner",  "value": f"**{actual_winner}** by {margin} pts", "inline": True},
            {"name": "🤖 Our pick","value": pred_text, "inline": True},
        ],
    }
