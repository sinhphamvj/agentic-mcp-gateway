#!/bin/bash
set -euo pipefail

# Make sure we're in the project root
cd "$(dirname "$0")/.."

# Check if vhs is installed
if ! command -v vhs &> /dev/null; then
    echo "vhs could not be found. Please install it: https://github.com/charmbracelet/vhs"
    exit 1
fi

echo "Generating demo.tape..."
cat << 'EOF' > demo.tape
Output demo.gif
Require uv
Require curl

Set FontSize 16
Set Width 1200
Set Height 800
Set Padding 40
Set Theme "Catppuccin Mocha"

# Show starting the database MCP server
Type "DB_PATH=sample.db uv run python servers/database/server.py &"
Enter
Sleep 2s

# Show starting the gateway
Type "GATEWAY_CONFIG=workflow.yaml uv run amcpg serve &"
Enter
Sleep 3s
Clear

# Query 1: Basic schema query
Type "echo 'Querying database schema...'"
Enter
Type "curl -s -X POST http://localhost:8001/v1/chat/completions -H 'Content-Type: application/json' -d '{\"messages\": [{\"role\": \"user\", \"content\": \"What tables exist in the database?\"}]}' | jq .choices[0].message.content"
Enter
Sleep 5s
Clear

# Query 2: Data query
Type "echo 'Querying data...'"
Enter
Type "curl -s -X POST http://localhost:8001/v1/chat/completions -H 'Content-Type: application/json' -d '{\"messages\": [{\"role\": \"user\", \"content\": \"List the top 3 users by ID.\"}]}' | jq .choices[0].message.content"
Enter
Sleep 5s
Clear

# Query 3: Complex routing
Type "echo 'Performing complex routed query...'"
Enter
Type "curl -s -X POST http://localhost:8001/v1/chat/completions -H 'Content-Type: application/json' -d '{\"messages\": [{\"role\": \"user\", \"content\": \"How many products are there?\"}]}' | jq .choices[0].message.content"
Enter
Sleep 5s

Type "kill %1 %2"
Enter
Sleep 1s
EOF

echo "Running vhs..."
vhs demo.tape
rm demo.tape

echo "Demo recorded to demo.gif!"
