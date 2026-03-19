"""
predict_matches/handler.py

Runs Thursday morning AEST via EventBridge.
1. Fetches upcoming AFL fixtures from Squiggle API
2. Fetches live form, player stats, and H2H for each match
3. Calls Claude with real data to predict each match
4. Posts rich embeds to Discord #predictions channel
5. Saves predictions to DynamoDB
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
    get_team_form,
    get_top_players,
    get_head_to_head,
    save_prediction,
    post_embed,
    post_plain,
    build_prediction_embed,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

WEBHOOK_KEY = "discord_predictions_webhook"


def format_form(form: dict, team: str) -> str:
    """Format team form data into a readable string for the prompt."""
    if not form:
        return f"{team}: no form data available"
    results_str = ", ".join(form.get("last_5_results", []))
    return (
        f"{team}: {form['wins_last_5']}W-{form['losses_last_5']}L last 5 games | "
        f"Avg score: {form['avg_score_for']} for, {form['avg_score_against']} against | "
        f"Results: {results_str}"
    )


def format_players(players: list[dict], team: str) -> str:
    """Format top player stats into a readable string for the prompt."""
    if not players:
        return f"{team}: no player data available"
    player_lines = ", ".join(
        f"{p['name']} (avg {p['avg_score']} SC, {p['games']} games)"
        for p in players
    )
    return f"{team} top players: {player_lines}"


def call_claude(
    home: str,
    away: str,
    venue: str,
    year: int,
    round_num: int,
    home_form: dict,
    away_form: dict,
    home_players: list[dict],
    away_players: list[dict],
    h2h: list[str],
) -> dict:
    """Ask Claude to predict a match using live form + player data."""
    secrets = get_secrets()
    client = anthropic.Anthropic(api_key=secrets["anthropic_api_key"])

    h2h_str = "\n".join(h2h) if h2h else "No recent head-to-head data available"

    prompt = f"""You are an expert AFL analyst. Predict the winner of this match using the live data provided below.

MATCH: {home} (home) vs {away} (away)
VENUE: {venue}
SEASON: {year}, Round {round_num}

RECENT FORM (last 5 games):
{format_form(home_form, home)}
{format_form(away_form, away)}

TOP PLAYERS BY FANTASY SCORE:
{format_players(home_players, home)}
{format_players(away_players, away)}

HEAD-TO-HEAD (recent):
{h2h_str}

Use ALL of the above data in your reasoning. Specifically call out:
- Which team is in better form and by how much
- Any standout players likely to influence the result
- What the H2H history suggests
- How much home ground advantage matters at {venue}

For confidence, use the FULL range based on the actual data:
- 55-60% = genuinely even, form and H2H are close
- 61-70% = slight lean based on one or two factors
- 71-80% = clear favourite based on form or H2H
- 81-90% = dominant form advantage or big H2H edge
- 91-99% = one team is significantly better across all metrics right now
DO NOT default to 65-70%. Let the data drive the number.

Respond ONLY with valid JSON (no markdown, no backticks, no preamble):
{{
  "winner": "exact team name as given above",
  "confidence": 84,
  "margin_estimate": "by 15-25 points",
  "reasoning": "3 sentence explanation that references the actual form, player, or H2H data above"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def lambda_handler(event, context):
    """Entry point - triggered by EventBridge on Thursday morning AEST."""
    now = datetime.now(timezone.utc)
    year      = event.get("year_override") or now.year
    round_num = event.get("round_override") or None

    logger.info("Starting prediction run - %s", now.isoformat())

    try:
        if not round_num:
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
                "The AI analyst has studied the form guide, crunched the player stats, "
                "and checked the head-to-head records. Here's how this week is going to go...\n\n"
                f"**{len(games)} matches** - predictions below"
            ),
            "color": COLOUR_GOLD,
            "footer": {"text": "Powered by live form + player data | Results recap drops Monday"},
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
            # Fetch live data for both teams in parallel-ish
            logger.info("Fetching live data for %s vs %s", home, away)
            home_form    = get_team_form(home, year, round_num)
            away_form    = get_team_form(away, year, round_num)
            home_players = get_top_players(home, year)
            away_players = get_top_players(away, year)
            h2h          = get_head_to_head(home, away, year)

            logger.info(
                "Data fetched - home form: %s, away form: %s, H2H: %d games",
                f"{home_form.get('wins_last_5', '?')}W" if home_form else "none",
                f"{away_form.get('wins_last_5', '?')}W" if away_form else "none",
                len(h2h),
            )

            prediction = call_claude(
                home, away, venue, year, round_num,
                home_form, away_form,
                home_players, away_players,
                h2h,
            )

            logger.info(
                "Predicted %s vs %s -> %s (%d%%)",
                home, away, prediction["winner"], prediction["confidence"],
            )

            embed = build_prediction_embed(home, away, venue, date, prediction, i, len(games))
            message_id = post_embed(WEBHOOK_KEY, embed)

            predictions_made.append((game, prediction, message_id))
            time.sleep(0.5)

        except Exception as e:
            logger.error("Failed to predict %s vs %s: %s", home, away, e)
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
