# 部署与 CI/CD

> 目标：本地一条命令跑起来，推送到 `main` 自动测试并构建镜像，打标签后一键部署到服务器。

## 1. 本地运行

```bash
cp .env.example .env
# 填入 QWEN_API_KEY、ADMIN_PASSWORD
streamlit run src/app.py
```

首次启动会自动把 `data/business_templates/` 的 29 条模板导入独立知识库（幂等，之后启动约 5ms 跳过）。

## 2. Docker 运行

```bash
docker compose up -d --build
curl http://localhost:8501/_stcore/health
```

生产模式（带 Nginx / HTTPS）：

```bash
# 把证书放到 nginx/ssl/{fullchain.pem,privkey.pem}
docker compose --profile prod up -d --build
```

数据持久化：

| 卷 | 容器路径 | 内容 |
|---|---|---|
| `biz-db` | `/app/db` | `biz_data.db`（业务库，含客户信息） |
| `knowledge-data` | `/app/data/uploads` | 管理员上传的模板文件 |
| `vector-store` | `/app/chroma_db` | Chroma 向量库 + BM25 索引 |
| `app-config` | `/app/logs` | 应用日志 |

> 备份 `biz-db` 和 `vector-store` 即可恢复业务；`exports/` 是可重新生成的交付物。

## 3. CI：测试 + 构建镜像

`.github/workflows/ci.yml` 在 push / PR 时执行：

1. Python 3.12 安装依赖；
2. `python -m compileall` 语法检查；
3. `pytest tests -q`（92 个用例）；
4. `main` 分支通过后构建镜像并推送到 GHCR：
   - `ghcr.io/<owner>/travel-itinerary-ai:latest`
   - `ghcr.io/<owner>/travel-itinerary-ai:sha-<commit>`

CI 使用占位环境变量，不会调用真实模型：

```yaml
QWEN_API_KEY: sk-ci-placeholder
ADMIN_PASSWORD: ci-test-password-123
```

> 为什么要设置 `ADMIN_PASSWORD`：部分测试依赖 id=1 的管理员用户建立外键关系。

## 4. CD：部署到服务器

`.github/workflows/deploy.yml` 默认**不执行**，需要显式开启。

### 4.1 服务器首次准备

```bash
# 安装 Docker + Compose 插件后
git clone https://github.com/aibiyaqi/travel-itinerary-ai.git /opt/travel-itinerary
cd /opt/travel-itinerary
cp .env.example .env
vim .env                      # QWEN_API_KEY / ADMIN_PASSWORD
docker compose pull travel-assistant
docker compose up -d --no-build travel-assistant
curl -fsS http://127.0.0.1:8501/_stcore/health
```

### 4.2 仓库配置

Settings → Secrets and variables → Actions：

| 类型 | 名称 | 说明 |
|---|---|---|
| Variable | `DEPLOY_ENABLED` | 设为 `true` 才允许部署 |
| Secret | `DEPLOY_HOST` | 服务器 IP / 域名 |
| Secret | `DEPLOY_USER` | SSH 用户（建议非 root） |
| Secret | `DEPLOY_SSH_KEY` | 部署私钥（对应公钥在服务器 `authorized_keys`） |
| Secret | `DEPLOY_PATH` | 例如 `/opt/travel-itinerary` |
| Secret | `GHCR_TOKEN` | 具有 `read:packages` 的 PAT，供服务器拉取私有镜像 |

另外在 Settings → Environments 创建 `production`，可加人工审批。

### 4.3 触发方式

- 手动：Actions → Deploy → Run workflow → 填镜像 tag（默认 `latest`）；
- 自动：推送 `v*` 标签，例如 `git tag v1.0.0 && git push origin v1.0.0`。

部署脚本会：登录 GHCR → `docker compose pull` → `up -d --no-build` → 健康检查。

## 5. 回滚

镜像按 commit 打了 `sha-<commit>` 标签：

```bash
APP_IMAGE=ghcr.io/aibiyaqi/travel-itinerary-ai:sha-<commit> \
  docker compose up -d --no-build travel-assistant
```

数据库变更前先备份：

```bash
docker run --rm -v travel-itinerary_biz-db:/src -v "$PWD/backup:/backup" alpine \
  tar czf /backup/biz-db-$(date +%F).tar.gz -C /src .
```

## 6. 安全清单（上线前逐项确认）

- [ ] `.env` 不在 Git 历史中（本仓库 `.gitignore` 已忽略；提交前 `git status` 再确认）；
- [ ] `QWEN_API_KEY` 已轮换，不使用开发期 Key；
- [ ] `ADMIN_PASSWORD` 为强密码，且已修改默认账号；
- [ ] `biz_data.db`、`chroma_db/`、`exports/` 未提交；
- [ ] GHCR 包可见性按需设置（私有则服务器必须配 `GHCR_TOKEN`）；
- [ ] 服务器防火墙只开放 80/443，8501 仅监听 `127.0.0.1`；
- [ ] Nginx 证书有效，`X-Frame-Options` / HSTS 已生效；
- [ ] 定期备份 `biz-db` 与 `vector-store`；
- [ ] 审计日志（`audit_logs`）保留周期符合公司要求。

## 7. 排障

```bash
docker compose ps
docker compose logs -f travel-assistant
docker compose logs -f nginx
nginx -t                      # 容器内：docker compose exec nginx nginx -t
```

常见问题：

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动即退出，提示缺少 `QWEN_API_KEY` | `.env` 未挂载/未配置 | 检查 `env_file` 与 `.env` |
| `database is locked` | 多写并发超过 SQLite 承受范围 | 已开 WAL/busy_timeout；继续增长则迁 PostgreSQL/MySQL |
| 健康检查失败 | 模型首次加载慢 | `start_period` 已放宽到 120s，查看日志确认 |
| Nginx 起不来 | 证书路径/域名未替换 | 检查 `nginx/nginx.conf` 与 `nginx/ssl/` |
| 拉取镜像 401 | GHCR 私有包未登录 | 配置 `GHCR_TOKEN` 并 `docker login ghcr.io` |
