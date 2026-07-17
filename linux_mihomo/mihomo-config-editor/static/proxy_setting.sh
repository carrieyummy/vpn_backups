# >>> mihomo-config-editor: proxy environment >>>
# 解决codex插件 reconnect 且必须开 tun 的问题。
# Cursor 的远程 extensionHost 是以 --useHostProxy=false 启动的，所以它没有继承宿主代理设置。Codex 又没有自己的代理环境变量，于是就直连了 所以只能通过配置环境变量解决
# 同时配置大小写和 ALL_PROXY，更稳一点
export HTTP_PROXY="http://<MIHOMO_LAN_IP>:7890"
export HTTPS_PROXY="http://<MIHOMO_LAN_IP>:7890"
export ALL_PROXY="http://<MIHOMO_LAN_IP>:7890"

export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export all_proxy="$ALL_PROXY"

export NO_PROXY="localhost,127.0.0.1,::1,10.0.0.0/8,192.168.20.0/24"
export no_proxy="$NO_PROXY"
# <<< mihomo-config-editor: proxy environment <<<
