# 自建 Jenkins CI/CD 方案（已归档，暂缓）

> 状态：**已归档**。2026-08-09 决策：暂不实施，先用 GitHub Actions 跑 CI。
> 保留此文档，将来需要时按此方案执行。
> 触发条件（任一想实现时）：仓库在国内平台(Gitee)/国内网络拉依赖太慢/需连内网服务/要集中管理多个仓库。

---

## 一、与 GitHub Actions 的取舍

| | GitHub Actions（现状） | 阿里云自建 Jenkins |
|---|---|---|
| 费用 | 免费 | 用已有服务器，无新增成本 |
| 构建速度 | runner 在国外，国内拉依赖慢/易超时 | 服务器在国内，可用清华/阿里镜像，快 |
| 维护 | 零维护 | 要自己升级 Jenkins、插件、打安全补丁 |
| 安全 | GitHub 托管 | 面向公网 = 攻击面，必须加固 |
| 多仓库 | 每个仓库各配一份 workflow | 一个 Jenkins 集中管所有仓库 |
| 触发 | push/PR 自动 | webhook 自动 |

**结论**：纯 GitHub 仓库 + lint/test 场景，Actions 更省心；自建适合国内/Gitee/内网/多仓库集中管理。

## 二、目标架构

```text
GitHub / Gitee 仓库
   │  push
   ▼  webhook
阿里云服务器 (Docker)
  └─ Jenkins 容器  (Web UI :443 HTTPS)
       └─ 流水线: clone → Poetry install → ruff → pytest → (可选) Docker build
             │
             ▼  构建状态回传 GitHub (commit status)
```

**关键组件**：
1. **服务器**：Docker 装 Jenkins（升级/隔离/回滚方便，持久化到 volume 不丢数据）
2. **GitHub/Gitee 集成**：Personal Access Token（拉代码 + 回传状态）+ webhook（push 触发）
3. **多仓库**：Jenkins "GitHub Organization Folder" 插件 → 一个 job 自动发现名下所有仓库所有分支
4. **统一流水线**：每个仓库放一个 Jenkinsfile（或 shared library 共享模板）
5. **安全**：nginx 反代 + Let's Encrypt HTTPS，防火墙只开 443，Jenkins 不裸奔公网

## 三、落地步骤分工

| 步骤 | 我做的 | 用户做的 |
|---|---|---|
| 1. 服务器环境 | 一键脚本（装 Docker + 起 Jenkins + 配数据卷） | 在服务器执行 |
| 2. Jenkins 初始化 | 解锁步骤 + 插件清单 + 管理员配置脚本 | 网页点几下 |
| 3. GitHub/Gitee 接入 | PAT 申请步骤 + webhook 配置说明 | 生成 token、配 webhook |
| 4. 流水线 | 写通用 Jenkinsfile（Poetry+ruff+pytest，标好可改点）+ docker-compose | 放进各仓库或接入共享库 |
| 5. 接所有仓库 | 配 Organization Folder 的指引 | 填组织/用户名 |
| 6. 验证 | 用现有项目做一次全流程压测 | push 看流水线跑 |

> 注意：本机（Windows）无法直接 SSH 到用户服务器，配置文件和脚本需先写好放在仓库里，由用户在服务器上执行。

## 四、待用户拍板的参数（实施前确认）

- [ ] 仓库托管平台：GitHub / Gitee / 两者都有
- [ ] 服务器 OS：Ubuntu 22.04 / Debian 12 / CentOS 7 / 其他
- [ ] Jenkins 部署方式：Docker 容器（推荐）/ 系统原生安装
- [ ] 服务器配置（决定并发构建数）：2C4G / 4C8G / 更高

## 五、安全清单（实施时必做）

- [ ] nginx 反代 + Let's Encrypt HTTPS，仅暴露 443
- [ ] Jenkins 管理员强密码，关闭匿名访问
- [ ] 防火墙仅开放必要端口
- [ ] PAT 用最小权限（repo 读写 + 状态回传），不泄露
- [ ] 定期升级 Jenkins 与插件

## 六、备注

- Jenkins 流水线可复用本仓库现有 GitHub Actions 步骤（Poetry install、ruff、pytest、Docker build），迁移成本低。
- 当前 `.github/workflows/ci.yml` 即为 Actions 版参照实现。
