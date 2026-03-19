#!/usr/bin/env bash
# build.sh - builds Lambda layer zip before terraform apply
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"

echo "🏉 AFL Predictor - build script"
echo "================================"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo ""
echo "📦 Building Lambda layer (Python dependencies)..."

LAYER_DIR="$BUILD_DIR/layer/python"
mkdir -p "$LAYER_DIR"

# Note: no tweepy needed - Discord uses plain HTTP webhooks via requests
pip3 install \
  anthropic \
  requests \
  --target "$LAYER_DIR" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --quiet

cd "$BUILD_DIR/layer"
zip -r ../layer.zip python/ -q
cd "$SCRIPT_DIR"
echo "   layer.zip created ($(du -sh "$BUILD_DIR/layer.zip" | cut -f1))"

echo ""
echo "Build complete! Now run:"
echo "   cd terraform"
echo "   terraform init"
echo "   terraform plan -var-file=terraform.tfvars"
echo "   terraform apply -var-file=terraform.tfvars"
