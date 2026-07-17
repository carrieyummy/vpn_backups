# Clash 系 VPN 客户端覆写脚本说明

本目录用于保存 Clash 系 VPN 客户端的JavaScript 覆写脚本。

- `Script.js`

这个脚本会在订阅配置加载后修改 Clash 配置，自动整理代理组和规则，核心目标是只使用非中国（香港、台湾）节点，让 AI 相关流量优先走稳定的自动兜底线路，同时让 Outlook、Teams、Windows 网络检测等 Microsoft 服务保持直连。

使用这个脚本后，选择 `AI自动兜底` 代理组，AI 相关流量会优先走新加坡自动节点；如果不可用，会自动兜底到日本、美国等候选节点，同时 Microsoft 相关服务仍保持直连。

- `Script_Clash_Mi.js`

这是 iPad、iPhone 上 Clash Mi 客户端的专用版本。把 `节点选择` 固定放到代理组最前面，。

它与 `Script.js` 共用新加坡、日本、美国自动测速和 `AI自动兜底` 的节点筛选逻辑；主要区别是：`Script_Clash_Mi.js` 会把需要代理的规则统一交给 `节点选择`。这样才能在 Clash Mi 首页手动选择 `AI自动兜底`、地区自动组或具体节点。

## 已测试客户端

`Script.js` 已在以下客户端中测试可用：

- macOS：Clash Verge
- Windows：Clash Verge
- Android：FlClash

`Script_Clash_Mi.js` 已在以下客户端中测试可用：

- iPad、iPhone：Clash Mi

## 在 Clash Verge 中使用

1. 打开 Clash Verge 。
2. 进入 `订阅` 或 `Profiles` 页面。
3. 右击全局扩展脚本 -> 编辑文件，把 `Script.js` 全文粘贴进去并保存。
4. 回到代理页面，确认出现 `AI`、`AI自动兜底`、`新加坡自动`、`日本自动`、`美国自动` 等代理组。
5. 点击 `首页`，在 `当前节点` 栏，选择 `AI自动兜底` 作为默认代理组。

## 在 Android FlClash 中使用

1. 点击 `配置` -> 某个订阅 -> `更多` -> `覆写`。
2. 点击 `前往配置脚本` -> 覆写模式 `脚本` -> `添加` -> 把 `Script.js` 全文粘贴进去并保存 -> 选择这个脚本
3. 在 `代理选项卡` 看到覆写后的新分组 -> 选择 `AI自动兜底` 作为默认代理组。

不同版本的 VPN 客户端菜单名称可能略有不同，但本质都是把 `Script.js` 作为订阅解析后的 JavaScript 覆写脚本执行。

## 在 iPad、iPhone Clash Mi 中使用

1. 在 Clash Mi 中打开订阅或配置的覆写脚本设置。
2. 新建或编辑 JavaScript 覆写脚本，把 `Script_Clash_Mi.js` 全文粘贴进去并保存。
3. 将该脚本应用到当前订阅，然后重新更新订阅或重新加载配置。
4. 回到首页，确认第一个代理组为 `节点选择`。
5. 在 `节点选择` 中选择 `AI自动兜底` 作为日常默认策略；需要固定地区或节点时，也可以在这里改选 `新加坡自动`、`日本自动`、`美国自动` 或具体节点。

Clash Mi 的菜单名称会随版本变化，但应始终使用 `Script_Clash_Mi.js`，不要使用通用版 `Script.js`。该专用脚本会确保 `节点选择` 位于第一个代理组，以适配 Clash Mi 首页的展示方式。

## 脚本会生成的代理组

脚本会维护以下关键代理组：

- `AI`（仅 `Script.js`）
- `节点选择`（仅 `Script_Clash_Mi.js`）
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

`自动选择` 不在 `AI自动兜底` 的候选列表中。实际生成时，只有当前订阅中存在匹配节点的代理组才会被加入。

`Script.js` 会维护 `AI` 选择组，并建议把 `AI自动兜底` 作为客户端默认代理组。`Script_Clash_Mi.js` 则维护 `节点选择` 选择组，并将其移动到第一位；日常使用时，在 `节点选择` 中选择 `AI自动兜底` 即可。

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

`Script.js` 会把大部分原本走代理的规则统一改到：

```text
AI自动兜底
```

但下面这些策略不会被改写：

- `DIRECT`
- `REJECT`
- `REJECT-DROP`
- `PASS`

因此，原配置中明确直连、拒绝或透传的规则会保留。

`Script_Clash_Mi.js` 的规则改写方式不同：它会把大部分原本走代理的规则统一改到 `节点选择`。因此，在 Clash Mi 首页切换 `节点选择` 的选项后，新的代理连接会使用你选定的自动策略或具体节点；`DIRECT`、`REJECT`、`REJECT-DROP`、`PASS` 仍会保持原样。

## 强制代理域名

`forceProxyDomains` 用于指定必须走代理的域名。当前默认包含：

```js
const forceProxyDomains = [
  "openai.com",
  "chatgpt.com",
  "api.openai.com",
  "auth.openai.com",
  "oaistatic.com",
  "oaiusercontent.com",
];
```

在 `Script.js` 中，这些域名会走 `AI自动兜底`；在 `Script_Clash_Mi.js` 中，这些域名会走 `节点选择`，并跟随你在 Clash Mi 首页的选择。

如果不想强制代理这些域名，可以把数组改成空数组：

```js
const forceProxyDomains = [];
```

如果要增加其他 AI 服务域名，直接继续添加 `DOMAIN-SUFFIX` 对应的主域名即可。

## 生成本地版 `Script.local.js` 的提示词

`Script.local.js` 是在 `Script.js` 基础上维护的本地版本，可用于保留个人自定义域名。它不应提交到仓库。需要用 AI 生成或同步本地版本时，可将下面的提示词连同当前的 `Script.js` 和现有 `Script.local.js` 一起提供给 AI：

```text
请以 `clash_overrides/Script.js` 为上游源文件，生成并写入
`clash_overrides/Script.local.js`。

要求：
1. 完整同步 `Script.js` 的最新功能、结构、注释和配置；除个人自定义域名区块外，两者应保持一致。
2. 保留现有 `Script.local.js` 中由 START 和 END 标记界定的个人自定义域名区块，不能删除、改写、移动或在回复中展示其中的域名。
3. 若本地文件尚不存在该区块，则在与 `forceProxyDomains` 相关的位置创建清晰的 START/END 标记，并仅在该区块中添加由用户另行提供的自定义域名。
4. 个人域名只能存在于 `Script.local.js`，绝不能写入 `Script.js`、README、提交信息或任何共享文件。
5. 不要写入真实订阅 URL、IP 地址、代理地址、密钥或其他私密运行值；需要时使用占位符。
6. 只修改 `clash_overrides/Script.local.js`，不要修改 `Script.js`。
7. 完成后检查 JavaScript 语法，并简要说明是否成功保留了本地区块；不要输出本地区块的具体内容。
```

## 强制直连域名

`forceDirectDomains` 用于指定必须直连的域名。当前主要包含 Outlook、Teams、Microsoft 登录、Office、OneDrive、Windows 网络检测相关域名。

这些规则会被放在强制代理规则前面，所以优先级更高。也就是说，即使脚本把其它代理规则统一改到 `AI自动兜底` 或 `节点选择`，这些 Microsoft 相关域名仍然会走 `DIRECT`。

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

`AI自动兜底` 是 `fallback` 代理组，会按以下优先级检查实际存在的候选代理组：

```text
新加坡自动 -> 日本自动 -> 美国自动 -> AI自动
```

`自动选择` 不属于 `AI自动兜底` 的候选项。若上述候选组均不存在，脚本才会让 `AI自动兜底` 直接使用全部可用节点。

`新加坡自动` 与 `AI自动兜底` 的健康检查相互独立：前者会根据自己的测速结果选择较快的可用新加坡节点；后者按自身的健康检查结果，从候选组中选择优先级最高的可用组。因此，不能保证单个新加坡节点故障时一定先在新加坡组内完成切换、再切到日本组；当 `AI自动兜底` 认为新加坡组不可用时，新建连接会改走日本组或后续候选组。

默认健康检查间隔均为 60 秒，但由两个独立配置项控制：

```text
autoTestInterval: 60  # url-test 自动测速组
fallbackInterval: 60  # fallback 兜底组
```

脚本会为这些 `url-test` 和 `fallback` 组写入 `lazy: false`，使其不采用懒检查。前面的候选组恢复后，`fallback` 会在后续健康检查中为新建连接选择更靠前的可用组；已有连接不会被迁移。

## 常见调整

如果想更快发现节点故障或恢复，可以分别把脚本开头的 `autoTestInterval`（`url-test` 自动测速组）和 `fallbackInterval`（`fallback` 兜底组）从 `60` 改小，例如：

```js
const autoTestInterval = 45;
const fallbackInterval = 45;
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
- 修改 `Script_Clash_Mi.js` 后需要在 Clash Mi 中重新更新订阅或重新加载配置。
- 如果订阅节点命名不包含地区关键词，对应国家自动组可能不会生成。
- 规则顺序很重要：脚本会把强制直连规则放在最前面，其次是强制代理域名，最后才是改写后的原始规则。通用版的改写规则走 `AI自动兜底`，Clash Mi 专用版则走 `节点选择`。
