# Clash 系 VPN 客户端覆写脚本说明

本目录用于保存 Clash Verge / Clash Verge Rev / FlClash 的 JavaScript 覆写脚本：

- `Script.js`

这个脚本会在订阅配置加载后修改 Clash 配置，自动整理代理组和规则，核心目标是让 AI 相关流量优先走稳定的自动兜底线路，同时让 Outlook、Teams、Windows 网络检测等 Microsoft 服务保持直连。

## 已测试客户端

`Script.js` 已在以下客户端中测试可用：

- macOS：Clash Verge
- Windows：Clash Verge
- Android：FlClash

## 在 Clash Verge 中使用

1. 打开 Clash Verge 。
2. 进入 `订阅` 或 `Profiles` 页面。
3. 右击全局扩展脚本 -> 编辑文件，把 `Script.js` 全文粘贴进去并保存。
4. 回到代理页面，确认出现 `AI`、`AI自动兜底`、`新加坡自动`、`日本自动`、`美国自动` 等代理组。
5. 点击 `首页`，在 `当前节点` 栏，选择 `AI自动兜底` 作为默认代理组。

不同版本的 VPN 客户端菜单名称可能略有不同，但本质都是把 `Script.js` 作为订阅解析后的 JavaScript 覆写脚本执行。

## 脚本会生成的代理组

脚本会维护这些关键代理组：

- `AI`
- `AI自动`
- `AI自动兜底`
- `新加坡自动`
- `日本自动`
- `美国自动`
- `自动选择`

其中最重要的是 `AI自动兜底`。它是一个 `fallback` 代理组，默认候选顺序大致是：

1. `新加坡自动`
2. `日本自动`
3. `美国自动`
4. `AI自动`
5. `自动选择`

实际生成时，只有当前订阅中存在匹配节点的代理组才会被加入。

## 节点筛选逻辑

脚本会从订阅里的真实节点名称中识别地区：

- 新加坡：匹配 `新加坡`、`狮城`、`SG`、`Singapore`、`🇸🇬` 等关键词。
- 日本：匹配 `日本`、`东京`、`大阪`、`JP`、`Japan`、`Tokyo`、`🇯🇵` 等关键词。
- 美国：匹配 `美国`、`US`、`USA`、`United States`、`Los Angeles`、`Seattle`、`🇺🇸` 等关键词。

`AI自动` 和 `AI自动兜底` 默认会排除香港、台湾节点，避免 AI 流量误走这些地区：

- 香港关键词：`香港`、`HK`、`Hong Kong`、`🇭🇰` 等。
- 台湾关键词：`台湾`、`TW`、`Taiwan`、`Taipei`、`🇹🇼` 等。

脚本也会排除订阅信息节点，例如 `剩余流量`、`套餐到期`、`traffic`、`expire` 这类不是真实代理的节点。

## 规则改写逻辑

脚本会把大部分原本走代理的规则统一改到：

```text
AI自动兜底
```

但下面这些策略不会被改写：

- `DIRECT`
- `REJECT`
- `REJECT-DROP`
- `PASS`

因此，原配置中明确直连、拒绝或透传的规则会保留。

## 强制代理域名

`Script.js` 里的 `forceProxyDomains` 用于指定必须走 `AI自动兜底` 的域名。当前默认包含：

```js
const forceProxyDomains = [
  "openai.com",
  "chatgpt.com",
  "api.openai.com",
  "auth.openai.com",
  "oaistatic.com",
  "oaiusercontent.com"
];
```

如果不想强制代理这些域名，可以把数组改成空数组：

```js
const forceProxyDomains = [];
```

如果要增加其他 AI 服务域名，直接继续添加 `DOMAIN-SUFFIX` 对应的主域名即可。

## 强制直连域名

`forceDirectDomains` 用于指定必须直连的域名。当前主要包含 Outlook、Teams、Microsoft 登录、Office、OneDrive、Windows 网络检测相关域名。

这些规则会被放在强制代理规则前面，所以优先级更高。也就是说，即使脚本把其它代理规则统一改到 `AI自动兜底`，这些 Microsoft 相关域名仍然会走 `DIRECT`。

如果 Outlook、Teams 或 Microsoft 登录异常，优先检查这里是否需要补充域名。

## DNS 直连 IP

`forceDirectCidrs` 默认是空的：

```js
const forceDirectCidrs = [
  // "1.1.1.1/32",
  // "8.8.8.8/32"
];
```

如果发现 Clash/mihomo 自己的 DNS 查询被代理规则错误接管，可以取消注释或添加 DNS 服务器 IP，让这些 IP 强制直连。

## 自动切换行为

`新加坡自动`、`日本自动`、`美国自动` 是 `url-test` 代理组，会在同一地区的节点里选择延迟较低且可用的节点。

`AI自动兜底` 是 `fallback` 代理组，会按顺序检查候选代理组：

```text
新加坡自动 -> 日本自动 -> 美国自动 -> AI自动 -> 自动选择
```

如果单个新加坡节点超时，`新加坡自动` 会先尝试其它新加坡节点。只有当整个 `新加坡自动` 不可用时，`AI自动兜底` 才会切到 `日本自动`。

默认健康检查间隔是：

```text
interval: 300
```

也就是大约 300 秒检查一次。前面的候选组恢复后，`fallback` 会在后续健康检查中切回更靠前的可用组。

## 常见调整

如果想更快发现节点故障或恢复，可以把脚本里的 `interval` 从 `300` 改小，例如：

```js
interval: 60
```

如果想调整地区优先级，可以修改 `defaultFallbackCandidates` 里的候选顺序。

如果想增加国家自动组，可以在 `countryAutoGroups` 中添加新的对象，例如：

```js
{
  name: "韩国自动",
  keywords: ["韩国", "韓國", "KR", "KOR", "Korea", "Seoul", "🇰🇷"]
}
```

## 注意事项

- 修改 `Script.js` 后需要在 Clash Verge 中重新更新订阅或重新应用配置。
- 如果订阅节点命名不包含地区关键词，对应国家自动组可能不会生成。
- 规则顺序很重要：脚本会把强制直连规则放在最前面，其次是强制代理域名，最后才是改写后的原始规则。
