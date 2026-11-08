set -euo pipefail
cd "$(dirname "$0")/.."
kubectl create configmap pipeline-code --from-file=app/ --dry-run=client -o yaml \
  > configmaps/pipeline-code-configmap.yaml
kubectl apply -f configmaps/
kubectl rollout restart deployment upload-api preprocessor inference storage
