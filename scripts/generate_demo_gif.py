# Apache-2.0 License Header
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Script to generate a simulated terminal session GIF for README."""

import os

from PIL import Image, ImageDraw, ImageFont

# Dimensions
WIDTH = 800
HEIGHT = 500
FONT_PATH = "/System/Library/Fonts/Supplemental/Courier New.ttf"
SRV_RUN_MSG = "[INFO] Gateway HTTP server running on http://127.0.0.1:8001"


def draw_window_frame(draw):
    # Background
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill="#1e1e2e")
    
    # Title bar
    draw.rectangle([0, 0, WIDTH, 40], fill="#303046")
    
    # Title bar window controls (macOS style)
    draw.ellipse([15, 12, 31, 28], fill="#ff5f56") # Red
    draw.ellipse([40, 12, 56, 28], fill="#ffbd2e") # Yellow
    draw.ellipse([65, 12, 81, 28], fill="#27c93f") # Green


def generate_gif():
    # Load fonts
    try:
        font = ImageFont.truetype(FONT_PATH, 16)
        font_bold = ImageFont.truetype(FONT_PATH.replace(".ttf", " Bold.ttf"), 16)
    except Exception:
        font = ImageFont.load_default()
        font_bold = font

    frames = []
    
    # Step 1: Start terminal and prompt
    prompt = "sinhphamvj@mac:~$ "
    command = "amcpg serve --config workflow.yaml"
    
    # Typing the command frame by frame
    for i in range(len(command) + 1):
        img = Image.new("RGB", (WIDTH, HEIGHT), "#1e1e2e")
        draw = ImageDraw.Draw(img)
        draw_window_frame(draw)
        
        # Draw prompt
        draw.text((20, 60), prompt, fill="#89b4fa", font=font_bold)
        # Draw typed command
        cursor = "_" if i < len(command) else ""
        draw.text((20 + 170, 60), command[:i] + cursor, fill="#a6e3a1", font=font)
        
        frames.append(img)
    
    # Frame holding the full command typed
    for _ in range(5):
        frames.append(frames[-1])
        
    # Step 2: Show server startup logs
    server_logs = [
        "[INFO] Loading configuration from workflow.yaml",
        "[INFO] Connected to MCP server 'demo-db' at http://localhost:8000/mcp",
        "[INFO] Intent router initialized with 2 intents: QUERY, SCHEMA",
        "[INFO] Gateway HTTP server running on http://127.0.0.1:8001 (Press CTRL+C to quit)"
    ]
    
    # Render logs line by line
    for log_index in range(1, len(server_logs) + 1):
        img = Image.new("RGB", (WIDTH, HEIGHT), "#1e1e2e")
        draw = ImageDraw.Draw(img)
        draw_window_frame(draw)
        
        # Draw prompt and command
        draw.text((20, 60), prompt, fill="#89b4fa", font=font_bold)
        draw.text((20 + 170, 60), command, fill="#a6e3a1", font=font)
        
        # Draw log lines
        y = 90
        for log in server_logs[:log_index]:
            draw.text((20, y), log, fill="#cdd6f4", font=font)
            y += 25
            
        frames.append(img)
        # Hold on each line briefly
        for _ in range(3):
            frames.append(img)
            
    # Step 3: Draw a split pane or second terminal command (curl)
    curl_prompt = "sinhphamvj@mac:~$ "
    curl_cmd = "curl -X POST http://localhost:8001/v1/chat/completions \\"
    curl_cmd2 = (
        "  -d '{\"messages\": [{\"role\": \"user\", "
        "\"content\": \"How many products do we have?\"}]}'"
    )
    
    # Build curl frames
    for i in range(len(curl_cmd) + 1):
        img = Image.new("RGB", (WIDTH, HEIGHT), "#1e1e2e")
        draw = ImageDraw.Draw(img)
        draw_window_frame(draw)
        
        # Draw previous server run logs truncated at the top
        draw.text((20, 60), SRV_RUN_MSG, fill="#cdd6f4", font=font)
        
        # Draw new prompt
        draw.text((20, 95), curl_prompt, fill="#89b4fa", font=font_bold)
        cursor = "_" if i < len(curl_cmd) else ""
        draw.text((20 + 170, 95), curl_cmd[:i] + cursor, fill="#f9e2af", font=font)
        
        frames.append(img)
        
    for i in range(len(curl_cmd2) + 1):
        img = Image.new("RGB", (WIDTH, HEIGHT), "#1e1e2e")
        draw = ImageDraw.Draw(img)
        draw_window_frame(draw)
        
        draw.text((20, 60), SRV_RUN_MSG, fill="#cdd6f4", font=font)
        draw.text((20, 95), curl_prompt, fill="#89b4fa", font=font_bold)
        draw.text((20 + 170, 95), curl_cmd, fill="#f9e2af", font=font)
        cursor = "_" if i < len(curl_cmd2) else ""
        draw.text((20 + 170, 120), curl_cmd2[:i] + cursor, fill="#f9e2af", font=font)
        
        frames.append(img)
        
    for _ in range(5):
        frames.append(frames[-1])
        
    # Step 4: Show gateway handling request
    log_incoming = (
        "[INFO] POST /v1/chat/completions - Routing user query to 'demo-db' (QUERY intent)"
    )
    log_mcp_call = (
        "[INFO] calling tool 'query_database' on 'demo-db' with args: "
        "{'query': 'SELECT COUNT(*) FROM products'}"
    )
    log_mcp_resp = "[INFO] tool 'query_database' returned 1 row"
    log_complete = "[INFO] Compiled response from LLM using retrieved tools: 200 OK"
    
    gateway_logs = [log_incoming, log_mcp_call, log_mcp_resp, log_complete]
    
    # Render gateway logs
    for log_index in range(1, len(gateway_logs) + 1):
        img = Image.new("RGB", (WIDTH, HEIGHT), "#1e1e2e")
        draw = ImageDraw.Draw(img)
        draw_window_frame(draw)
        
        # Server running log
        draw.text((20, 60), SRV_RUN_MSG, fill="#cdd6f4", font=font)
        # Curl command
        draw.text((20, 95), curl_prompt, fill="#89b4fa", font=font_bold)
        draw.text((20 + 170, 95), curl_cmd, fill="#f9e2af", font=font)
        draw.text((20 + 170, 120), curl_cmd2, fill="#f9e2af", font=font)
        
        # Draw server response logs
        y = 155
        for log in gateway_logs[:log_index]:
            draw.text((20, y), log, fill="#a6e3a1", font=font)
            y += 25
            
        frames.append(img)
        for _ in range(3):
            frames.append(img)
            
    # Step 5: Show curl output (JSON response)
    json_response = [
        "{",
        '  "choices": [',
        "    {",
        '      "index": 0,',
        '      "message": {',
        '        "role": "assistant",',
        '        "content": "There are currently 42 products in the demo database."',
        "      },",
        '      "finish_reason": "stop"',
        "    }",
        "  ],",
        '  "usage": { "total_tokens": 348 }',
        "}"
    ]
    
    # Final frames containing all logs + curl response
    img = Image.new("RGB", (WIDTH, HEIGHT), "#1e1e2e")
    draw = ImageDraw.Draw(img)
    draw_window_frame(draw)
    
    # Server running logs
    draw.text((20, 60), SRV_RUN_MSG, fill="#cdd6f4", font=font)
    draw.text((20, 95), curl_prompt, fill="#89b4fa", font=font_bold)
    draw.text((20 + 170, 95), curl_cmd, fill="#f9e2af", font=font)
    draw.text((20 + 170, 120), curl_cmd2, fill="#f9e2af", font=font)
    
    # Server reaction logs
    y = 155
    for log in gateway_logs:
        draw.text((20, y), log, fill="#cdd6f4", font=font)
        y += 25
        
    # Draw JSON response
    y_json = 265
    for line in json_response:
        draw.text((20, y_json), line, fill="#b4befe", font=font)
        y_json += 17
        
    # Add new prompt line at the very bottom
    draw.text((20, y_json + 5), curl_prompt, fill="#89b4fa", font=font_bold)
    
    # Hold final frame for a longer duration
    for _ in range(15):
        frames.append(img)
        
    # Save GIF
    os.makedirs("assets", exist_ok=True)
    frames[0].save(
        "assets/demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=120,  # 120ms per frame
        loop=0
    )
    print("Demo GIF successfully saved to assets/demo.gif")


if __name__ == "__main__":
    generate_gif()
