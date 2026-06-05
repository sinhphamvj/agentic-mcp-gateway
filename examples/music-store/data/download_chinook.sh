#!/usr/bin/env bash
# Copyright 2024 agentic-mcp-gateway contributors
# SPDX-License-Identifier: Apache-2.0
#
# Download the Chinook SQLite database from the official repository.
# Usage: bash download_chinook.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_URL="https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"
OUTPUT_PATH="${SCRIPT_DIR}/chinook.db"

echo "🎵 Downloading Chinook SQLite database..."
echo "   Source : ${DB_URL}"
echo "   Target : ${OUTPUT_PATH}"
echo ""

curl -fSL --progress-bar -o "${OUTPUT_PATH}" "${DB_URL}"

echo ""
echo "✅ Download complete — $(du -h "${OUTPUT_PATH}" | cut -f1) written to chinook.db"
