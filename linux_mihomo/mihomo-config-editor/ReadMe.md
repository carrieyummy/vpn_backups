# Mihomo Config Editor

一个局域网内使用的 `config.yaml` 简易网页编辑器。

- 访问地址：`http://<MIHOMO_LAN_IP>:9091`
- 登录密钥：读取 `${HOME}/.config/mihomo/secret`
- 配置文件：`${HOME}/.config/mihomo/config.yaml`
- 服务文件：`${HOME}/.config/systemd/user/mihomo-config-editor.service`

仓库中的地址和路径均为通用示例或占位符；实际订阅地址与密钥只保留在运行时私密文件中，不应提交。

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
