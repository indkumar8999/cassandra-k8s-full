# Cassandra + Simulator Kubernetes Setup

This package includes:
- Kubernetes manifests for Cassandra (StatefulSet) with customizable replica count
- A separate simulator application you can build and deploy independently
- Dockerfile and Python/Flask simulator source code

## Folder structure

- `k8s/` Kubernetes manifests
- `simulator/` simulator application source
- `docker/` optional local Docker Compose setup for local testing

## Build simulator image

From the `simulator` folder:

```bash
docker build -t cassandra-simulator:latest .
```

### If using minikube

```bash
minikube image load cassandra-simulator:latest
```

### If using kind

```bash
kind load docker-image cassandra-simulator:latest --name <your-kind-cluster-name>
```

### If using a remote cluster

Tag and push to your registry:

```bash
docker tag cassandra-simulator:latest <your-registry>/cassandra-simulator:latest
docker push <your-registry>/cassandra-simulator:latest
```

Then update `k8s/simulator/simulator-deployment.yaml` with your image name.

## Deploy

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/cassandra/
kubectl apply -f k8s/simulator/
```

## Scale Cassandra nodes

```bash
kubectl scale statefulset cassandra -n cassandra-lab --replicas=5
```

## Access simulator API

```bash
kubectl port-forward svc/cassandra-simulator 8080:8080 -n cassandra-lab
```

Then:
- `GET  http://localhost:8080/health`
- `GET  http://localhost:8080/load`
- `POST http://localhost:8080/load`
- `POST http://localhost:8080/pause`
- `POST http://localhost:8080/resume`
- `GET  http://localhost:8080/metrics`

Example:

```bash
curl -X POST http://localhost:8080/load \
  -H "Content-Type: application/json" \
  -d '{"profile":"high"}'
```
