# 发布流程

Tag 触发构建 API/worker/web 三镜像，trivy high/critical 门禁，syft SBOM，上传 wheel/sdist 与 sha256。镜像必须使用 `tools/image_digests.py` 和 sandbox digest 同源锁。Docker 构建与扫描标记 `requires_docker`。