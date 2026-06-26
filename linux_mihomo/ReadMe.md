# Mihomo 使用说明

## 1. 目录约定

这个 `vpn_backups` 项目可以下载到 Linux 机器上的任意目录。下面示例用 `PROJECT_DIR` 表示实际下载后的目录，请按你的实际路径进入：

```bash
cd /path/to/vpn_backups/linux_mihomo
```

本项目里的 `mihomo/` 目录用于保存要备份的 Mihomo 配置：

- `./mihomo/config.yaml`
- `./mihomo/providers/`
- `./mihomo/ui-metacubexd/`，执行 `install-ui.sh` 后生成

Mihomo 实际运行时读取的用户配置目录是：

```bash
$HOME/.config/mihomo
```

首次使用或修改了项目里的配置后，把项目里的 `mihomo/` 同步到实际运行目录：

```bash
mkdir -p "$HOME/.config/mihomo"
cp -a ./mihomo/. "$HOME/.config/mihomo/"
```

同步后，实际生效的配置文件应位于：

```bash
$HOME/.config/mihomo/config.yaml
```

## 2. 下载与安装 Mihomo

当前实际验证过的安装方式，是使用本目录中的 Debian 安装包：

- `mihomo-linux-amd64-v1-alpha-df1c5e5.deb`

该安装包适用于 amd64 / x86_64 Linux。建议优先使用这个包安装，避免直接使用未测试脚本。

```bash
cd /path/to/vpn_backups/linux_mihomo

# 安装已验证过的 deb 包
sudo apt install ./mihomo-linux-amd64-v1-alpha-df1c5e5.deb

# 如果 apt 无法直接安装本地包，可改用 dpkg
sudo dpkg -i ./mihomo-linux-amd64-v1-alpha-df1c5e5.deb
sudo apt-get install -f
```

`untested_install-mihomo.sh` 是未实际使用过的备用脚本。它会从 Mihomo 官方 GitHub Releases 下载版本并安装到 `/usr/bin/mihomo`，目前仅作为参考，不建议作为默认安装方式。

如需自行测试该脚本：

```bash
cd /path/to/vpn_backups/linux_mihomo
chmod +x ./untested_install-mihomo.sh

# 默认安装 GitHub Releases 最新版本
./untested_install-mihomo.sh

# 安装指定版本，例如：
./untested_install-mihomo.sh --version v1.19.27
```

## 3. 基本管理

```bash
# 查看状态
systemctl --user status mihomo.service

# 修改配置文件以后先reload再重启
systemctl --user daemon-reload

# 重启
systemctl --user restart mihomo.service

# 停止
systemctl --user stop mihomo.service

# 开启自启
systemctl --user enable mihomo.service

# 关闭自启
systemctl --user disable mihomo.service
```

## 4. TUN 权限说明

当前方案是给 `mihomo` 二进制授予 TUN 所需能力，以便用户级服务正常使用 TUN。

```bash
# 授予能力
sudo setcap cap_net_admin,cap_net_bind_service+ep /usr/bin/mihomo

# 重启服务
systemctl --user restart mihomo.service
```

验证：

```bash
getcap /usr/bin/mihomo
# 期望输出:
# /usr/bin/mihomo = cap_net_bind_service,cap_net_admin+ep

systemctl --user status mihomo.service
journalctl --user -u mihomo.service -f
```

如果需要撤销能力（恢复默认安全策略）：

```bash
sudo setcap -r /usr/bin/mihomo

# 验证能力已撤销；正常情况下不应再输出 cap_net_admin / cap_net_bind_service
getcap /usr/bin/mihomo
```

撤销后需要确认配置文件里没有开启 TUN：

```yaml
tun:
  enable: false
```

如果实际使用的 `~/.config/mihomo/config.yaml` 仍然是 `tun.enable: true`，撤销能力后重启服务可能会失败。确认 TUN 已关闭后，再重启服务：

```bash
systemctl --user restart mihomo.service
systemctl --user status mihomo.service
```

## 5. MetaCubeXD 面板安装

`install-ui.sh` 用于从 `https://github.com/metacubex/metacubexd` 的 `gh-pages` 分支下载静态面板。

脚本默认安装到本项目的 `./mihomo/ui-metacubexd/`，不需要把脚本复制到 `~/.config/mihomo` 再运行。

如果 `./mihomo/ui-metacubexd/` 已存在，脚本默认会先备份成类似 `ui-metacubexd.bak.20260627-xxxxxx` 的目录，再安装新版。

```bash
cd /path/to/vpn_backups/linux_mihomo

# 默认安装，已存在旧面板时会先备份
chmod +x ./install-ui.sh
./install-ui.sh

# 不保留旧面板备份，直接替换
./install-ui.sh --no-backup
```

下载完成后，把项目里的 `mihomo/` 同步到 Mihomo 实际运行目录：

```bash
cp -a ./mihomo/. "$HOME/.config/mihomo/"
systemctl --user restart mihomo.service
```

如果你想直接把 UI 下载到实际运行目录，也可以这样运行：

```bash
MIHOMO_DIR="$HOME/.config/mihomo" ./install-ui.sh
```

## 6. 配置策略与节点优先级

本项目的 `./mihomo/config.yaml` 是一个模板配置，设计目标是稳定地按用途选择节点，避免手动切换。订阅 URL 属于隐私信息，项目里的配置只保留占位符，实际订阅链接应只写在 Mihomo 实际运行目录：

```bash
$HOME/.config/mihomo/config.yaml
```

节点的日常切换是在 MetaCubeXD 图形界面里完成的，不需要手动改 YAML 里的 `proxy-groups`。确认 Mihomo 服务和 UI 都已启动后，在浏览器打开：

```text
http://<mihomo所在机器的IP>:9090/ui/
```

进入 MetaCubeXD 的 `代理` / `Proxies` 页面，找到策略组 `节点选择`，把它切换为 `良心云兜底`。这是日常常用配置。

配置里有：

```yaml
profile:
  store-selected: true
```

所以在 MetaCubeXD 里选过的策略会被记住，服务重启后通常仍沿用上次选择。

### 6.1 顶层选择

`节点选择` 是 MetaCubeXD 里需要操作的主要策略组。规则里的 OpenAI / ChatGPT 相关域名，以及最后的 `MATCH` 兜底流量，都会走 `节点选择`：

```yaml
- DOMAIN-SUFFIX,openai.com,节点选择
- DOMAIN-SUFFIX,chatgpt.com,节点选择
- DOMAIN-SUFFIX,oaistatic.com,节点选择
- DOMAIN-SUFFIX,oaiusercontent.com,节点选择
- MATCH,节点选择
```

在 MetaCubeXD 的 `节点选择` 策略组里，常用优先看这几个选项：

- `良心云兜底`：日常常用。优先使用良心云的新加坡、日本、美国自动组，最后再兜到 `AI自动选择`。
- `AI自动选择`：只在适合 AI 服务的节点池里自动测速选择。
- `自动选择`：在两个订阅的通用自动选择组之间测速选择。
- `故障转移`：按订阅顺序做可用性兜底。
- `魔戒兜底`：优先使用魔戒的新加坡、日本、美国自动组，最后再兜到 `AI自动选择`。
- `DIRECT`：手动直连。

### 6.2 兜底组优先级

`良心云兜底` 和 `魔戒兜底` 都是 `fallback` 组，会按列表顺序做可用性兜底。前面的候选组整体不可用时，才会继续尝试后面的组；当前面的组恢复可用后，下一轮健康检查会自动切回更靠前的组。

日常选择 `良心云兜底` 时，顺序是：

1. `良心云新加坡自动`
2. `良心云日本自动`
3. `良心云美国自动`
4. `AI自动选择`

选择 `魔戒兜底` 时，顺序是：

1. `魔戒新加坡自动`
2. `魔戒日本自动`
3. `魔戒美国自动`
4. `AI自动选择`

当前配置的健康检查间隔是 `300` 秒。已经建立的连接通常不会被强制迁移，新连接会使用恢复后的选择结果。

其中 `新加坡自动`、`日本自动`、`美国自动` 这些区域组本身是 `url-test`，会在对应地区节点里按延迟自动选择。

### 6.3 AI 自动选择

`AI自动选择` 是 `url-test` 组，会在下面两个组之间按延迟自动选择：

```yaml
AI自动选择:
  - AI良心云自动
  - AI魔戒自动
```

`AI良心云自动` 和 `AI魔戒自动` 都排除了香港、台湾、流量信息和套餐到期提示类节点：

```yaml
exclude-filter: "香港|台湾|台灣|🇭🇰|🇹🇼|HK|HKT|TW|WAP|^(剩余流量|套餐到期)"
```

这样做的目的，是让 AI 相关访问默认避开更容易不稳定或不适合的节点名称，只在更适合的节点池里自动测速。

注意：`url-test` 不是固定按列表顺序使用节点，而是按探测结果选择当前更合适的候选。列表顺序主要决定候选范围和面板展示顺序。

## 7. 订阅更新说明

配置文件：`~/.config/mihomo/config.yaml`  
订阅提供者键名：`良心云`、`魔戒`

### 7.1 情况 1：订阅链接不变（只是节点内容更新）

当前已配置自动更新（`interval: 21600`，即每 6 小时自动拉取）。  
如果要立即更新，执行：

```bash
systemctl --user restart mihomo.service
```

### 7.2 情况 2：订阅链接变更（更换新 URL）

1. 修改 Mihomo 实际运行目录里的配置文件：

```bash
nano "$HOME/.config/mihomo/config.yaml"
```

需要更新以下字段：

- `proxy-providers.良心云.url`
- `proxy-providers.魔戒.url`

1. 校验配置：

```bash
mihomo -t -d "$HOME/.config/mihomo" -f "$HOME/.config/mihomo/config.yaml"
```

1. 重启服务：

```bash
# 修改配置文件以后先reload再重启
systemctl --user daemon-reload

systemctl --user restart mihomo.service
```
