terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Optional: use S3 backend for team collaboration
  # backend "s3" {
  #   bucket = "your-tf-state-bucket"
  #   key    = "afl-predictor/terraform.tfstate"
  #   region = "ap-southeast-2"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "afl-predictor"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ─────────────────────────────────────────
# Data sources
# ─────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
