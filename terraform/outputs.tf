output "predict_lambda_arn" {
  description = "ARN of the predict_matches Lambda"
  value       = aws_lambda_function.predict_matches.arn
}

output "results_lambda_arn" {
  description = "ARN of the fetch_results Lambda"
  value       = aws_lambda_function.fetch_results.arn
}

output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.predictions.name
}

output "secret_arn" {
  description = "Secrets Manager ARN"
  value       = aws_secretsmanager_secret.afl_predictor.arn
  sensitive   = true
}

output "predict_schedule" {
  description = "Cron schedule for predictions"
  value       = var.predict_cron
}

output "results_schedule" {
  description = "Cron schedule for results"
  value       = var.results_cron
}

output "cloudwatch_log_groups" {
  description = "CloudWatch log group names"
  value = {
    predict = aws_cloudwatch_log_group.predict_matches.name
    results = aws_cloudwatch_log_group.fetch_results.name
  }
}
