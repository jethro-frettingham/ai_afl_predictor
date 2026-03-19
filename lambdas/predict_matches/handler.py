"""
predict_matches/handler.py

Runs Thursday morning AEST via EventBridge.
1. Fetches upcoming AFL fixtures from Squiggle API
2. Calls Claude to predict each match
3. Posts rich embeds to Discord #predictions channel
4. Saves predictions to DynamoDB
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import anthropic

from utils import (
    COLOUR_GOLD,
    get_secrets,
    get_upcoming_games,
    get_current_round,
    save_prediction,
    post_embed,
    post_plain,
    build_prediction_embed,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

WEBHOOK_KEY = "discord_predictions_webhook"


def call_claude(home: str, away: str, venue: str, year: int, round_num: int) -> dict:
    secrets = get_secrets()
    client = anthropic.Anthropic(api_key=secrets["anthropic_api_key"])

    prompt = f"""You are an expert AFL analyst with deep knowledge of Australian Rules Football.
Predict the winner of this AFL match and explain your reasoning concisely.

Match details:
- Home team: {home}
- Away team: {away}
- Venue: {venue}
- Season: {year}, Round {round_num}

Consider: home ground advantage, recent form, head-to-head history, key players,
known injuries or suspensions, and playing conditions.

For the confidence score, use the FULL range realistically:
- 55-60% = genuine coin flip, very even match
- 61-70% = slight lean, could go either way
- 71-80% = clear favourite but upset very possible
- 81-90% = strong favourite, would be a big surprise if they lost
- 91-99% = massive mismatch, one team is clearly far superior right now
DO NOT default to 65-70% for every match. A top-4 team hosting a bottom-4 team
should be 80-90%+. A genuine 50/50 derby should be 55-58%.

Respond ONLY with valid JSON (no markdown, no backticks, no preamble):
{{
  "winner": "exact team name as given above",
  "confidence": 84,
  "margin_estimate": "by 15-25 points",
  "reasoning": "2-3 sentence explanation referencing specific reasons like ladder position, home ground, recent form or head-to-head"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def lambda_handler(event, context):
    """Entry point - triggered by EventBridge on Thursday morning AEST."""
    now = datetime.now(timezone.utc)
    year = now.year

    logger.info("Starting prediction run - %s", now.isoformat())

    try:
        round_num = get_current_round(year)
        logger.info("Predicting year=%s round=%s", year, round_num)
    except Exception as e:
        logger.error("Failed to determine current round: %s", e)
        raise

    try:
        games = get_upcoming_games(year, round_num)
        if not games:
            logger.warning("No games found for round %s", round_num)
            return {"status": "no_games", "round": round_num}
        logger.info("Found %d games for round %s", len(games), round_num)
    except Exception as e:
        logger.error("Failed to fetch fixtures: %s", e)
        raise

    # Opening announcement embed
    post_embed(
        WEBHOOK_KEY,
        embed={
            "title": f":football: AFL {year} - Round {round_num} Predictions",
            "description": (
                "The AI analyst has studied the tape, checked the stats, and "
                "consulted the football gods. Here's how this week is going to go...\n\n"
                f"**{len(games)} matches** - predictions below"
            ),
            "color": COLOUR_GOLD,
            "footer": {"text": "Results recap drops Monday morning"},
        },
    )

    predictions_made = []

    for i, game in enumerate(games, 1):
        home  = game.get("hteam", "TBA")
        away  = game.get("ateam", "TBA")
        venue = game.get("venue", "TBA")
        date  = game.get("date", "")

        if home == "TBA" or away == "TBA":
            logger.warning("Skipping game with missing team info: %s", game)
            continue

        try:
            prediction = call_claude(home, away, venue, year, round_num)
            logger.info(
                "Predicted %s vs %s -> %s (%d%%)",
                home, away, prediction["winner"], prediction["confidence"],
            )

            embed = build_prediction_embed(home, away, venue, date, prediction, i, len(games))
            message_id = post_embed(WEBHOOK_KEY, embed)

            predictions_made.append((game, prediction, message_id))
            time.sleep(0.5)

        except Exception as e:
            import traceback
            logger.error("Failed to predict %s vs %s: %s\n%s", home, away, e, traceback.format_exc())
            post_plain(WEBHOOK_KEY, f"**{home} vs {away}** - prediction unavailable this week.")

    # Save all to DynamoDB
    for game, prediction, message_id in predictions_made:
        save_prediction(year, round_num, game, prediction, message_id=message_id)

    post_plain(
        WEBHOOK_KEY,
        f"That's all {len(predictions_made)} predictions for Round {round_num}!\n"
        "Good luck everyone - may the best algorithm win.",
    )

    logger.info("Prediction run complete - %d predictions posted to Discord", len(predictions_made))

    return {
        "status": "success",
        "year": year,
        "round": round_num,
        "predictions_made": len(predictions_made),
    }
