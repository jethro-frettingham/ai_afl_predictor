variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-southeast-2" # Sydney — closest to Brisbane
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude"
  type        = string
  sensitive   = true
}

variable "discord_predictions_webhook" {
  description = "Discord webhook URL for the #predictions channel"
  type        = string
  sensitive   = true
}

variable "discord_results_webhook" {
  description = "Discord webhook URL for the #results channel (can be same as predictions)"
  type        = string
  sensitive   = true
}

variable "afl_api_base_url" {
  description = "Base URL for AFL scores API (squiggle.com.au)"
  type        = string
  default     = "https://api.squiggle.com.au"
}

variable "predict_cron" {
  description = "Cron for predictions — Thursday 11pm UTC = Friday 9am AEST"
  type        = string
  default     = "cron(0 23 ? * THU *)"
}

variable "results_cron" {
  description = "Cron for results — Monday 11pm UTC = Tuesday 9am AEST"
  type        = string
  default     = "cron(0 23 ? * MON *)"
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 120
}
