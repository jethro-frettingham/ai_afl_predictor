# ─────────────────────────────────────────
# Secrets Manager — all sensitive keys
# ─────────────────────────────────────────
resource "aws_secretsmanager_secret" "afl_predictor" {
  name                    = "afl-predictor/${var.environment}/secrets"
  description             = "API keys for AFL predictor — Anthropic + X/Twitter"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "afl_predictor" {
  secret_id = aws_secretsmanager_secret.afl_predictor.id

  secret_string = jsonencode({
    anthropic_api_key            = var.anthropic_api_key
    discord_predictions_webhook  = var.discord_predictions_webhook
    discord_results_webhook      = var.discord_results_webhook
    afl_api_base_url             = var.afl_api_base_url
  })
}
