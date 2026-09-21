const state = {
  currentPage: "overview",
  offline: false,
  queuePaused: false,
  selectedRiskFilter: "all",
  selectedTemplate: "风险清单",
  documents: [
    { name: "2025年银行流水扫描件.pdf", hash: "9f24a1c7...8d36", year: "2025", type: "银行流水", pages: 208, method: "视觉模型", status: "运行中", progress: 68.8 },
    { name: "2025年度财务报表附注.pdf", hash: "8b7d03f1...420c", year: "2025", type: "财务报表", pages: 86, method: "本地解析", status: "已完成" },
    { name: "应收账款账龄分析.xlsx", hash: "64ac917e...5fb2", year: "2025", type: "明细账", pages: 12, method: "本地解析", status: "已完成" },
    { name: "关联方往来核对表.xlsx", hash: "1d34e0ba...92a5", year: "2025", type: "专项资料", pages: 9, method: "本地解析", status: "待处理" },
    { name: "2024年存货盘点报告.pdf", hash: "3ca6179e...0b11", year: "2024", type: "盘点报告", pages: 41, method: "本地解析", status: "已完成" },
    { name: "固定资产减值测试底稿.pdf", hash: "b5c38d04...a912", year: "2024", type: "审计底稿", pages: 28, method: "视觉模型", status: "失败" },
    { name: "2023年度总账.csv", hash: "a2950edc...7e43", year: "2023", type: "总账", pages: 1, method: "本地解析", status: "已完成" }
  ],
  risks: [
    { id: "R-2025-018", title: "应收账款期末异常增长", summary: "同比增长 47.3%，显著高于营业收入增速", level: "高", amount: "¥ 8,426.7 万", evidence: "5 / 6", status: "待复核", updated: "今天 15:08" },
    { id: "R-2025-011", title: "关联方资金往来披露不完整", summary: "三笔大额往来未匹配披露清单", level: "高", amount: "¥ 3,187.4 万", evidence: "7 / 9", status: "待补证", updated: "今天 14:46" },
    { id: "R-2024-037", title: "存货周转率连续下降", summary: "连续三年下降，部分库龄超过 720 天", level: "中", amount: "¥ 1,904.2 万", evidence: "4 / 4", status: "待复核", updated: "昨天 17:22" },
    { id: "R-2025-006", title: "期末收入确认集中", summary: "12 月收入占全年 28.6%，高于历史区间", level: "高", amount: "¥ 6,742.1 万", evidence: "8 / 8", status: "已核实", updated: "昨天 16:09" },
    { id: "R-2024-029", title: "在建工程长期未转固", summary: "两个项目完工后超过 14 个月仍未转固", level: "中", amount: "¥ 918.6 万", evidence: "6 / 6", status: "已核实", updated: "09-18 11:34" },
    { id: "R-2025-023", title: "供应商付款账户重复", summary: "四家供应商共用两个收款账户", level: "高", amount: "¥ 2,066.8 万", evidence: "3 / 5", status: "待补证", updated: "09-18 09:41" },
    { id: "R-2023-014", title: "固定资产减值迹象", summary: "闲置设备利用率低于 15%，未见减值测试", level: "中", amount: "¥ 782.3 万", evidence: "5 / 5", status: "已排除", updated: "09-17 18:05" }
  ],
  findings: [
    { level: "高", title: "应收账款增长与收入变动不匹配", rule: "AR-GROWTH-02", value: "+47.3%", evidence: "5 项证据", risk: "R-2025-018" },
    { level: "高", title: "年末收入确认集中度异常", rule: "REV-CUTOFF-04", value: "28.6%", evidence: "8 项证据", risk: "R-2025-006" },
    { level: "中", title: "存货周转天数连续三年上升", rule: "INV-TREND-03", value: "+31.8 天", evidence: "4 项证据", risk: "R-2024-037" }
  ],
  providers: [
    { name: "DeepSeek", model: "deepseek-chat", capabilities: "文本、JSON、长上下文", status: "已连接", enabled: true },
    { name: "智谱 GLM", model: "glm-4.6", capabilities: "文本、视觉、工具调用", status: "已连接", enabled: true },
    { name: "月之暗面 Kimi", model: "kimi-k2", capabilities: "文本、长上下文", status: "未测试", enabled: true },
    { name: "阿里云百炼", model: "qwen3-max", capabilities: "文本、视觉、Embedding", status: "已连接", enabled: true }
  ],
  exports: [
    { file: "华东制造_风险清单_2025-09-20.xlsx", template: "风险清单", snapshot: "16 项已核实风险", source: "本地模板", time: "今天 16:02" },
    { file: "华东制造_管理层材料_草稿.docx", template: "管理层材料", snapshot: "14 项已核实风险", source: "DeepSeek V3.2", time: "昨天 18:24" },
    { file: "华东制造_访谈提纲.pdf", template: "访谈提纲", snapshot: "12 项待复核风险", source: "GLM-4.6", time: "09-18 15:17" }
  ]
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function showToast(title, message = "") {
  const toast = document.createElement("div");
  toast.className = "toast";
  const strong = document.createElement("strong");
  strong.textContent = title;
  toast.appendChild(strong);
  if (message) {
    const span = document.createElement("span");
    span.textContent = message;
    toast.appendChild(span);
  }
  $("#toastRegion").appendChild(toast);
  setTimeout(() => toast.remove(), 3400);
}

function badgeClass(value) {
  if (["高", "失败"].includes(value)) return "badge-danger";
  if (["中", "待复核", "待补证", "待处理", "运行中", "未测试"].includes(value)) return "badge-warn";
  if (["已完成", "已核实", "已连接", "已关闭"].includes(value)) return "badge-ok";
  return "badge-neutral";
}

function setPage(page) {
  state.currentPage = page;
  $$(".page").forEach((item) => item.classList.toggle("is-active", item.id === `page-${page}`));
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.page === page));
  $("#sidebar").classList.remove("is-open");
  document.title = `${$(".nav-item.is-active span:nth-child(2)")?.textContent || "衡鉴"} | 衡鉴财务审计工作台`;
  if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  document.documentElement.scrollTop = 0;
  if (page === "analysis") requestAnimationFrame(drawChart);
}

function renderDocuments() {
  const query = $("#documentSearch").value.trim().toLowerCase();
  const filter = $("#documentFilter").value;
  const items = state.documents.filter((doc) => {
    const matchesQuery = `${doc.name} ${doc.year} ${doc.type} ${doc.status}`.toLowerCase().includes(query);
    const matchesStatus = filter === "all" || doc.status === filter;
    return matchesQuery && matchesStatus;
  });

  $("#documentRows").innerHTML = items.map((doc, index) => `
    <tr class="clickable" data-doc-index="${state.documents.indexOf(doc)}">
      <td class="doc-name"><strong>${escapeHtml(doc.name)}</strong><span>SHA-256 ${doc.hash}</span></td>
      <td>${doc.year}</td><td>${doc.type}</td><td class="num">${doc.pages}</td><td>${doc.method}</td>
      <td><span class="badge ${badgeClass(doc.status)}">${doc.status}${doc.progress ? ` ${doc.progress}%` : ""}</span></td>
      <td><button class="row-action" type="button">${doc.status === "失败" ? "重试" : "查看"}</button></td>
    </tr>`).join("");
  $("#documentEmpty").hidden = items.length > 0;
}

function renderRisks() {
  const query = $("#riskSearch").value.trim().toLowerCase();
  const level = $("#riskLevelFilter").value;
  const items = state.risks.filter((risk) => {
    const matchesQuery = `${risk.id} ${risk.title} ${risk.summary}`.toLowerCase().includes(query);
    const matchesStatus = state.selectedRiskFilter === "all" || risk.status === state.selectedRiskFilter;
    const matchesLevel = level === "all" || risk.level === level;
    return matchesQuery && matchesStatus && matchesLevel;
  });
  $("#riskRows").innerHTML = items.map((risk) => `
    <tr class="clickable risk-link" data-risk="${risk.id}" tabindex="0">
      <td><strong>${risk.id}　${risk.title}</strong><span class="cell-sub">${risk.summary}</span></td>
      <td><span class="badge ${badgeClass(risk.level)}">${risk.level}</span></td>
      <td class="num">${risk.amount}</td><td>${risk.evidence}</td>
      <td><span class="badge ${badgeClass(risk.status)}">${risk.status}</span></td><td>${risk.updated}</td>
    </tr>`).join("");
  $("#riskEmpty").hidden = items.length > 0;
  bindRiskLinks();
}

function renderFindings() {
  $("#findingList").innerHTML = state.findings.map((item) => `
    <article class="finding-item risk-link" data-risk="${item.risk}" tabindex="0">
      <span class="badge ${badgeClass(item.level)}">${item.level}优先级</span>
      <div class="finding-main"><strong>${item.title}</strong><span>规则 ${item.rule}，本地确定性计算</span></div>
      <div class="finding-value">${item.value}</div><div class="finding-evidence">${item.evidence}</div>
    </article>`).join("");
  bindRiskLinks();
}

function renderProviders() {
  $("#providerList").innerHTML = state.providers.map((provider, index) => `
    <div class="provider-row">
      <div class="provider-name"><strong>${provider.name}</strong><span>${provider.model}</span></div>
      <div class="provider-capabilities">${provider.capabilities}</div>
      <span class="badge ${badgeClass(provider.status)}">${provider.status}</span>
      <div class="provider-actions"><button type="button" data-provider-test="${index}">测试</button><button type="button" data-provider-edit="${index}">编辑</button></div>
    </div>`).join("");
}

function renderRouting() {
  const routes = [
    ["快速抽取", "低延迟与结构化输出", "DeepSeek V3.2", "Qwen3 Max"],
    ["视觉识别", "图片输入与 JSON 输出", "GLM-4.6V", "Qwen3 VL"],
    ["风险解释", "长上下文与稳定指令遵循", "DeepSeek V3.2", "Kimi K2"],
    ["报告生成", "长文本与格式稳定", "Qwen3 Max", "DeepSeek V3.2"],
    ["Embedding", "项目证据向量索引", "Qwen3 Embedding", "GLM Embedding" ]
  ];
  $("#routingGrid").innerHTML = routes.map((route) => `
    <div class="routing-item"><strong>${route[0]}</strong><span>${route[1]}</span>
      <label>主模型<select><option>${route[2]}</option><option>DeepSeek V3.2</option><option>GLM-4.6</option><option>Kimi K2</option><option>Qwen3 Max</option></select></label>
      <label>失败回退<select><option>${route[3]}</option><option>不自动回退</option><option>DeepSeek V3.2</option><option>GLM-4.6</option></select></label>
    </div>`).join("");
}

function renderExports() {
  $("#exportRows").innerHTML = state.exports.map((item) => `
    <tr><td><strong>${item.file}</strong></td><td>${item.template}</td><td>${item.snapshot}</td><td>${item.source}</td><td>${item.time}</td><td><button class="row-action download-export" type="button">打开</button></td></tr>`).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function bindRiskLinks() {
  $$(".risk-link").forEach((item) => {
    item.onclick = () => openRisk(item.dataset.risk);
    item.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openRisk(item.dataset.risk);
      }
    };
  });
}

function openRisk(id) {
  const risk = state.risks.find((item) => item.id === id) || state.risks[0];
  $("#drawerId").textContent = risk.id;
  $("#drawerTitle").textContent = risk.title;
  $("#drawerSummary").textContent = `${risk.summary}。系统已关联本地计算结果、支持证据与反证，当前结论仍需人工确认。`;
  $("#drawerLevel").textContent = `${risk.level}风险`;
  $("#drawerLevel").className = `badge ${badgeClass(risk.level)}`;
  $("#drawerStatusBadge").textContent = risk.status;
  $("#drawerStatusBadge").className = `badge ${badgeClass(risk.status)}`;
  $("#drawerStatus").value = risk.status;
  $("#drawerNote").value = "";
  $("#riskDrawer").dataset.risk = risk.id;
  $("#drawerBackdrop").hidden = false;
  $("#riskDrawer").classList.add("is-open");
  $("#riskDrawer").setAttribute("aria-hidden", "false");
  setTimeout(() => $("#closeDrawer").focus(), 30);
}

function closeRisk() {
  $("#riskDrawer").classList.remove("is-open");
  $("#riskDrawer").setAttribute("aria-hidden", "true");
  setTimeout(() => { $("#drawerBackdrop").hidden = true; }, 190);
}

function setOffline(offline) {
  state.offline = offline;
  $("#offlineSwitch").checked = offline;
  $("#offlineSwitch").closest(".switch").querySelector("em").textContent = offline ? "已开启" : "未开启";
  $("#offlineBanner").hidden = !offline;
  $("#apiStatus span:last-child").textContent = offline ? "严格离线" : "外部 API 已允许";
  $("#apiStatus .status-dot").className = `status-dot ${offline ? "status-dot-off" : "status-dot-ok"}`;
  $$(".api-dependent").forEach((button) => { button.disabled = offline; });
  showToast(offline ? "已开启严格离线模式" : "已允许外部 API", offline ? "外部模型与 OCR 请求已统一拦截。" : "任务将继续遵守最小证据外发策略。");
}

function handleFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  files.forEach((file) => {
    state.documents.unshift({
      name: file.name,
      hash: `待计算...${Math.random().toString(16).slice(2, 6)}`,
      year: new Date().getFullYear().toString(),
      type: file.name.toLowerCase().endsWith(".pdf") ? "待识别" : "表格资料",
      pages: 0,
      method: "待判定",
      status: "待处理"
    });
  });
  renderDocuments();
  setPage("documents");
  showToast(`已加入 ${files.length} 个文件`, "正在计算哈希并检查重复文件，不会立即调用外部 API。");
}

function getThemeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawChart() {
  const canvas = $("#trendChart");
  if (!canvas || state.currentPage !== "analysis") return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = rect.width;
  const height = rect.height;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const metric = $("#metricSelect").value;
  const sets = {
    receivable: { title: "应收账款周转天数", summary: "2025 年为 96.4 天，较历史中位数高 38.7 天", values: [48.7, 51.2, 54.1, 57.7, 63.5, 71.8, 96.4], median: 57.7, max: 110 },
    inventory: { title: "存货周转天数", summary: "2025 年为 128.6 天，连续三年上升", values: [76.2, 78.1, 81.4, 83.9, 91.7, 108.3, 128.6], median: 83.9, max: 145 },
    margin: { title: "销售毛利率", summary: "2025 年为 18.7%，较历史中位数下降 5.8 个百分点", values: [25.1, 24.8, 24.5, 25.7, 23.4, 21.6, 18.7], median: 24.5, max: 32 }
  };
  const data = sets[metric];
  $("#chartTitle").textContent = data.title;
  $("#chartSummary").textContent = data.summary;
  const labels = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"];
  const pad = { left: 52, right: 28, top: 20, bottom: 42 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const border = getThemeColor("--border");
  const text = getThemeColor("--text-muted");
  const accent = getThemeColor("--accent");

  ctx.clearRect(0, 0, width, height);
  ctx.font = '11px "Microsoft YaHei UI", sans-serif';
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.strokeStyle = border;
  ctx.fillStyle = text;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + chartH * (i / 4);
    const value = data.max - data.max * (i / 4);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(metric === "margin" ? `${value.toFixed(0)}%` : value.toFixed(0), pad.left - 10, y);
  }

  ctx.setLineDash([5, 5]);
  ctx.strokeStyle = text;
  const medianY = pad.top + chartH - (data.median / data.max) * chartH;
  ctx.beginPath(); ctx.moveTo(pad.left, medianY); ctx.lineTo(width - pad.right, medianY); ctx.stroke();
  ctx.setLineDash([]);

  const points = data.values.map((value, index) => ({
    x: pad.left + chartW * (index / (data.values.length - 1)),
    y: pad.top + chartH - (value / data.max) * chartH,
    value
  }));
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
  ctx.stroke();
  points.forEach((point, index) => {
    ctx.fillStyle = getThemeColor("--surface-raised");
    ctx.beginPath(); ctx.arc(point.x, point.y, 5, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = text; ctx.textAlign = "center"; ctx.fillText(labels[index], point.x, height - 17);
  });
}

function runAnalysis() {
  if (state.offline) return;
  const button = $("#runAnalysis");
  button.disabled = true;
  button.textContent = "正在分析";
  $("#findingList").hidden = true;
  $("#analysisSkeleton").hidden = false;
  $("#taskCount").textContent = "2";
  setTimeout(() => {
    button.disabled = false;
    button.textContent = "运行增量分析";
    $("#findingList").hidden = false;
    $("#analysisSkeleton").hidden = true;
    $("#taskCount").textContent = "1";
    showToast("增量分析已完成", "2 项风险已更新，1 项新异常等待复核。");
  }, 1800);
}

function generateOutput() {
  if (state.offline) return;
  const format = $("#outputFormat").value.match(/\(([^)]+)\)/)?.[1]?.replace(".", "") || "docx";
  const timestamp = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  state.exports.unshift({
    file: `华东制造_${state.selectedTemplate}_草稿.${format}`,
    template: state.selectedTemplate,
    snapshot: "16 项已核实风险",
    source: $("#quickModel").value,
    time: `今天 ${timestamp}`
  });
  renderExports();
  showToast(`${state.selectedTemplate}已生成`, "原型仅模拟生成流程，未创建真实文件。");
}

function initEvents() {
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setPage(item.dataset.page)));
  $$('[data-go]').forEach((item) => item.addEventListener("click", () => setPage(item.dataset.go)));
  $("#mobileMenu").addEventListener("click", () => $("#sidebar").classList.toggle("is-open"));
  $("#projectSelect").addEventListener("change", (event) => {
    $("#topProjectName").textContent = event.target.value;
    showToast("项目已切换", `当前项目：${event.target.value}`);
  });
  $("#quickModel").addEventListener("change", (event) => showToast("主模型已切换", `后续任务将优先使用 ${event.target.value}。`));
  $("#apiStatus").addEventListener("click", () => setOffline(!state.offline));
  $("#offlineSwitch").addEventListener("change", (event) => setOffline(event.target.checked));

  $("#themeToggle").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    localStorage.setItem("hengjian-theme", next);
    $("#themeToggle").textContent = next === "dark" ? "切换浅色主题" : "切换深色主题";
    requestAnimationFrame(drawChart);
  });

  $("#chooseFiles").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", (event) => handleFiles(event.target.files));
  $("#uploadZone").addEventListener("click", () => $("#fileInput").click());
  $("#uploadZone").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") $("#fileInput").click();
  });
  ["dragenter", "dragover"].forEach((name) => $("#uploadZone").addEventListener(name, (event) => {
    event.preventDefault(); $("#uploadZone").classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((name) => $("#uploadZone").addEventListener(name, (event) => {
    event.preventDefault(); $("#uploadZone").classList.remove("is-dragging");
  }));
  $("#uploadZone").addEventListener("drop", (event) => handleFiles(event.dataTransfer.files));
  $("#documentSearch").addEventListener("input", renderDocuments);
  $("#documentFilter").addEventListener("change", renderDocuments);
  $("#documentRows").addEventListener("click", (event) => {
    const row = event.target.closest("tr");
    if (!row) return;
    const doc = state.documents[Number(row.dataset.docIndex)];
    showToast(doc.status === "失败" ? "任务已重新加入队列" : "已打开资料预览", `${doc.name}，${doc.pages || "待识别"} 页。`);
    if (doc.status === "失败") { doc.status = "待处理"; renderDocuments(); }
  });
  $("#pauseQueue").addEventListener("click", (event) => {
    state.queuePaused = !state.queuePaused;
    event.target.textContent = state.queuePaused ? "继续队列" : "暂停队列";
    showToast(state.queuePaused ? "处理队列已暂停" : "处理队列已继续", state.queuePaused ? "已完成步骤不会重复执行或重复计费。" : "任务将按单工作器顺序运行。");
  });

  $("#metricSelect").addEventListener("change", drawChart);
  $("#runAnalysis").addEventListener("click", runAnalysis);
  $("#analysisScope").addEventListener("click", () => showToast("当前分析范围", "2019-2025 年，全部主体，新增及受影响资料。"));
  $("#viewRunLog").addEventListener("click", () => showToast("运行记录", "24 条规则执行成功，3 项调用模型解释，缓存命中 1 项。"));

  $("#riskSearch").addEventListener("input", renderRisks);
  $("#riskLevelFilter").addEventListener("change", renderRisks);
  $$(".risk-stat").forEach((item) => item.addEventListener("click", () => {
    state.selectedRiskFilter = item.dataset.riskFilter;
    $$(".risk-stat").forEach((button) => button.classList.toggle("is-selected", button === item));
    renderRisks();
  }));
  $("#closeDrawer").addEventListener("click", closeRisk);
  $("#drawerBackdrop").addEventListener("click", closeRisk);
  $("#saveRisk").addEventListener("click", () => {
    const risk = state.risks.find((item) => item.id === $("#riskDrawer").dataset.risk);
    const newStatus = $("#drawerStatus").value;
    const note = $("#drawerNote").value.trim();
    if (newStatus !== risk.status && !note) {
      showToast("请填写人工意见", "状态变更必须记录判断依据，历史状态不会被覆盖。");
      $("#drawerNote").focus();
      return;
    }
    risk.status = newStatus;
    risk.updated = "刚刚";
    renderRisks();
    closeRisk();
    showToast("风险处理结果已保存", `${risk.id} 已更新为“${newStatus}”，并生成新的历史记录。`);
  });
  $("#viewEvidence").addEventListener("click", () => {
    closeRisk(); setPage("documents"); showToast("已定位到证据资料", "原型展示资料列表，正式版将在 PDF 阅读器中打开准确页码。" );
  });
  $("#exportRisks").addEventListener("click", () => { setPage("outputs"); showToast("已带入风险清单模板", "当前筛选条件将作为输出范围。" ); });
  $("#newRisk").addEventListener("click", () => showToast("已创建空白风险事项", "正式版将打开风险编辑表单并要求关联证据。"));

  $$(".template-item").forEach((item) => item.addEventListener("click", () => {
    state.selectedTemplate = item.dataset.template;
    $$(".template-item").forEach((button) => button.classList.toggle("is-selected", button === item));
    $("#selectedTemplate").textContent = state.selectedTemplate;
    $("#generateFromPanel").textContent = `生成${state.selectedTemplate}`;
  }));
  $("#generateOutput").addEventListener("click", generateOutput);
  $("#generateFromPanel").addEventListener("click", generateOutput);
  $("#exportRows").addEventListener("click", (event) => {
    if (event.target.closest(".download-export")) showToast("已打开导出记录", "原型未创建真实文件，正式版将从项目本地目录打开。" );
  });

  $$("[data-settings-tab]").forEach((item) => item.addEventListener("click", () => {
    $$("[data-settings-tab]").forEach((button) => button.classList.toggle("is-active", button === item));
    $$(".settings-pane").forEach((pane) => pane.classList.toggle("is-active", pane.id === `settings-${item.dataset.settingsTab}`));
  }));
  $("#addProvider").addEventListener("click", () => $("#providerDialog").showModal());
  $("#providerList").addEventListener("click", (event) => {
    const test = event.target.closest("[data-provider-test]");
    const edit = event.target.closest("[data-provider-edit]");
    if (test) {
      const provider = state.providers[Number(test.dataset.providerTest)];
      test.textContent = "测试中"; test.disabled = true;
      setTimeout(() => { provider.status = "已连接"; renderProviders(); showToast("连接测试成功", `${provider.name} 返回正常，耗时 684 毫秒。`); }, 700);
    }
    if (edit) $("#providerDialog").showModal();
  });
  $("#testConnection").addEventListener("click", () => {
    const result = $("#connectionResult");
    result.hidden = false; result.textContent = "正在测试接口与模型能力...";
    setTimeout(() => { result.textContent = "连接成功，文本与 JSON Schema 能力验证通过。"; }, 800);
  });
  $("#providerForm").addEventListener("submit", (event) => {
    const form = new FormData(event.currentTarget);
    if (event.submitter?.value === "save") {
      state.providers.push({ name: form.get("name"), model: form.get("model"), capabilities: "文本、JSON Schema", status: "未测试", enabled: true });
      renderProviders();
      showToast("服务商配置已保存", "API Key 已模拟写入本机系统凭据。" );
    }
  });
  $("#saveRouting").addEventListener("click", () => showToast("任务路由已保存", "新任务将使用更新后的主模型与失败回退策略。"));
  $("#openLocation").addEventListener("click", () => showToast("本地目录", "浏览器原型无法打开系统目录，桌面版将调用 Windows 文件资源管理器。"));

  [["cpuLimit", "cpuLimitValue", (v) => `${v}%`], ["memoryLimit", "memoryLimitValue", (v) => `${Number(v).toFixed(1)} GB`], ["apiConcurrency", "apiConcurrencyValue", (v) => v]].forEach(([inputId, outputId, format]) => {
    $(`#${inputId}`).addEventListener("input", (event) => { $(`#${outputId}`).textContent = format(event.target.value); });
  });
  $$(".switch input").forEach((input) => input.addEventListener("change", () => {
    const label = input.closest(".switch")?.querySelector("em");
    if (label && input.id !== "offlineSwitch") label.textContent = input.checked ? "已开启" : "未开启";
  }));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("#riskDrawer").classList.contains("is-open")) closeRisk();
  });
}

function init() {
  const requestedTheme = new URLSearchParams(location.search).get("theme");
  const storedTheme = localStorage.getItem("hengjian-theme");
  const preferredTheme = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  const initialTheme = [requestedTheme, storedTheme, preferredTheme].find((value) => ["light", "dark"].includes(value)) || "light";
  document.documentElement.dataset.theme = initialTheme;
  $("#themeToggle").textContent = initialTheme === "dark" ? "切换浅色主题" : "切换深色主题";
  renderDocuments();
  renderRisks();
  renderFindings();
  renderProviders();
  renderRouting();
  renderExports();
  bindRiskLinks();
  initEvents();
  if ("ResizeObserver" in window) new ResizeObserver(() => drawChart()).observe($("#trendChart"));
  const initialPage = location.hash.replace("#", "");
  if (["overview", "documents", "analysis", "risks", "outputs", "settings"].includes(initialPage)) setPage(initialPage);
}

init();
