# Dabba Helm chart

This chart deploys the image published by `.github/workflows/docker-build-push.yml`.
The application listens on port `8080`, uses `/health` for liveness, `/ready` for
readiness, and stores platform state under `/data`.

## Install

```bash
helm upgrade --install dabba ./helm/dabba \
  --set image.repository=docker.io/YOUR_DOCKERHUB_USERNAME/dabba \
  --set image.tag=latest
```

For a private Docker Hub repository, create an image pull secret and set
`image.pullSecrets`, for example:

```bash
kubectl create secret docker-registry dockerhub \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username="$DOCKERHUB_USERNAME" \
  --docker-password="$DOCKERHUB_TOKEN"
helm upgrade --install dabba ./helm/dabba \
  --set image.repository=docker.io/$DOCKERHUB_USERNAME/dabba \
  --set image.pullSecrets[0].name=dockerhub
```

Set the API key using an existing Secret (recommended):

```bash
kubectl create secret generic dabba-auth --from-literal=DABBA_API_KEY='change-me'
helm upgrade --install dabba ./helm/dabba \
  --set secret.existingSecret=dabba-auth
```

The chart creates a 10Gi PVC by default. For ephemeral development storage,
use `--set persistence.enabled=false`. Enable external access with
`--set ingress.enabled=true` and configure `ingress.hosts` for your controller.

## Important values

| Value | Default | Purpose |
|---|---|---|
| `image.repository` | `dabba` | Docker image repository |
| `image.tag` | `latest` | Published image tag |
| `api.modelPath` | `rule_based` | `DABBA_MODEL_PATH` |
| `secret.existingSecret` | empty | Secret containing `DABBA_API_KEY` |
| `persistence.size` | `10Gi` | Durable `/data` storage |
| `ingress.enabled` | `false` | Expose the Service through Ingress |
