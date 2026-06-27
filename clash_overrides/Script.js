function main(config, profileName) {
  // 自动测速/url-test 健康检查间隔，单位：秒。
  const autoTestInterval = 120;
  // fallback 兜底健康检查间隔，单位：秒。
  const fallbackInterval = 120;
  const defaultAutoGroupName = "自动选择";
  const aiGroupName = "AI";
  const aiAutoGroupName = "AI自动";
  const aiFallbackGroupName = "AI自动兜底";
  const countryAutoGroups = [
    {
      name: "新加坡自动",
      keywords: ["新加坡", "狮城", "SG", "SGP", "Singapore", "🇸🇬"]
    },
    {
      name: "日本自动",
      keywords: ["日本", "东京", "大阪", "JP", "JPN", "Japan", "Tokyo", "Osaka", "🇯🇵"]
    },
    {
      name: "美国自动",
      keywords: ["美国", "美國", "美", "US", "USA", "United States", "America", "Los Angeles", "San Jose", "Seattle", "Dallas", "New York", "🇺🇸"]
    }
  ];

  const blockKeywords = [
    "香港", "港", "HK", "HKG", "Hong Kong", "HongKong", "🇭🇰",
    "台湾", "台灣", "台北", "臺北", "TW", "TWN", "Taiwan", "Taipei", "TPE", "🇹🇼"
  ];

  const infoKeywords = [
    "剩余流量", "套餐到期", "距离下次", "官网", "流量", "到期", "过期",
    "expire", "traffic", "subscription", "官网", "重置"
  ];
  
  // 对AI域名强制代理：如果不需要可以注释掉留空数组 
  const forceProxyDomains = [
    // OpenAI
    "openai.com",
    "chatgpt.com",
    "api.openai.com",
    "auth.openai.com",
    "oaistatic.com",
    "oaiusercontent.com"
  ];

  // 强制直连：Outlook、Teams、Windows网路检测
  const forceDirectDomains = [
    "outlook.cloud.microsoft",
    "outlook.office.com",
    "outlook.office365.com",
    "outlook.live.com",
    "outlook.com",
    "live.com",
    "office.com",
    "office.net",
    "office365.com",
    "microsoft.com",
    "msftncsi.com",
    "msftconnecttest.com",
    "static.microsoft",
    "cdn.office.net",
    "sharepoint.com",
    "onedrive.com",
    "cloud.microsoft",
    "microsoftusercontent.com",
    "smtp.office365.com",
    "imap-mail.outlook.com",
    "smtp-mail.outlook.com",
    "autodiscover-s.outlook.com",
    "teams.cloud.microsoft",
    "teams.microsoft.com",
    "skype.com",
    "lync.com",
    "broadcast.skype.com",
    "login.microsoftonline.com",
    "microsoftonline.com",
    "msftauth.net",
    "msauth.net"
  ];

  // Clash/mihomo 自己在向这些 DNS 服务器查询域名，但它被规则匹配到 良心云 走代理了。
  // DNS 查询走代理有时会导致 Microsoft/Outlook 这类客户端解析、认证、连接变得奇怪
  const forceDirectCidrs = [
    // "1.1.1.1/32",
    // "8.8.8.8/32"
  ];

  if (!config || typeof config !== "object") {
    return config;
  }

  config.proxies = Array.isArray(config.proxies) ? config.proxies : [];
  config["proxy-groups"] = Array.isArray(config["proxy-groups"])
    ? config["proxy-groups"]
    : [];
  config.rules = Array.isArray(config.rules) ? config.rules : [];

  const proxyGroups = config["proxy-groups"];
  const realNodeNames = config.proxies.map((p) => p.name).filter(Boolean);
  const realNodeSet = new Set(realNodeNames);
  const countryAutoGroupNames = countryAutoGroups.map((group) => group.name);

  function includesAny(value, keywords) {
    const text = String(value || "").toLowerCase();
    return keywords.some((kw) => text.includes(String(kw).toLowerCase()));
  }

  function isBlockedName(name) {
    return includesAny(name, blockKeywords);
  }

  function isInfoNodeName(name) {
    return includesAny(name, infoKeywords);
  }

  function isUsableRealNode(name) {
    return realNodeSet.has(name) && !isInfoNodeName(name);
  }

  function isWantedRealNode(name) {
    return isUsableRealNode(name) && !isBlockedName(name);
  }

  function isCountryAutoGroupName(name) {
    return countryAutoGroupNames.includes(name);
  }

  function isAiAutoGroupName(name) {
    const text = String(name || "");
    return name !== aiGroupName &&
      name !== aiFallbackGroupName &&
      /AI|OpenAI|ChatGPT/i.test(text) &&
      /自动|auto|♻/i.test(text);
  }

  function unique(names) {
    return [...new Set(names)];
  }

  function existingProxyGroupNames(names) {
    return unique(names).filter((name) =>
      proxyGroups.some((group) => group && group.name === name)
    );
  }

  function firstExistingProxyGroupName(names) {
    return names.find((name) =>
      proxyGroups.some((group) => group && group.name === name)
    );
  }

  function replaceRulePolicy(rule, fromNames, toName) {
    if (typeof rule !== "string") {
      return rule;
    }

    const parts = rule.split(",");
    for (let i = parts.length - 1; i >= 1; i -= 1) {
      const value = parts[i].trim();
      if (value === "no-resolve") {
        continue;
      }

      if (!fromNames.has(value)) {
        continue;
      }

      const leading = parts[i].match(/^\s*/)[0];
      const trailing = parts[i].match(/\s*$/)[0];
      parts[i] = `${leading}${toName}${trailing}`;
      return parts.join(",");
    }

    return rule;
  }

  // 将所有已有的“走代理”规则统一改到 AI 自动兜底。
  // DIRECT/REJECT/PASS 这类明确直连、拦截或透传的规则保持不变。
  function forceRulePolicyToAiFallback(rule) {
    if (typeof rule !== "string") {
      return rule;
    }

    const parts = rule.split(",");
    for (let i = parts.length - 1; i >= 1; i -= 1) {
      const value = parts[i].trim();

      // Clash 的 IP 规则可能以 no-resolve 结尾，真正的策略在它前一个字段。
      if (value === "no-resolve") {
        continue;
      }

      // 不接管明确直连、拦截或透传的规则。
      if (["DIRECT", "REJECT", "REJECT-DROP", "PASS"].includes(value)) {
        return rule;
      }

      // 已经是 AI 自动兜底的规则不重复改写，保留原格式。
      if (value === aiFallbackGroupName) {
        return rule;
      }

      // 只替换策略字段，保留字段前后的空格格式。
      const leading = parts[i].match(/^\s*/)[0];
      const trailing = parts[i].match(/\s*$/)[0];
      parts[i] = `${leading}${aiFallbackGroupName}${trailing}`;
      return parts.join(",");
    }

    return rule;
  }

  function includesCountryKeyword(value, keywords) {
    const text = String(value || "");
    const lowerText = text.toLowerCase();

    return keywords.some((kw) => {
      const keyword = String(kw);
      const lowerKeyword = keyword.toLowerCase();

      if (/^[A-Z]{2,3}$/.test(keyword)) {
        const escaped = lowerKeyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`).test(lowerText);
      }

      return lowerText.includes(lowerKeyword);
    });
  }

  function countryNodes(keywords) {
    return unique(realNodeNames.filter((name) =>
      isUsableRealNode(name) && includesCountryKeyword(name, keywords)
    ));
  }

  function wantedNodesFromGroup(group) {
    if (!group || !Array.isArray(group.proxies)) {
      return [];
    }
    return unique(group.proxies.filter(isUsableRealNode));
  }

  function wantedAllNodes() {
    return unique(realNodeNames.filter(isUsableRealNode));
  }

  function wantedAiNodes() {
    return unique(realNodeNames.filter(isWantedRealNode));
  }

  function findBestSourceGroup(autoGroupName) {
    const selectGroups = proxyGroups.filter((group) =>
      group &&
      group.type === "select" &&
      Array.isArray(group.proxies)
    );

    const groupsContainingAuto = selectGroups.filter((group) =>
      group.proxies.includes(autoGroupName)
    );

    const candidates = groupsContainingAuto.length > 0 ? groupsContainingAuto : selectGroups;

    return candidates
      .map((group) => ({ group, nodes: wantedNodesFromGroup(group) }))
      .sort((a, b) => b.nodes.length - a.nodes.length)[0] || null;
  }

  function addOptionsToSelectGroup(group, options, preferredFirstOptions) {
    if (!group || group.type !== "select" || !Array.isArray(group.proxies)) {
      return;
    }

    const currentProxies = group.proxies;

    group.proxies = unique([
      ...preferredFirstOptions,
      ...options,
      ...currentProxies
    ]);
  }

  if (wantedAllNodes().length === 0) {
    return config;
  }

  let autoGroups = proxyGroups.filter((group) =>
    group &&
    group.type === "url-test" &&
    group.name !== aiAutoGroupName &&
    !isAiAutoGroupName(group.name) &&
    !isCountryAutoGroupName(group.name) &&
    /自动|auto|♻/i.test(String(group.name || ""))
  );

  if (autoGroups.length === 0) {
    const source = findBestSourceGroup(defaultAutoGroupName);
    const nodes = source?.nodes?.length ? source.nodes : wantedAllNodes();
    const autoGroup = {
      name: defaultAutoGroupName,
      type: "url-test",
      proxies: nodes,
      url: "https://www.gstatic.com/generate_204",
      interval: autoTestInterval,
      tolerance: 50
    };

    proxyGroups.unshift(autoGroup);
    autoGroups = [autoGroup];

    if (source?.group && !source.group.proxies.includes(defaultAutoGroupName)) {
      source.group.proxies.unshift(defaultAutoGroupName);
    }
  }

  const allWantedNodes = wantedAllNodes();

  for (const autoGroup of autoGroups) {
    const source = findBestSourceGroup(autoGroup.name);
    const nodes = autoGroup.name === defaultAutoGroupName
      ? allWantedNodes
      : source?.nodes?.length ? source.nodes : allWantedNodes;

    autoGroup.type = "url-test";
    autoGroup.proxies = nodes;
    autoGroup.url = autoGroup.url || "https://www.gstatic.com/generate_204";
    autoGroup.interval = autoGroup.interval || autoTestInterval;
    autoGroup.tolerance = autoGroup.tolerance || 50;

    if (source?.group && !source.group.proxies.includes(autoGroup.name)) {
      source.group.proxies.unshift(autoGroup.name);
    }
  }

  for (let i = proxyGroups.length - 1; i >= 0; i -= 1) {
    if (isCountryAutoGroupName(proxyGroups[i]?.name)) {
      proxyGroups.splice(i, 1);
    }
  }

  const countryGroupNames = [];
  for (const countryGroup of countryAutoGroups) {
    const nodes = countryNodes(countryGroup.keywords);
    if (nodes.length === 0) {
      continue;
    }

    let group = proxyGroups.find((item) => item.name === countryGroup.name);
    if (!group) {
      group = {
        name: countryGroup.name,
        type: "url-test",
        proxies: []
      };
      proxyGroups.unshift(group);
    }

    group.type = "url-test";
    group.proxies = nodes;
    group.url = group.url || "https://www.gstatic.com/generate_204";
    group.interval = group.interval || autoTestInterval;
    group.tolerance = group.tolerance || 50;
    countryGroupNames.push(group.name);
  }

  const allAiNodes = wantedAiNodes();
  let aiAutoGroup = proxyGroups.find((group) => group.name === aiAutoGroupName);
  if (allAiNodes.length > 0) {
    if (!aiAutoGroup) {
      aiAutoGroup = {
        name: aiAutoGroupName,
        type: "url-test",
        proxies: []
      };
      proxyGroups.unshift(aiAutoGroup);
    }

    for (const group of proxyGroups.filter((item) => item && isAiAutoGroupName(item.name))) {
      group.type = "url-test";
      group.proxies = allAiNodes;
      group.url = group.url || "https://www.gstatic.com/generate_204";
      group.interval = group.interval || autoTestInterval;
      group.tolerance = group.tolerance || 50;
    }
  } else {
    for (let i = proxyGroups.length - 1; i >= 0; i -= 1) {
      if (isAiAutoGroupName(proxyGroups[i]?.name)) {
        proxyGroups.splice(i, 1);
      }
    }
    aiAutoGroup = null;
  }

  const autoGroupNames = autoGroups.map((group) => group.name);

  let aiGroup = proxyGroups.find((group) => group.name === aiGroupName);
  if (!aiGroup) {
    aiGroup = {
      name: aiGroupName,
      type: "select",
      proxies: []
    };
    proxyGroups.unshift(aiGroup);
  }

  aiGroup.type = "select";
  aiGroup.proxies = unique([
    aiFallbackGroupName,
    ...countryGroupNames,
    ...(aiAutoGroup ? [aiAutoGroupName] : []),
    ...autoGroups.map((group) => group.name),
    ...(Array.isArray(aiGroup.proxies)
      ? aiGroup.proxies.filter((name) => !isCountryAutoGroupName(name))
      : []),
    ...allAiNodes
  ]).filter((name) => !realNodeSet.has(name) || isWantedRealNode(name));

  const aiAutoGroupCandidates = proxyGroups
    .filter((group) => group && isAiAutoGroupName(group.name))
    .map((group) => group.name);

  const defaultFallbackCandidates = existingProxyGroupNames([
    firstExistingProxyGroupName(["新加坡自动选择", "新加坡自动"]),
    firstExistingProxyGroupName(["日本自动选择", "日本自动"]),
    firstExistingProxyGroupName(["美国自动选择", "美国自动"]),
    firstExistingProxyGroupName([aiAutoGroupName, "AI自动选择", ...aiAutoGroupCandidates]),
    firstExistingProxyGroupName([defaultAutoGroupName, ...autoGroupNames])
  ].filter(Boolean)).filter((name) => name !== aiFallbackGroupName);

  let aiFallbackGroup = proxyGroups.find((group) => group.name === aiFallbackGroupName);
  if (!aiFallbackGroup) {
    aiFallbackGroup = {
      name: aiFallbackGroupName,
      type: "fallback",
      proxies: []
    };
    proxyGroups.unshift(aiFallbackGroup);
  }

  aiFallbackGroup.type = "fallback";
  aiFallbackGroup.proxies = defaultFallbackCandidates.length
    ? defaultFallbackCandidates
    : allWantedNodes;
  aiFallbackGroup.url = aiFallbackGroup.url || "https://www.gstatic.com/generate_204";
  aiFallbackGroup.interval = aiFallbackGroup.interval || fallbackInterval;

  const preferredMainGroupFirstOptions = unique([
    aiFallbackGroupName,
    ...(aiAutoGroup ? [aiAutoGroupName] : []),
    defaultAutoGroupName,
    ...autoGroupNames
  ]);
  const mainSelectGroups = proxyGroups.filter((group) =>
    group &&
    group.type === "select" &&
    group.name !== aiGroupName &&
    Array.isArray(group.proxies) &&
    (
      group.proxies.includes(defaultAutoGroupName) ||
      autoGroupNames.some((name) => group.proxies.includes(name))
    )
  );

  for (const group of mainSelectGroups) {
    addOptionsToSelectGroup(group, countryGroupNames, preferredMainGroupFirstOptions);
  }

  const newRules = forceProxyDomains.map(
    (domain) => `DOMAIN-SUFFIX,${domain},${aiFallbackGroupName}`
  );

  // 这些域名即使在“其它代理规则全部走 AI 自动兜底”时，也必须优先直连。
  const directRules = forceDirectDomains.map(
    (domain) => `DOMAIN-SUFFIX,${domain},DIRECT`
  );
  const directIpRules = forceDirectCidrs.map(
    (cidr) => `IP-CIDR,${cidr},DIRECT,no-resolve`
  );

  // 先清理旧的强制代理/强制直连规则，避免重复规则影响判断。
  const cleanedOldRules = config.rules.filter((rule) => {
    const text = String(rule);
    const isForceProxyRule = forceProxyDomains.some((domain) =>
      text.includes(`DOMAIN-SUFFIX,${domain},`) ||
      text.includes(`DOMAIN,${domain},`)
    );
    const isForceDirectRule = forceDirectDomains.some((domain) =>
      text.includes(`DOMAIN-SUFFIX,${domain},`) ||
      text.includes(`DOMAIN,${domain},`)
    );
    const isForceDirectIpRule = forceDirectCidrs.some((cidr) =>
      text.includes(`IP-CIDR,${cidr},`)
    );

    return !isForceProxyRule && !isForceDirectRule && !isForceDirectIpRule;
  });

  // 第一步：把已知 AI/自动策略名改到 AI 自动兜底。
  // 第二步：把剩余非 DIRECT/REJECT/PASS 的代理规则也统一改到 AI 自动兜底。
  const fallbackRulePolicyNames = new Set(unique([
    aiGroupName,
    aiAutoGroupName,
    defaultAutoGroupName,
    "AI自动选择",
    ...aiAutoGroupCandidates,
    ...autoGroupNames
  ]).filter((name) => name !== aiFallbackGroupName));
  const rewrittenOldRules = cleanedOldRules
    .map((rule) => replaceRulePolicy(rule, fallbackRulePolicyNames, aiFallbackGroupName))
    .map(forceRulePolicyToAiFallback);

  // 规则顺序很关键：显式直连优先，其次是强制走 AI 的域名，
  // 最后才放入已经统一改写到 AI 自动兜底的原有规则。
  config.rules = directIpRules.concat(directRules, newRules, rewrittenOldRules);

  return config;
}
