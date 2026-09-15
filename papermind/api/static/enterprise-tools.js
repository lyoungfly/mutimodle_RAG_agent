(() => {
  if (typeof enterpriseMode === 'undefined' || !enterpriseMode) return;
  const el = (tag, text = '', className = '') => {
    const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
  };
  const root = el('section', '', 'enterprise-tools'); root.id = 'enterprise-tools';
  root.setAttribute('aria-labelledby', 'enterprise-tools-heading');
  // 模板仅含固定界面文本；业务数据一律通过 textContent 渲染。
  root.innerHTML = `<div class="section-heading"><div><span class="eyebrow">FROM KNOWLEDGE TO ACTION</span><h2 id="enterprise-tools-heading">企业分析与报告</h2></div><a href="/access?workspace=enterprise">成员与权限 ↗</a></div>
  <div class="enterprise-tool-tabs" role="tablist" aria-label="企业工具"><span class="enterprise-tab-indicator" aria-hidden="true"></span><button type="button" role="tab" id="ent-tab-table" aria-controls="ent-panel-table" aria-selected="true" data-panel="table">表格统计</button><button type="button" role="tab" id="ent-tab-agent" aria-controls="ent-panel-agent" aria-selected="false" tabindex="-1" data-panel="agent">智能分析</button><button type="button" role="tab" id="ent-tab-jobs" aria-controls="ent-panel-jobs" aria-selected="false" tabindex="-1" data-panel="jobs">任务与报告</button></div>
  <div class="enterprise-tool-panels">
  <div id="ent-panel-table" role="tabpanel" aria-labelledby="ent-tab-table"><p>选择已索引的表格，按列筛选并执行统计。计算由程序完成，结果保留资料来源。</p><form id="ent-table-form"><div class="enterprise-tool-grid"><label class="enterprise-tool-wide">资料与表格<select id="ent-table" required><option value="">正在读取表格目录…</option></select></label><label>统计方式<select id="ent-operation"><option value="count">记录条数</option><option value="sum">求和</option><option value="mean">平均值</option><option value="min">最小值</option><option value="max">最大值</option><option value="group_count">分组计数</option><option value="group_sum">分组求和</option></select></label><label id="ent-column-label" hidden>数值列<select id="ent-column"></select></label><label id="ent-group-label" hidden>分组列<select id="ent-group"></select></label></div><p id="ent-table-hint" class="enterprise-table-hint">先在企业资料库上传并索引 Word、Excel、CSV 或包含表格的 PDF。</p><details class="enterprise-filter"><summary>添加筛选条件（可选）</summary><div class="enterprise-tool-grid"><label>筛选列<select id="ent-filter-column"><option value="">不筛选</option></select></label><label>比较方式<select id="ent-filter-operator"><option value="eq">等于</option><option value="ne">不等于</option><option value="contains">包含</option><option value="gt">大于</option><option value="gte">大于等于</option><option value="lt">小于</option><option value="lte">小于等于</option></select></label><label>比较值<input id="ent-filter-value" maxlength="500" placeholder="例如：冷却系统 或 10"></label></div></details><div class="enterprise-tool-actions"><button type="submit">提交统计任务 →</button><button type="button" id="ent-refresh-tables" class="secondary">刷新表格</button></div></form></div>
  <div id="ent-panel-agent" role="tabpanel" aria-labelledby="ent-tab-agent" hidden><form id="ent-agent-form"><label for="ent-question">描述分析目标、涉及的资料和希望获得的结果</label><textarea id="ent-question" rows="4" maxlength="8000" required placeholder="例如：对比两份设备维护规范，结合故障记录统计故障类型，整理维护建议并列出每项结论的依据。"></textarea><p class="enterprise-agent-note">智能体将按需检索知识、读取原文和调用统计工具。运行步骤与资料来源保留在任务详情中；完成后可下载报告。</p><div class="enterprise-tool-actions"><button type="submit">开始智能分析 →</button><p>范围：<strong id="ent-agent-collection"></strong></p></div></form></div>
  <div id="ent-panel-jobs" role="tabpanel" aria-labelledby="ent-tab-jobs" hidden><div class="section-heading"><p>后台任务在关闭页面后仍可继续。重新打开这里查看结果。</p><button type="button" id="ent-refresh-jobs" class="secondary">刷新任务</button></div><ul id="ent-jobs" class="enterprise-job-list"></ul></div>
  </div><p id="ent-status" role="status" class="enterprise-tool-status"></p><section id="ent-detail" class="enterprise-job-detail" hidden aria-label="任务详情"><div class="section-heading"><h3 id="ent-detail-title">任务详情</h3><span id="ent-detail-state" class="enterprise-state"></span></div><div id="ent-progress" class="enterprise-job-progress"><div class="enterprise-progress-track" aria-hidden="true"><span></span></div><p id="ent-progress-label" role="status"></p></div><ol id="ent-events" class="enterprise-job-events"></ol><div id="ent-result" class="enterprise-job-result"></div><div class="enterprise-tool-actions"><button type="button" id="ent-cancel" class="secondary" hidden>取消任务</button><div id="ent-downloads" class="enterprise-downloads" hidden><button type="button" class="secondary" data-format="docx">下载 Word</button><button type="button" class="secondary" data-format="pdf">下载 PDF</button><button type="button" class="secondary" data-format="json">下载分析数据</button></div></div></section>`;
  document.getElementById('result-panel').after(root);
  const get = id => root.querySelector(`#ent-${id}`);
  const statusNames = {queued:'排队中',running:'进行中',succeeded:'已完成',failed:'失败',cancelled:'已取消'};
  const kindNames = {index:'资料索引',analysis:'表格统计',analyze:'表格统计',table:'表格统计',agent:'智能分析'};
  let collection = activeCollection, tables = [], jobs = [], selectedJob = null, timer = null;
  let fetching = false, disposed = false, submitting = false, activePanel = 'table', selectedPending = false;
  let tableFetch = null, cycleFetch = null, refreshRequested = false, resultKey = '', detailJob = null, detailVersion = '', failureCount = 0;
  const jobRows = new Map(), eventRows = new Map(), workingCounts = new WeakMap();
  const tablist = root.querySelector('.enterprise-tool-tabs'), panelHost = root.querySelector('.enterprise-tool-panels');
  const emptyJobs = el('li','还没有任务。提交一次表格统计或智能分析后，可在这里查看进度与报告。','enterprise-empty');
  const pending = job => ['queued','running'].includes(job?.status);
  const query = () => `collection_id=${encodeURIComponent(collection)}`;
  const setStatus = (text, error = false) => {get('status').textContent = text; get('status').classList.toggle('error',error);};
  function setWorking(node, value) {
    const count = Math.max(0,(workingCounts.get(node) || 0) + (value ? 1 : -1));
    workingCounts.set(node,count); node.setAttribute('aria-busy',String(count > 0));
    if ('disabled' in node) node.disabled = count > 0;
  }
  function reconcile(parent, nodes) {
    let cursor = parent.firstChild;
    for (const node of nodes) {
      if (node !== cursor) parent.insertBefore(node,cursor); else cursor = cursor.nextSibling;
    }
    while (cursor) {const next = cursor.nextSibling; cursor.remove(); cursor = next;}
  }
  function resetDetail() {
    resultKey = ''; detailJob = null; detailVersion = ''; eventRows.clear();
    get('events').replaceChildren(); get('result').replaceChildren();
  }
  const locationLabel = source => {
    if (!source || typeof source !== 'object') return '';
    return [source.sheet || source.sheet_name,source.cell_range,source.heading_path,
      source.paragraph ? `正文第 ${source.paragraph} 段` : source.paragraph_start ? `段落 ${source.paragraph_start}${source.paragraph_end ? '–'+source.paragraph_end : ''}` : '',
      source.table_number ? `表格 ${source.table_number}${source.row ? ' · 第 '+source.row+' 行' : ''}` : '',
      source.page ? `第 ${source.page} 页` : ''].filter(Boolean).join(' · ');
  };
  function sourceLink(container,url,label) {
    if (!url) return;
    try {
      const target = new URL(url,location.origin);
      if (target.origin !== location.origin || !target.pathname.startsWith('/documents/')) return;
      const link = el('a',label); link.href = target.href; link.target = '_blank'; link.rel = 'noopener'; container.append(link);
    } catch {}
  }
  function columns(select, includeEmpty = false) {
    select.replaceChildren();
    if (includeEmpty) {const option = el('option','不筛选'); option.value = ''; select.append(option);}
    const table = tables[Number(get('table').value)];
    for (const [i,header] of (table?.headers || []).entries()) {
      const option = el('option',`${i+1}. ${header || '未命名列'}`); option.value = i; select.append(option);
    }
  }
  function selectTable() {
    for (const id of ['column','group','filter-column']) columns(get(id),id === 'filter-column');
    const table = get('table').value === '' ? null : tables[Number(get('table').value)];
    get('table-hint').textContent = table ? `${table.row_count ?? '—'} 条记录 · ${locationLabel(table.source) || '来源位置见统计结果'}` : '当前知识库没有已索引表格。请先上传并建立索引，再刷新表格。';
  }
  function operationChanged() {
    const op = get('operation').value;
    get('column-label').hidden = ['count','group_count'].includes(op);
    get('group-label').hidden = !op.startsWith('group_');
  }
  async function readTables() {
    const scope = collection;
    const data = await request(`/api/enterprise/tables?${query()}`);
    if (scope !== collection || disposed) return;
    const selected = tables[Number(get('table').value)];
    const previous = selected ? `${selected.document_id}:${selected.table_id}` : '';
    const selectedColumns = ['column','group','filter-column'].map(id => [id,get(id).value]);
    tables = Array.isArray(data.tables) ? data.tables : [];
    get('table').replaceChildren();
    if (!tables.length) {const option = el('option','没有可用表格'); option.value = ''; get('table').append(option);}
    tables.forEach((table,i) => {const option = el('option',`${table.filename} · ${locationLabel(table.source) || table.table_id}`); option.value = i; if (`${table.document_id}:${table.table_id}` === previous) option.selected = true; get('table').append(option);});
    selectTable();
    const current = tables[Number(get('table').value)];
    if (current && `${current.document_id}:${current.table_id}` === previous) {
      for (const [id,value] of selectedColumns) if (Array.from(get(id).options).some(option => option.value === value)) get(id).value = value;
    }
  }
  async function loadTables() {
    setWorking(get('refresh-tables'),true);
    try {
      if (tableFetch) await tableFetch.catch(() => {});
      if (disposed) return;
      const current = readTables(); tableFetch = current;
      try {await current;} finally {if (tableFetch === current) tableFetch = null;}
    } finally {setWorking(get('refresh-tables'),false);}
  }
  function renderJobs() {
    const nodes = [], identities = new Set();
    for (const job of jobs) {
      if (identities.has(job.id)) continue; identities.add(job.id);
      let entry = jobRows.get(job.id);
      if (!entry) {
        const row = el('li','','enterprise-job-row'), info = el('div');
        const title = el('strong'), meta = el('small'), state = el('span','','enterprise-state');
        const button = el('button','查看','secondary'); button.type = 'button';
        button.onclick = async () => {
          if (selectedJob !== job.id) {selectedJob = job.id; resetDetail(); renderJob(jobs.find(item => item.id === job.id) || job);}
          renderJobs(); setWorking(button,true); setWorking(get('detail'),true);
          try {await cycle(true);} finally {setWorking(button,false); setWorking(get('detail'),false);}
        };
        info.append(title,meta); row.append(info,state,button);
        entry = {row,title,meta,state,button}; jobRows.set(job.id,entry);
      }
      const date = new Date(typeof job.created_at === 'number' ? job.created_at * 1000 : job.created_at);
      const title = kindNames[job.kind] || '企业任务';
      const meta = `${Number.isNaN(date.getTime()) ? job.created_at || '' : date.toLocaleString()} · ${job.id}`;
      if (entry.title.textContent !== title) entry.title.textContent = title;
      if (entry.meta.textContent !== meta) entry.meta.textContent = meta;
      if (entry.row.dataset.status !== job.status) {
        entry.row.dataset.status = job.status; entry.state.textContent = statusNames[job.status] || job.status;
        entry.state.className = `enterprise-state${Object.hasOwn(statusNames,job.status) ? ' '+job.status : ''}`;
      }
      const selected = selectedJob === job.id;
      entry.row.classList.toggle('is-selected',selected); entry.button.setAttribute('aria-pressed',String(selected));
      const label = selected ? '当前任务' : '查看任务';
      if (entry.button.textContent !== label) entry.button.textContent = label;
      nodes.push(entry.row);
    }
    for (const id of jobRows.keys()) if (!identities.has(id)) jobRows.delete(id);
    reconcile(get('jobs'),nodes.length ? nodes : [emptyJobs]);
  }
  function renderValue(container,value) {
    if (value === null || value === undefined) return;
    if (typeof value !== 'object') {container.append(el('p',String(value))); return;}
    if (Array.isArray(value)) {
      const list = el('ul');
      for (const item of value.slice(0,150)) {
        const li = el('li');
        if (item && typeof item === 'object') {
          if (item.calculation_id && item.summary) {renderCalculation(li,item); list.append(li); continue;}
          if (item.evidence_id) {li.id = `ent-evidence-${item.evidence_id}`; li.append(el('strong',`[${item.evidence_id}] `));}
          const text = item.text || item.summary || item.message || item.content;
          if (text) li.append(el('p',String(text)));
          if (item.filename || item.document_id) li.append(el('p',`${item.filename || item.document_id} · ${locationLabel(item.source || item.metadata?.source)}`,'muted'));
          const ids = item.evidence_ids || item.citations;
          if (Array.isArray(ids)) li.append(el('p',`证据：${ids.join('、')}`,'muted'));
          sourceLink(li,item.url || item.source?.file_url,'查看原始资料 ↗');
          if (!text || Object.keys(item).some(key => ['value','result','rows'].includes(key))) li.append(el('pre',JSON.stringify(item,null,2)));
        } else li.textContent = String(item);
        list.append(li);
      }
      if (value.length > 150) list.append(el('li','仅展示前 150 项，完整结果请下载分析数据。'));
      container.append(list); return;
    }
    const headers = value.headers || value.columns, rows = value.rows;
    if (Array.isArray(headers) && Array.isArray(rows)) {
      const wrap = el('div','','table-scroll'), table = el('table'), head = el('thead'), tr = el('tr');
      headers.forEach(header => tr.append(el('th',String(header)))); head.append(tr); table.append(head);
      const body = el('tbody');
      rows.slice(0,100).forEach(row => {const line = el('tr'); headers.forEach((header,i) => line.append(el('td',String((Array.isArray(row) ? row[i] : row[header]) ?? '')))); body.append(line);});
      table.append(body); wrap.append(table); container.append(wrap);
      if (rows.length > 100) container.append(el('p','表格展示前 100 行，完整结果可下载。','muted'));
    } else container.append(el('pre',JSON.stringify(value,null,2)));
  }
  function renderCalculation(container,calculation) {
    const summary = calculation.summary || {};
    const names = {count:'记录条数',sum:'求和',mean:'平均值',min:'最小值',max:'最大值',group_count:'分组计数',group_sum:'分组求和'};
    const metrics = el('div','','enterprise-calculation-metrics');
    for (const [label,value] of [[names[summary.operation] || '统计值',summary.value ?? '无数据'],['参与统计',summary.selected_rows ?? '—'],['筛除记录',summary.excluded_rows ?? '—']]) {
      const metric = el('div'); metric.append(el('small',label),el('strong',String(value))); metrics.append(metric);
    }
    container.append(metrics,el('p',`${calculation.filename || ''} · ${locationLabel(calculation.source)}`,'muted'));
    sourceLink(container,calculation.source?.file_url,'打开计算来源 ↗');
    if (calculation.groups?.length) renderValue(container,{headers:['分组','记录数','统计值'],rows:calculation.groups.map(group => [group.label,group.count,group.value])});
    const detail = el('details'); detail.append(el('summary','计算参数与原始行预览'));
    detail.append(el('pre',JSON.stringify({calculation_id:calculation.calculation_id,parameters:calculation.parameters,selected_row_numbers:calculation.selected_row_numbers},null,2)));
    if (calculation.rows?.length) renderValue(detail,{headers:['原始行号',...(calculation.headers || [])],rows:calculation.rows.map(row => [row.row_number,...row.values])});
    container.append(detail);
  }
  function renderResult(result) {
    get('result').replaceChildren(); if (!result) return;
    if (result.calculation_id && result.summary) renderCalculation(get('result'),result);
    const labels = {summary:'分析摘要',answer:'分析结论',findings:'主要发现',recommendations:'建议',conflicts:'资料冲突',missing_information:'资料缺口',calculations:'计算记录',evidence:'引用证据',sources:'资料来源',warnings:'提示',table:'统计结果'};
    let shown = false;
    for (const [key,label] of Object.entries(labels)) if (result[key] && !(key === 'summary' && result.calculation_id) && (!Array.isArray(result[key]) || result[key].length)) {
      const section = el('section'); section.append(el('h4',label)); renderValue(section,result[key]); get('result').append(section); shown = true;
      if (key === 'summary' && result.summary_evidence_ids?.length) section.append(el('p',`依据：${result.summary_evidence_ids.join('、')}`,'muted'));
    }
    const detail = el('details'), raw = el('pre'); let expanded = false;
    const expand = () => {if (detail.open && !expanded) {expanded = true; raw.textContent = JSON.stringify(result,null,2);}};
    detail.append(el('summary','完整分析数据'),raw); detail.addEventListener('toggle',expand); detail.addEventListener('enterprise:expand',expand);
    detail.open = !shown && !result.calculation_id; get('result').append(detail); expand();
  }
  function renderJob(job) {
    const entering = get('detail').hidden;
    if (detailJob !== job.id) {resetDetail(); detailJob = job.id;}
    if (Object.hasOwn(job,'result')) detailVersion = `${job.id}:${job.status}:${job.updated_at}`;
    selectedPending = pending(job);
    get('detail').hidden = false;
    get('detail-title').textContent = `${kindNames[job.kind] || '任务'} · ${String(job.id).slice(0,12)}`;
    get('detail-state').textContent = statusNames[job.status] || job.status;
    get('detail-state').className = 'enterprise-state';
    if (Object.hasOwn(statusNames,job.status)) get('detail-state').classList.add(job.status);
    const eventNodes = [], eventKeys = new Set(), occurrences = new Map();
    for (const [index,event] of (job.events || []).entries()) {
      const base = `${event.at ?? index}:${event.stage || ''}:${event.tool || ''}`;
      const occurrence = occurrences.get(base) || 0; occurrences.set(base,occurrence+1);
      const key = `${base}:${occurrence}`, text = `${event.stage ? event.stage+' · ' : ''}${event.message || ''}`;
      let node = eventRows.get(key); if (!node) {node = el('li'); eventRows.set(key,node);}
      if (node.textContent !== text) node.textContent = text;
      node.classList.toggle('is-latest',index === job.events.length-1 && selectedPending);
      eventKeys.add(key); eventNodes.push(node);
    }
    for (const key of eventRows.keys()) if (!eventKeys.has(key)) eventRows.delete(key);
    reconcile(get('events'),eventNodes);
    // 结果在完成后固定，轮询只更新进度，保留阅读位置及已展开的来源。
    const nextResultKey = `${job.id}:${job.status}:${job.result ? job.result.completed_at || job.updated_at || 'complete' : 'empty'}:${job.error || ''}`;
    if (resultKey !== nextResultKey) {
      resultKey = nextResultKey; renderResult(job.result);
      if (job.error) get('result').prepend(el('p',String(job.error),'error'));
      if (job.result) window.enterpriseMotion?.enter(get('result'));
    }
    const progress = get('progress'); progress.classList.toggle('is-active',selectedPending);
    progress.dataset.status = job.status;
    const latest = (job.events || []).at(-1);
    const progressText = job.cancel_requested && selectedPending ? '正在等待当前操作结束，随后取消任务。' : job.status === 'queued' ? '任务已进入队列，等待处理。' : job.status === 'running' ? latest?.message || '正在分析资料，可继续浏览工作空间。' : job.status === 'succeeded' ? '任务已完成，可查看结论、依据与报告。' : job.status === 'cancelled' ? '任务已取消。' : job.status === 'failed' ? '任务未完成，请查看下方原因。' : '正在读取任务详情…';
    if (get('progress-label').textContent !== progressText) get('progress-label').textContent = progressText;
    get('cancel').hidden = !pending(job); get('downloads').hidden = job.status !== 'succeeded' || !job.result;
    get('cancel').textContent = job.cancel_requested ? '正在取消（当前操作结束后生效）' : '取消任务';
    for (const button of root.querySelectorAll('[data-format]')) button.hidden = job.kind === 'index' && button.dataset.format !== 'json';
    if (entering) window.enterpriseMotion?.enter(get('detail'));
  }
  async function cycle(force = false) {
    clearTimeout(timer);
    if (disposed || document.hidden || (!force && document.getElementById('research-view').hidden)) return;
    if (fetching) {refreshRequested ||= force; return cycleFetch;}
    fetching = true; setWorking(get('refresh-jobs'),true);
    cycleFetch = (async () => {
      do {
        refreshRequested = false; const scope = collection;
        try {
          const data = await request(`/api/enterprise/jobs?${query()}`);
          if (disposed) return;
          if (scope !== collection) {refreshRequested = true; continue;}
          const oldStatus = new Map(jobs.map(job => [job.id,job.status]));
          jobs = Array.isArray(data.jobs) ? data.jobs : []; renderJobs();
          if (jobs.some(job => job.kind === 'index' && job.status === 'succeeded' && ['queued','running'].includes(oldStatus.get(job.id)))) {
            await refresh(); await loadTables();
          }
          if (selectedJob && scope === collection) {
            const selected = selectedJob, summary = jobs.find(job => job.id === selected);
            if (!summary || detailVersion !== `${summary.id}:${summary.status}:${summary.updated_at}`) {
              const job = await request(`/api/enterprise/jobs/${encodeURIComponent(selected)}`);
              if (scope === collection && selected === selectedJob && !disposed) renderJob(job);
            }
          }
          failureCount = 0;
        } catch (error) {if (scope === collection && !disposed) {setStatus(error.message,true); failureCount++;}}
      } while (refreshRequested && !disposed && !document.hidden);
    })();
    try {await cycleFetch;}
    finally {
      fetching = false; cycleFetch = null; setWorking(get('refresh-jobs'),false);
      if (!disposed && !document.hidden && !document.getElementById('research-view').hidden && (selectedPending || jobs.some(pending))) {
        timer = setTimeout(() => cycle(),Math.min(30000,3000 * 2 ** Math.min(failureCount,4)));
      }
    }
  }
  function switchPanel(name) {
    if (!['table','agent','jobs'].includes(name)) return;
    const changed = name !== activePanel, previousHeight = changed ? panelHost.getBoundingClientRect().height : 0;
    activePanel = name;
    for (const button of root.querySelectorAll('[data-panel]')) {
      const active = button.dataset.panel === name; button.setAttribute('aria-selected',String(active)); button.tabIndex = active ? 0 : -1;
      get(`panel-${button.dataset.panel}`).hidden = !active;
    }
    window.enterpriseMotion?.tabs(tablist);
    if (changed) {
      window.enterpriseMotion?.enter(get(`panel-${name}`));
      window.enterpriseMotion?.resize(panelHost,previousHeight);
    }
    if (name === 'jobs') cycle(true);
  }
  function trackJob(job) {
    if (selectedJob !== job.id) resetDetail();
    selectedJob = job.id; jobs = [job,...jobs.filter(item => item.id !== job.id)]; renderJobs(); renderJob(job); switchPanel('jobs');
    setStatus('任务已提交，可在这里查看进度。');
  }
  async function submit(form,path,payload) {
    if (busy) {setStatus('正在处理当前工作空间请求，请稍后提交。'); return;}
    if (submitting) {setStatus('正在提交任务，请稍候。'); return;} submitting = true;
    const button = form.querySelector('[type="submit"]'); setWorking(button,true); setWorking(form,true); setStatus('正在提交任务…');
    const scope = collection;
    try {const job = await post(path,payload); if (scope === collection) trackJob(job);}
    catch (error) {setStatus(error.message,true);}
    finally {submitting = false; setWorking(button,false); setWorking(form,false);}
  }
  get('table-form').onsubmit = event => {
    event.preventDefault();
    if (get('table').value === '') {setStatus('请先选择一张已索引表格。',true); return;}
    const table = tables[Number(get('table').value)], operation = get('operation').value;
    if (!table) {setStatus('表格目录正在更新，请稍后重新选择。'); return;}
    const column = ['count','group_count'].includes(operation) ? null : Number(get('column').value);
    const groupBy = operation.startsWith('group_') ? Number(get('group').value) : null;
    const filters = get('filter-column').value === '' ? [] : [{column:Number(get('filter-column').value),operator:get('filter-operator').value,value:get('filter-value').value}];
    submit(event.currentTarget,'/api/enterprise/analyze',{collection_id:collection,document_id:table.document_id,table_id:table.table_id,operation,column,group_by:groupBy,filters});
  };
  get('agent-form').onsubmit = event => {event.preventDefault(); const question = get('question').value.trim(); if (question) submit(event.currentTarget,'/api/enterprise/agent',{collection_id:collection,question});};
  get('operation').onchange = operationChanged; get('table').onchange = selectTable;
  get('refresh-tables').onclick = async () => {try {await loadTables(); setStatus('表格目录已更新。');} catch (error) {setStatus(error.message,true);}};
  get('refresh-jobs').onclick = () => cycle(true);
  get('cancel').onclick = async () => {
    const id = selectedJob, scope = collection; if (!id) return; setWorking(get('cancel'),true);
    try {
      const job = await post(`/api/enterprise/jobs/${encodeURIComponent(id)}/cancel`,{});
      if (scope === collection && selectedJob === id && !disposed) {renderJob(job); setStatus('已请求取消任务。');}
      await cycle(true);
    } catch(error) {if (scope === collection) setStatus(error.message,true);} finally {setWorking(get('cancel'),false);}
  };
  for (const button of root.querySelectorAll('[data-panel]')) {
    button.onclick = () => switchPanel(button.dataset.panel);
    button.onkeydown = event => {
      const names = ['table','agent','jobs']; let index = names.indexOf(activePanel);
      if (event.key === 'ArrowRight') index = (index+1)%3; else if (event.key === 'ArrowLeft') index = (index+2)%3;
      else if (event.key === 'Home') index = 0; else if (event.key === 'End') index = 2; else return;
      event.preventDefault(); switchPanel(names[index]); get(`tab-${names[index]}`).focus();
    };
  }
  for (const button of root.querySelectorAll('[data-format]')) button.onclick = async () => {
    const id = selectedJob; if (!id) return; setWorking(button,true);
    try {
      const response = await fetch(`/api/enterprise/jobs/${encodeURIComponent(id)}/report?format=${encodeURIComponent(button.dataset.format)}`,{credentials:'same-origin'});
      if (!response.ok) {const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : '报告下载失败，请稍后重试。');}
      const url = URL.createObjectURL(await response.blob()), link = el('a'); link.href = url; link.download = `IndustrialInsight-${id}.${button.dataset.format}`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
      setStatus('报告已准备下载。');
    } catch (error) {setStatus(error.message,true);} finally {setWorking(button,false);}
  };
  async function refreshTools() {
    if (disposed) return;
    if (!workspaceSession || (workspaceSession.enabled && !workspaceSession.authenticated)) {
      setStatus('请先登录并加载授权的知识库。'); return;
    }
    if (collection !== activeCollection) {
      collection = activeCollection; tables = []; jobs = []; selectedJob = null; selectedPending = false; failureCount = 0;
      resetDetail(); get('detail').hidden = true; renderJobs(); setStatus('');
      const option = el('option','正在读取表格目录…'); option.value = ''; get('table').replaceChildren(option);
    }
    get('agent-collection').textContent = collection;
    try {await loadTables();} catch(error) {setStatus(error.message,true);}
    await cycle(true);
  }
  document.addEventListener('visibilitychange',() => {clearTimeout(timer); if (!document.hidden) cycle(true);});
  window.addEventListener('pagehide',() => {disposed = true; refreshRequested = false; clearTimeout(timer);});
  window.addEventListener('pageshow',event => {if (event.persisted) {disposed = false; refreshTools();}});
  document.addEventListener('workspace:view',event => {if (event.detail?.view === 'research') {window.enterpriseMotion?.tabs(tablist); cycle(true);} else clearTimeout(timer);});
  window.enterpriseTools = {refresh:refreshTools,trackJob,selectPanel:switchPanel};
  window.enterpriseMotion?.tabs(tablist);
  refreshTools();
})();
