# Project Rules

- 本项目用于备份我的 VPN 配置，不要暴露个人信息，如 `10.100.10.xx`、真实订阅 URL、代理地址、面板密钥、provider 节点文件内容。如果发现个人信息，先停止展示具体值，询问我怎么处理，同时给我处理方案供选择。
- 仓库内配置和说明使用占位符，不提交真实运行值。常用占位符包括 `<MIHOMO_LAN_IP>`、`<LAN_CLIENT_IP>`、`<LIANGXINYUN_SUBSCRIPTION_URL>`、`<MOJIE_SUBSCRIPTION_URL>`、`<MIHOMO_SECRET>`。
- `linux_mihomo/.codex/.env` 保留文件名，但只能作为占位符模板；不要写入真实 IP、真实代理地址或密钥。
- `mihomo/providers/*`、`$HOME/.config/mihomo/config.yaml`、`$HOME/.config/mihomo/secret` 是运行时私密内容，不要把真实内容复制进仓库或回复里。
- 增强脚本的通用性，不要写死 `/home/<用户名>` 路径。普通 shell 脚本使用 `$HOME` 或 `${HOME}`，systemd user service 使用 `%h`。
