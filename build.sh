#!/bin/sh
# Build dist/phd-skill-catchup.zip, the package that users upload to their AI agent.
# Personal files (.config with API keys), caches and test definitions are left out.
set -e
cd "$(dirname "$0")"
rm -rf dist && mkdir dist
zip -r -q dist/phd-skill-catchup.zip phd-skill-catchup \
    -x "phd-skill-catchup/.config" "*/__pycache__/*" "*.pyc" "phd-skill-catchup/evals/*" "*/.DS_Store"
if unzip -l dist/phd-skill-catchup.zip | grep -q "\.config"; then
    echo "ERROR: .config is in the package" >&2; exit 1
fi
unzip -l dist/phd-skill-catchup.zip
