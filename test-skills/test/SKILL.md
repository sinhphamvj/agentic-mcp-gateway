---
name: test
description: test
---

# test

## Available Capabilities
- **search_movies**: Search movies by title and/or rating range. Results are sorted by rating descending. To get the top N highest rated movies, just set limit=N without any rating filters. Rating scale is 1.0 to 10.0. In this dataset, ratings range from 7.5 to 8.8.

## How to Use
Replace <query> with the exact question from the user or agent.
Do not remove or modify any information from the original query.

```bash
curl -X POST http://localhost:8001/generate \
  -H "Content-Type: application/json" \
  -d '{"input_message": "<query>"}'
```

## Important Rules
- Always pass the COMPLETE user question without modification
- Do not invent data; all information comes from the backend tools
- If the response contains an error, relay it to the user clearly
