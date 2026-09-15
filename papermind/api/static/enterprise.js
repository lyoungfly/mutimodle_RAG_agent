const workspaceMode = new URLSearchParams(location.search).get('workspace') === 'enterprise' ? 'enterprise' : 'research';
const enterpriseMode = workspaceMode === 'enterprise';
const workspaceNames = {research: enterpriseMode ? '企业工作台' : '研究工作台', library: enterpriseMode ? '企业资料库' : '文献库'};
const workspaceBrand = enterpriseMode ? 'IndustrialInsight' : 'PaperMind';
const workspaceSelector = document.getElementById('workspace-mode');
workspaceSelector.value = workspaceMode;
workspaceSelector.onchange = () => {
  const destination = workspaceSelector.value === 'enterprise' ? '/?workspace=enterprise' : '/';
  if (window.enterpriseMotion) window.enterpriseMotion.navigate(destination);
  else location.href = destination;
};

if (enterpriseMode) {
  document.querySelectorAll('a[href="/settings"]').forEach(link => {link.href = '/settings?workspace=enterprise';});
  document.body.classList.add('enterprise');
  document.querySelector('meta[name="theme-color"]').content = '#14243d';
  document.querySelector('meta[name="description"]').content = 'IndustrialInsight 企业知识工作台：汇集业务资料，检索原始证据，完成智能分析与报告。';
  document.title = 'IndustrialInsight · 企业知识工作台';
  const set = (selector, text) => {document.querySelector(selector).textContent = text;};
  set('.brand strong', 'IndustrialInsight');
  document.querySelector('.brand strong').append(Object.assign(document.createElement('small'), {textContent:'ENTERPRISE WORKSPACE'}));
  document.querySelector('.brand').href = '/?workspace=enterprise';
  document.querySelector('.brand').setAttribute('aria-label','IndustrialInsight 首页');
  set('.brand-mark', 'I');
  document.querySelector('#nav-research').lastChild.textContent = '企业工作台';
  const libraryNav = document.querySelector('#nav-library');
  libraryNav.firstChild.textContent = '▤';
  libraryNav.childNodes[1].textContent = '企业资料库 ';
  set('#view-title', workspaceNames.research);
  set('.hero-copy .eyebrow', 'INDUSTRIAL INSIGHT / 企业知识中枢');
  document.querySelector('.hero h1').replaceChildren(
    document.createTextNode('连接企业知识，'), document.createElement('br'),
    Object.assign(document.createElement('span'), {className:'accent',textContent:'让决策有据可循。'}));
  set('.hero-copy > p', '把技术手册、维护规范与业务记录放在一起。检索跨文档证据，定位到段落和单元格，核验每一项结论。');
  const art = document.querySelector('.research-art');
  art.className = 'enterprise-hero-visual';
  // 静态流程图只呈现产品能力，不模拟实时业务数据。
  art.innerHTML = `<div class="enterprise-orbit">
    <div class="enterprise-orbit-ring"></div><div class="enterprise-orbit-ring inner"></div>
    <svg class="enterprise-connectors" viewBox="0 0 440 320" fill="none" aria-hidden="true">
      <path d="M108 73C185 73 150 155 219 155M219 155C300 155 269 64 349 64M219 155C291 155 250 253 344 253" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 5"/>
      <circle cx="108" cy="73" r="4" fill="currentColor"/><circle cx="349" cy="64" r="4" fill="currentColor"/><circle cx="344" cy="253" r="4" fill="currentColor"/>
    </svg>
    <div class="enterprise-core"><span class="enterprise-core-symbol">✦</span><strong>Insight</strong><small>连接知识与决策</small></div>
    <div class="enterprise-satellite source"><span class="enterprise-node-icon">▤</span><div><strong>多源资料</strong><small>PDF · Word · Excel</small></div></div>
    <div class="enterprise-satellite search"><span class="enterprise-node-icon">⌕</span><div><strong>证据检索</strong><small>定位段落与单元格</small></div></div>
    <div class="enterprise-satellite insight"><span class="enterprise-node-icon">↗</span><div><strong>分析与报告</strong><small>让结论保留出处</small></div></div>
    <span class="enterprise-flow-label">KNOWLEDGE → EVIDENCE → INSIGHT</span>
  </div><div class="enterprise-hero-caption"><span></span>从业务资料，到有依据的下一步</div>`;
  const shortcuts = document.createElement('div'); shortcuts.className = 'enterprise-hero-actions';
  for (const [action,label] of [['library','管理企业资料 ↗'],['agent','开始智能分析 →']]) {
    const button = document.createElement('button'); button.type = 'button';
    button.dataset.enterpriseAction = action; button.textContent = label;
    button.className = action === 'library' ? 'secondary' : 'text-button';
    button.onclick = () => {
      showView(action === 'library' ? 'library' : 'research');
      if (action === 'agent') window.enterpriseTools?.selectPanel('agent');
      const target = document.getElementById(action === 'library' ? 'file' : 'ent-question');
      if (target) {
        target.focus({preventScroll:true});
        if (window.enterpriseMotion) window.enterpriseMotion.scrollTo(target);
        else target.scrollIntoView({block:'center'});
      }
    };
    shortcuts.append(button);
  }
  document.querySelector('.hero-copy').append(shortcuts);
  const placeholder = document.createElement('div');
  placeholder.id = 'enterprise-query-loading'; placeholder.className = 'enterprise-query-placeholder';
  placeholder.hidden = true; placeholder.setAttribute('aria-hidden','true');
  placeholder.innerHTML = '<div class="enterprise-placeholder-heading"><span>✦</span>正在从企业资料中寻找依据</div><div class="enterprise-skeleton-line"></div><div class="enterprise-skeleton-line"></div><div class="enterprise-skeleton-line short"></div>';
  document.getElementById('query-status').after(placeholder);
  set('.side-note strong', '把业务经验留在知识库');
  set('.side-note p', '规范、手册与记录，共同支撑每次分析。');
  set('#ask-heading', '今天需要查证什么？');
  set('.composer-panel .eyebrow', 'SEARCH YOUR KNOWLEDGE');
  document.querySelector('#question').placeholder = '例如：这两份维护规范对冷却系统的检查要求有哪些不同？请分别列出依据。';
  set('#ask-button', '检索并分析 ↗');
  set('#result-panel h2', '分析结果');
  set('#result-panel .eyebrow', 'BUSINESS INSIGHTS');
  set('.library-heading .eyebrow', 'YOUR ENTERPRISE KNOWLEDGE');
  set('.library-heading h1', '企业资料库。');
  set('#upload-form h2', '让团队资料成为可检索的知识');
  set('.library-tools h2', '全部资料');
  document.getElementById('document-search').placeholder = '搜索资料名称…';
  document.querySelector('label[for="document-search"]').textContent = '搜索资料名称';
  document.querySelector('.library-tools h2').append(Object.assign(document.createElement('span'), {id:'document-count',className:'pill',textContent:'0'}));
  set('.metrics > div:nth-child(1) small', '已上传资料');
  set('.metrics > div:nth-child(2) small', '已就绪资料');
  set('#start-panel h2', '从一份资料，到可核验的业务结论。');
  set('#open-library', '管理企业资料 ↗');
  const onboarding = document.querySelectorAll('.onboarding > div');
  const steps = [
    ['汇集业务资料','上传 PDF、Word、Excel 或图片，按业务主题建立知识库。'],
    ['提出具体问题','查询规范、比较技术要求，或提交表格统计与 Agent 分析任务。'],
    ['核验来源','查看正文段落、单元格和计算记录，导出带来源的分析报告。']
  ];
  onboarding.forEach((node,i) => {node.querySelector('h3').textContent = steps[i][0]; node.querySelector('p').textContent = steps[i][1];});
  const suggestions = [
    ['比较维护规范 ↗','不同文档对设备维护有哪些要求？请逐项引用来源。',''],
    ['定位业务记录 ↗','表格中记录了哪些设备故障及处理措施？请列出原始记录。','table'],
    ['查找操作依据 ↗','资料中有哪些开机前检查要求？请给出对应依据。','text']
  ];
  document.querySelectorAll('[data-question]').forEach((node,i) => {
    node.textContent = suggestions[i][0]; node.dataset.question = suggestions[i][1]; node.dataset.type = suggestions[i][2];
  });
  set('.workspace-footer span', 'IndustrialInsight · 企业知识工作台');
  document.getElementById('enterprise-note').hidden = false;
  document.getElementById('access-link').href = '/access?workspace=enterprise';
}
