# Deployment Guide

## Docker Deployment

### Building the Image

```bash
# Build the Docker image
docker build -t dabba:latest .

# Build with specific model preset
docker build --build-arg MODEL_PRESET=small -t dabba:small .
```

### Running with Docker

```bash
# Basic run
docker run -d --name dabba -p 8000:8000 dabba:latest

# With GPU support
docker run -d --name dabba --gpus all -p 8000:8000 dabba:latest

# With mounted model cache
docker run -d --name dabba \
  -v /path/to/models:/app/models \
  -p 8000:8000 \
  dabba:latest

# With environment configuration
docker run -d --name dabba \
  -e DABBA_API_KEY=your-secret-key \
  -e DABBA_MODEL=dabba-small \
  -e DABBA_MAX_TOKENS=2048 \
  -p 8000:8000 \
  dabba:latest
```

### Docker Compose

```yaml
# docker-compose.yml
version: "3.8"
services:
  dabba:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DABBA_API_KEY=${DABBA_API_KEY:-}
      - DABBA_MODEL=dabba-small
    volumes:
      - ./models:/app/models
      - ./data:/app/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Start with:
```bash
docker-compose up -d
```

## Production Deployment

### Using a Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name api.dabba.ai;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### With SSL (Let's Encrypt + Certbot)

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d api.dabba.ai
```

## Scaling

### Horizontal Scaling with Docker Compose

```yaml
version: "3.8"
services:
  dabba:
    build: .
    ports:
      - "8000-8003:8000"
    deploy:
      replicas: 4
    environment:
      - DABBA_MODEL=dabba-small
```

### Load Balancing with Nginx

```nginx
upstream dabba_cluster {
    server dabba1:8000;
    server dabba2:8000;
    server dabba3:8000;
    server dabba4:8000;
}

server {
    listen 80;
    location / {
        proxy_pass http://dabba_cluster;
    }
}
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dabba
spec:
  replicas: 3
  selector:
    matchLabels:
      app: dabba
  template:
    metadata:
      labels:
        app: dabba
    spec:
      containers:
      - name: dabba
        image: dabba:latest
        ports:
        - containerPort: 8000
        env:
        - name: DABBA_MODEL
          value: "dabba-small"
        resources:
          limits:
            nvidia.com/gpu: 1
            memory: "16Gi"
            cpu: "8"
---
apiVersion: v1
kind: Service
metadata:
  name: dabba-service
spec:
  selector:
    app: dabba
  ports:
  - port: 8000
    targetPort: 8000
  type: LoadBalancer
```

## Monitoring

### Health Check Endpoint
```bash
curl http://localhost:8000/health
```

### Logging
```python
# Server-side logging
import logging
logging.basicConfig(level=logging.INFO)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| DABBA_API_KEY | None | API key for authentication |
| DABBA_MODEL | dabba-small | Model preset to load |
| DABBA_MAX_TOKENS | 2048 | Maximum sequence length |
| DABBA_DEVICE | cuda if available | Compute device |
| DABBA_HOST | 0.0.0.0 | Server host |
| DABBA_PORT | 8000 | Server port |
| DABBA_LOG_LEVEL | info | Logging level |

## Performance Tuning

### Batch Processing
```python
# For higher throughput
model = Dabba.from_preset("small")
outputs = model.generate_batch(prompts, batch_size=8)
```

### Half Precision
```bash
# Use FP16 for faster inference
export DABBA_DTYPE=float16
dabba serve
```

### Model Quantization
```bash
# Use 8-bit quantization (reduced memory)
dabba serve --quantize 8bit
```
