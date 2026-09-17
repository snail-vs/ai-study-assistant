# StudyCenter GitOps seed

Copy this directory to the GitOps repository as `apps/studycenter/`, then add
`deploy/gitops/argocd/app-studycenter.yaml` to `argoCD/`.

The application repository workflow updates only the two image fields in the
Deployment manifests. Kubernetes secrets are intentionally not stored here.

