# API Reference

## Overview

Dabba provides an OpenAI-compatible REST API for chat completions, text completions, and model management.

## Starting the Server

```bash
# Start with default settings
dabba serve

# Start with custom host and port
dabba serve --host 0.0.0.0 --port 8000

# Start with a specific model
dabba serve --model dabba-small

# Start with authentication
dabba serve --api-key your-secret-key
```

## Endpoints

### Health Check

```http
GET /health
```

Response:
```json
{
    "status": "healthy",
    "model": "dabba-small",
    "uptime": "5m 30s",
    "version": "0.1.0"
}
```

### List Models

```http
GET /v1/models
```

Response:
```json
{
    "data": [
        {
            "id": "dabba-tiny",
            "object": "model",
            "created": 1700000000,
            "owned_by": "dabba"
        },
        {
            "id": "dabba-small",
            "object": "model",
            "created": 1700000000,
            "owned_by": "dabba"
        }
    ]
}
```

### Chat Completions

```http
POST /v1/chat/completions
```

Request:
```json
{
    "model": "dabba-small",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ],
    "temperature": 0.7,
    "max_tokens": 100,
    "stream": false
}
```

Response:
```json
{
    "id": "chatcmpl-123",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "dabba-small",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "The capital of France is Paris."
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 15,
        "completion_tokens": 7,
        "total_tokens": 22
    }
}
```

### Streaming Chat

```http
POST /v1/chat/completions
```

Set `"stream": true` in the request body to receive Server-Sent Events (SSE):

```
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":"The"},"index":0}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":" capital"},"index":0}]}

data: [DONE]
```

### Text Completions

```http
POST /v1/completions
```

Request:
```json
{
    "model": "dabba-small",
    "prompt": "Once upon a time",
    "max_tokens": 50,
    "temperature": 0.8
}
```

## Authentication

### API Key Authentication
```bash
# Set API key
export DABBA_API_KEY=your-secret-key

# Pass in header
curl -H "Authorization: Bearer your-secret-key" http://localhost:8000/v1/chat/completions
```

## Rate Limiting

Default limits:
- 60 requests per minute per user
- Configurable via server settings

```python
from dabba.api.rate_limiter import RateLimiter

limiter = RateLimiter(max_requests=120, window_seconds=60)
```

## Error Handling

```json
{
    "error": {
        "type": "invalid_request_error",
        "code": "model_not_found",
        "message": "Model 'unknown-model' not found",
        "param": "model"
    }
}
```

Common error codes:
- `model_not_found` - Requested model doesn't exist
- `rate_limit_exceeded` - Too many requests
- `invalid_api_key` - Authentication failed
- `context_length_exceeded` - Input too long

## SDK Examples

### Python
```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-api-key",
)

response = client.chat.completions.create(
    model="dabba-small",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### cURL
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "model": "dabba-small",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```
