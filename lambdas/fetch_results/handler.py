"""
fetch_results/handler.py

Runs Monday morning AEST via EventBridge.
1. Fetches completed game scores from Squiggle API
2. Loads stored predictions from DynamoDB
3. Compares predictions vs actuals
4. Asks Claude to write a witty recap
5. Posts results embeds to Discord #results channel
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import anthropic

from utils import (
    COLOUR_GOLD,
    get_secrets,
    get_completed_games,
    get_current_round,
    get_predictions_for_round,
    save_result,
    post_embed,
    post_plain,
    build_result_embed,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

WEBHOOK_KEY = "discord_results_webhook"


def find_prediction(game: dict, predictions: list[dict]) -> Optional[dict]:
    """Match a completed game to its stored prediction."""
    for pred in predictions:
        if pred.get("home") == game.get("hteam") and pred.get("away") == game.get("ateam"):
            return pred
    return None


def determine_winner(game: dict) -> str:
    hscore = int(game.get("hscore") or 0)
    ascore = int(game.get("ascore") or 0)
    if hscore > ascore:
        return game["hteam"]
    if ascore > hscore:
        return game["ateam"]
    return "Draw"


def generate_recap(round_num: int, year: int, results: list[dict], correct: int, total: int) -> str:
    """Ask Claude to write a witty one-paragraph Discord recap."""
    secrets = get_secrets()
    client = anthropic.Anthropic(api_key=secrets["anthropic_api_key"])

    summary = "\n".join([
        f"- {r['home']} vs {r['away']}: actual winner {r['actual_winner']} "
        f"(predicted {r['predicted_winner']}) - {'CORRECT' if r['correct'] else 'WRONG'}"
        for r in results
    ])

    prompt = f"""You are a witty AFL commentator writing a short Discord message recap of your AI prediction results.

Round {round_num}, {year} results vs predictions:
{summary}

Score: {correct}/{total} correct

Write a short punchy paragraph (max 300 chars) that:
- Is honest about the score {correct}/{total}
- Has personality, humour and AFL flavour
- Mentions the funniest wrong prediction if there is one

Just the text, no quotes, no formatting."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def lambda_handler(event, context):
    """Entry point - triggered by EventBridge on Monday morning AEST."""
    now = datetime.now(timezone.utc)
    year = now.year

    logger.info("Starting results run - %s", now.isoformat())

    # The round that just finished is one behind the upcoming round
    try:
        upcoming = get_current_round(year)
        round_num = max(1, upcoming - 1)
        logger.info("Fetching results for year=%s round=%s", year, round_num)
    except Exception as e:
        logger.error("Failed to determine round: %s", e)
        raise

    # Fetch completed games
    try:
        all_games = get_completed_games(year, round_num)
        games = [g for g in all_games if int(g.get("complete", 0)) == 100]
        if not games:
            logger.warning("No completed games for round %s", round_num)
            return {"status": "no_completed_games", "round": round_num}
        logger.info("Found %d completed games", len(games))
    except Exception as e:
        logger.error("Failed to fetch results: %s", e)
        raise

    # Load stored predictions
    predictions = get_predictions_for_round(year, round_num)
    logger.info("Found %d stored predictions", len(predictions))

    # Compare and build result data
    results_data = []
    correct_count = 0

    for game in games:
        prediction = find_prediction(game, predictions)
        winner = determine_winner(game)
        correct = bool(prediction and prediction["predicted_winner"] == winner)
        if correct:
            correct_count += 1

        results_data.append({
            "home": game["hteam"],
            "away": game["ateam"],
            "actual_winner": winner,
            "predicted_winner": prediction["predicted_winner"] if prediction else None,
            "correct": correct,
        })

    total = len(games)
    accuracy_pct = int((correct_count / total) * 100) if total else 0

    # Generate witty opener via Claude
    try:
        recap_text = generate_recap(round_num, year, results_data, correct_count, total)
    except Exception as e:
        logger.warning("Claude recap failed, using fallback: %s", e)
        recap_text = f"Round {round_num} results are in! We went {correct_count}/{total} correct ({accuracy_pct}%)."

    # Opening summary embed
    colour = COLOUR_GOLD
    post_embed(
        WEBHOOK_KEY,
        embed={
            "title": f":football: AFL {year} - Round {round_num} Results",
            "description": recap_text,
            "color": colour,
            "fields": [
                {"name": "Correct picks", "value": f"**{correct_count} / {total}**", "inline": True},
                {"name": "Accuracy",      "value": f"**{accuracy_pct}%**",           "inline": True},
            ],
            "footer": {"text": f"Round {round_num + 1} predictions drop Thursday morning"},
        },
    )

    # One embed per game result
    for idx, (game, result) in enumerate(zip(games, results_data)):
        prediction = find_prediction(game, predictions)
        embed = build_result_embed(
            home=game["hteam"],
            away=game["ateam"],
            home_score=int(game.get("hscore") or 0),
            away_score=int(game.get("ascore") or 0),
            actual_winner=result["actual_winner"],
            predicted_winner=result["predicted_winner"],
            correct=result["correct"],
        )
        message_id = post_embed(WEBHOOK_KEY, embed)
        save_result(year, round_num, game, result["correct"], message_id=message_id)

    logger.info(
        "Results run complete - %d/%d correct, %d embeds posted",
        correct_count, total, len(games),
    )

    return {
        "status": "success",
        "year": year,
        "round": round_num,
        "total_games": total,
        "correct_predictions": correct_count,
        "accuracy_pct": accuracy_pct,
    }
