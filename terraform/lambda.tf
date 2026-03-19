# ─────────────────────────────────────────
# Lambda layer — shared Python dependencies
# (tweepy + anthropic + requests)
# Built separately via build.sh
# ─────────────────────────────────────────
resource "aws_lambda_layer_version" "dependencies" {
  filename            = "${path.module}/../build/layer.zip"
  layer_name          = "afl-predictor-deps-${var.environment}"
  compatible_runtimes = ["python3.12"]
  source_code_hash    = filebase64sha256("${path.module}/../build/layer.zip")

  lifecycle {
    create_before_destroy = true
  }
}

# ─────────────────────────────────────────
# Lambda: predict_matches
# Runs Thursday — fetches fixtures, calls
# Claude, saves predictions, tweets thread
# ─────────────────────────────────────────
data "archive_file" "predict_matches" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/predict_matches"
  output_path = "${path.module}/../build/predict_matches.zip"
}

resource "aws_lambda_function" "predict_matches" {
  filename         = data.archive_file.predict_matches.output_path
  function_name    = "afl-predictor-predict-${var.environment}"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb
  source_code_hash = data.archive_file.predict_matches.output_base64sha256
  layers           = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      SECRET_ARN   = aws_secretsmanager_secret.afl_predictor.arn
      TABLE_NAME   = aws_dynamodb_table.predictions.name
      ENVIRONMENT  = var.environment
      LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.lambda_basic]
}

resource "aws_cloudwatch_log_group" "predict_matches" {
  name              = "/aws/lambda/${aws_lambda_function.predict_matches.function_name}"
  retention_in_days = 30
}

# ─────────────────────────────────────────
# Lambda: fetch_results
# Runs Monday — gets scores, compares to
# predictions, tweets results recap
# ─────────────────────────────────────────
data "archive_file" "fetch_results" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/fetch_results"
  output_path = "${path.module}/../build/fetch_results.zip"
}

resource "aws_lambda_function" "fetch_results" {
  filename         = data.archive_file.fetch_results.output_path
  function_name    = "afl-predictor-results-${var.environment}"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb
  source_code_hash = data.archive_file.fetch_results.output_base64sha256
  layers           = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      SECRET_ARN   = aws_secretsmanager_secret.afl_predictor.arn
      TABLE_NAME   = aws_dynamodb_table.predictions.name
      ENVIRONMENT  = var.environment
      LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.lambda_basic]
}

resource "aws_cloudwatch_log_group" "fetch_results" {
  name              = "/aws/lambda/${aws_lambda_function.fetch_results.function_name}"
  retention_in_days = 30
}

# ─────────────────────────────────────────
# EventBridge — Thursday prediction trigger
# ─────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "predict_schedule" {
  name                = "afl-predictor-predict-${var.environment}"
  description         = "Trigger AFL predictions on Thursday morning AEST"
  schedule_expression = var.predict_cron
}

resource "aws_cloudwatch_event_target" "predict_schedule" {
  rule      = aws_cloudwatch_event_rule.predict_schedule.name
  target_id = "predict-lambda"
  arn       = aws_lambda_function.predict_matches.arn
}

resource "aws_lambda_permission" "predict_schedule" {
  statement_id  = "AllowEventBridgePredict"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.predict_matches.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.predict_schedule.arn
}

# ─────────────────────────────────────────
# EventBridge — Monday results trigger
# ─────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "results_schedule" {
  name                = "afl-predictor-results-${var.environment}"
  description         = "Trigger AFL results recap on Monday morning AEST"
  schedule_expression = var.results_cron
}

resource "aws_cloudwatch_event_target" "results_schedule" {
  rule      = aws_cloudwatch_event_rule.results_schedule.name
  target_id = "results-lambda"
  arn       = aws_lambda_function.fetch_results.arn
}

resource "aws_lambda_permission" "results_schedule" {
  statement_id  = "AllowEventBridgeResults"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetch_results.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.results_schedule.arn
}
