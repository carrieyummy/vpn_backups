# Mihomo Config Editor

一个局域网内使用的 `config.yaml` 简易网页编辑器。

- 访问地址：`http://<MIHOMO_LAN_IP>:9091/`
- 登录密钥：读取 `/home/azurengine/.config/mihomo/secret`
- 配置文件：`/home/azurengine/.config/mihomo/config.yaml`
- 服务文件：`/home/azurengine/.config/systemd/user/mihomo-config-editor.service`

## 远程 Linux 代理环境同步

“表单编辑”页底部的“远程 Linux 代理环境”可通过 SSH 密码认证同步登录用户的：

- `~/.bashrc`
- `~/.codex/.env`

IP 下拉建议来自当前 `config.yaml` 的 `lan-allowed-ips`，包括 `# - <IP>/32` 形式的注释条目；会排除回环地址和 Mihomo 本机地址，仍可手动输入其他 IP。

首次使用某个 IP 成功完成 SSH 检查后，用户名和密码会按 IP 写入 `remote_credentials.db`。密码以 Fernet 加密令牌保存，独立密钥保存在仅当前用户可读的 `remote_credentials.key`；后续选择该 IP 时页面只自动填入用户名，密码不会返回到浏览器，后端会直接使用保存的凭据连接 SSH。

先点击“检查并预览”，确认两份文件的预计操作后再点击“确认同步”或“从远程删除配置”。同步会清理 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 及对应小写变量的旧赋值，再追加 `static/proxy_setting.sh` 中带 Mihomo 标记的唯一片段；删除操作会移除同一批变量，即使旧配置没有本工具标记，也不会删除 `.bashrc` 或 `.env` 文件本身。

- 不存在的 `.bashrc`、`.codex` 目录或 `.codex/.env` 会自动创建。
- 远端每个配置文件的同步备份只保留时间最近的 3 个。
- 每份已有且实际修改的文件都会在远端同目录创建 `*.mihomo-proxy.<时间戳>.*.bak` 备份。
- 成功后页面仅在当前会话显示修改后的完整内容，并以固定高度的滚动代码框呈现；刷新、重新检查或修改连接信息会清除过期显示内容，同步完成后会清除密码。
- 登录密码不会保存、不会写入日志；服务只允许输入 IP 地址并固定连接 SSH 22 端口，也不会执行远端 shell 命令。
- 当前选择为自动接受远端 SSH 主机密钥，无法防范中间人攻击；仅应在可信局域网和设备上使用此页面。

## 手动管理网页服务

查看状态：

```bash
systemctl --user status mihomo-config-editor.service --no-pager
```

启动：

```bash
systemctl --user start mihomo-config-editor.service
```

停止：

```bash
systemctl --user stop mihomo-config-editor.service
```

重启：

```bash
systemctl --user restart mihomo-config-editor.service
```

设置开机自启：

```bash
systemctl --user enable mihomo-config-editor.service
```

取消开机自启：

```bash
systemctl --user disable mihomo-config-editor.service
```

修改 service 文件后重载并重启：

```bash
systemctl --user daemon-reload
systemctl --user restart mihomo-config-editor.service
```

查看日志：

```bash
journalctl --user -u mihomo-config-editor.service -f
```

## 手动管理 Mihomo 内核服务

修改 `config.yaml` 后，如果需要手动重载 systemd 并重启内核：

```bash
systemctl --user daemon-reload
systemctl --user restart mihomo.service
```

查看内核服务状态：

```bash
systemctl --user status mihomo.service --no-pager
```

查看内核日志：

```bash
journalctl --user -u mihomo.service -f
```

## 端口检查

确认网页服务监听 `9091`：

```bash
ss -ltnp | rg ':9091'
```

确认 Mihomo 面板仍监听 `9090`：

```bash
ss -ltnp | rg ':9090'
```
