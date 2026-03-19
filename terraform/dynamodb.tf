# ─────────────────────────────────────────
# DynamoDB — predictions + results store
# ─────────────────────────────────────────
resource "aws_dynamodb_table" "predictions" {
  name         = "afl-predictor-${var.environment}"
  billing_mode = "PAY_PER_REQUEST" # free at low volume
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "round_year"
    type = "S"
  }

  # GSI to query all matches for a given round/year
  global_secondary_index {
    name            = "round-year-index"
    hash_key        = "round_year"
    range_key       = "sk"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "afl-predictor-${var.environment}"
  }
}

# ─────────────────────────────────────────
# DynamoDB schema (enforced in code):
#
# Prediction record:
#   pk  = "PREDICTION#2025#R1"           (season + round)
#   sk  = "MATCH#Hawthorn#Brisbane"       (home#away)
#   round_year = "2025#R1"               (for GSI)
#   home, away, venue, date
#   predicted_winner, confidence, margin_estimate, reasoning
#   tweet_id (prediction tweet)
#   created_at, expires_at (TTL ~90 days)
#
# Result record:
#   pk  = "RESULT#2025#R1"
#   sk  = "MATCH#Hawthorn#Brisbane"
#   actual_winner, home_score, away_score
#   prediction_correct (bool)
#   result_tweet_id
#   created_at
# ─────────────────────────────────────────
