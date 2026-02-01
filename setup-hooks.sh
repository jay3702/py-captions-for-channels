#!/bin/bash
# Setup pre-commit hook to run linters automatically

SOURCE_PATH="hooks/pre-commit"
DEST_PATH=".git/hooks/pre-commit"

if [ ! -f "$SOURCE_PATH" ]; then
    echo "❌ Source hook not found: $SOURCE_PATH"
    exit 1
fi

if [ -f "$DEST_PATH" ]; then
    echo "Pre-commit hook already exists. Updating..."
fi

# Copy hook from tracked location
cp "$SOURCE_PATH" "$DEST_PATH"
chmod +x "$DEST_PATH"

echo "✅ Pre-commit hook installed!"
echo "Linters will run automatically before each commit."
echo "To bypass: git commit --no-verify"
