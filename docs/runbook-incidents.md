# 故障演练

所有剧本标记 `requires_docker`，禁止伪造结果。worker 停止：重投或 failed 且不悬挂；Redis 停止：SSE 断但 API 可用；Postgres 停止：readyz 503。使用 job_id、signature、成本查询模板观察；压测仅 mock。