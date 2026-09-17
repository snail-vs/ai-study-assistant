# StudyCenter 家庭 K8s 部署

## 链路

```text
StudyCenter Gitea main
  -> Gitea Actions（ci-docker）
  -> 构建并推送 backend/frontend 镜像到 192.168.0.202:5000
  -> 提交 /data/code/gitops/apps/studycenter 的镜像 tag
  -> ArgoCD 监听 GitOps main 并同步到 K8s
```

应用仓库只负责构建和更新镜像版本，不直接调用 kubectl。GitOps 仓库才是
Kubernetes 的期望状态来源。

## 一次性安装 GitOps

将 `deploy/gitops/apps/studycenter/` 复制到 GitOps 仓库的
`apps/studycenter/`，将 `deploy/gitops/argocd/app-studycenter.yaml` 复制到
`argoCD/`，提交并推送 GitOps `main`。同时创建运行时 Secret：

```bash
kubectl -n studycenter create secret generic studycenter-runtime \
  --from-literal=encryption-key='REPLACE_WITH_STUDYCENTER_ENCRYPTION_KEY'
```

`encryption-key` 必须长期保持不变，否则数据库中已保存的 Provider API Key
无法解密。不要把这个 Secret 写入 Git。

首次同步前，Registry 需要已经允许 K8s 节点拉取镜像；若 Registry 是私有的，
还需要在 `studycenter` 命名空间创建 `imagePullSecret` 并补到两个 Deployment。

## Gitea Actions Secrets

在 StudyCenter 仓库配置：

* `REGISTRY_USERNAME`
* `REGISTRY_PASSWORD`

runner 需要复用现有家庭 Gitea SSH 凭据，以便 clone 应用仓库和 push GitOps
仓库。若未来改成 GitHub，保留 workflow 的 build 部分，只替换 checkout、
GitOps 鉴权和触发语法即可。

## 数据库策略

后端启动时执行 `alembic upgrade head`，数据库文件位于 PVC 的
`/data/studycenter.db`。第一版使用 SQLite 单副本和 `Recreate` 发布策略，
避免多副本同时写 SQLite 或并发迁移。

开发数据的一次性迁移建议：

1. 先停止开发服务并备份 `backend/studycenter.db`；
2. 将数据库文件复制到生产 PVC 的 `/data/studycenter.db`；
3. 启动后端，由启动命令执行 Alembic 迁移；
4. 检查课程、笔记、旁支会话和 Provider 设置；
5. 确认生产 `STUDYCENTER_ENCRYPTION_KEY` 与开发库写入时使用的 key 相同。

如果不需要带开发数据，删除生产 PVC 中的数据库文件后重新启动即可获得空库。
不要在生产容器启动命令中执行 `Base.metadata.create_all`，生产结构只由 Alembic 管理。

