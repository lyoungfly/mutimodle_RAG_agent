let activeCollection = enterpriseMode ? 'enterprise' : 'default';
for (const id of ['collection','active-library','library-badge']) {if (id === 'collection') $(id).value = activeCollection; else $(id).textContent = activeCollection;}
let busy = false;
let documents = [];
let lastResult = null;
let lastQuestion = '';
async function request(path, options = {}) {
  let response;
  try {response = await fetch(path, {...options,headers:await sessionHeaders(options),credentials:'same-origin'});} catch {throw new Error(`无法连接 ${workspaceBrand}，请检查本地服务是否启动后重试。`);}
  let data;
  try {data = await response.json();} catch {throw new Error('服务返回了无法读取的结果，请稍后重试。');}
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请检查输入后重试。');
  return data;
}
const post = (path, data) => request(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
function lock(value) {
  busy = value;
  document.querySelectorAll('button,input,textarea,select').forEach(node => {
    // 等待业务请求时，仍可切换视图、浏览任务和展开已有证据。
    if (enterpriseMode && node.matches('.side-nav button, [data-enterprise-action], #open-library, #document-search, #close-visuals')) return;
    if (enterpriseMode && node.closest('#enterprise-tools')) return;
    if (!node.closest('.table-pagination')) node.disabled = value;
  });
  $('main-content').classList.toggle('workspace-busy',value);
  if (!enterpriseMode) $('main-content').setAttribute('aria-busy', String(value));
}
function renderDocuments() {
  const query = $('document-search').value.trim().toLocaleLowerCase();
  const rows = documents.filter(row => row.filename.toLocaleLowerCase().includes(query));
  $('documents').replaceChildren();
  for (const row of rows) {
    const item = element('li','','document-card');
    item.append(element('span',row.filename.split('.').pop().toUpperCase(),'doc-icon'),element('h3',row.filename),
      element('p',row.indexed ? `● 已就绪 · ${row.chunk_count} 个证据块` : '○ 待索引 · 建立索引后即可检索'));
    const actions = element('div','','document-actions');
    const raw = element('a','查看原文 ↗','button secondary'); raw.href = `/documents/${row.document_id}/file?collection_id=${encodeURIComponent(activeCollection)}`; raw.target = '_blank'; raw.rel = 'noopener';
    const index = element('button',row.indexed ? '重新索引' : '建立索引','secondary');
    index.onclick = async () => {
      if (busy) return; lock(true); message('upload-status',`正在解析与索引 ${row.filename}…`,'loading');
      try {const result = await post(enterpriseMode ? '/api/enterprise/index' : '/documents/index',{document_id:row.document_id,collection_id:activeCollection});
        if (enterpriseMode) {
          message('upload-status',`已提交后台索引任务 ${result.id.slice(0,8)}，可在企业任务中查看进度。`);
          window.enterpriseTools?.trackJob(result);
        } else message('upload-status',`索引完成，共 ${result.chunk_count} 个证据块。${result.warnings.join('；')}`);
        await refresh();
      } catch (error) {message('upload-status',error.message,'error');} finally {lock(false);}
    };
    actions.append(raw,index);
    if (row.indexed) {
      const view = element('button','查看图表','secondary');
      view.onclick = async () => {
        if (busy) return; lock(true); message('upload-status','正在读取图表…','loading');
        try {const data = await request(`/documents/${row.document_id}/visuals?collection_id=${encodeURIComponent(activeCollection)}`);
          $('visuals').replaceChildren(renderVisualGallery(data,activeCollection)); $('visual-panel').hidden = false;
          if (window.enterpriseMotion) {window.enterpriseMotion.enter($('visual-panel')); window.enterpriseMotion.scrollTo($('visual-panel'));}
          else $('visual-panel').scrollIntoView({behavior:'smooth',block:'start'});
          message('upload-status','');
        } catch (error) {message('upload-status',error.message,'error');} finally {lock(false);}
      };
      actions.append(view);
    }
    item.append(actions); $('documents').append(item);
  }
  if (!rows.length) {
    const empty = element('li','','empty-state'); empty.append(element('strong',query ? `没有匹配的${enterpriseMode ? '资料' : '文献'}` : enterpriseMode ? '从第一份业务资料开始' : '你的下一个发现，从这里开始'),
      element('p',query ? '尝试其他文件名关键词。' : enterpriseMode ? '上传规范、手册或业务记录，建立团队可追溯的知识来源。' : '添加第一份文献，PaperMind 会为它建立可追溯的证据索引。')); $('documents').append(empty);
  }
}
async function refresh() {
  documents = await request(`/documents?collection_id=${encodeURIComponent(activeCollection)}`);
  for (const id of ['stat-documents','document-count','nav-count']) $(id).textContent = documents.length;
  $('stat-indexed').textContent = documents.filter(row => row.indexed).length;
  $('stat-chunks').textContent = documents.reduce((total,row) => total + row.chunk_count,0).toLocaleString();
  renderDocuments();
}
async function refreshCollections() {
  const collections = await request('/collections'); $('collection-list').replaceChildren();
  for (const name of new Set([enterpriseMode ? 'enterprise' : 'default',activeCollection,...collections.map(row => row.collection_id)])) {
    const option = element('option'); option.value = name; $('collection-list').append(option);
  }
  return collections;
}
$('load').onclick = async () => {
  if (busy) return;
  const next = $('collection').value.trim();
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(next)) {toast('知识库名称需为 1–64 位字母、数字、下划线或连字符。'); return;}
  lock(true); const previous = activeCollection; activeCollection = next;
  try {await refresh();
    $('active-library').textContent = next; $('library-badge').textContent = next;
    $('result-panel').hidden = true; $('start-panel').hidden = false; $('visual-panel').hidden = true; lastResult = null;
    $('answer').replaceChildren(); $('sources').replaceChildren(); $('visuals').replaceChildren();
    $('upload-results').replaceChildren(); message('upload-status',''); message('query-status','');
    $('document-search').value = ''; renderDocuments();
    toast(`已切换到 ${next}`);
    window.enterpriseMotion?.enter(document.querySelector('#research-view:not([hidden]), #library-view:not([hidden])'));
    window.enterpriseTools?.refresh();
  } catch (error) {activeCollection = previous; $('collection').value = previous; toast(error.message);} finally {lock(false);}
};
$('collection').onkeydown = event => {if(event.key === 'Enter') {event.preventDefault(); $('load').click();}};
$('upload-form').onsubmit = async event => {
  event.preventDefault(); if (busy) return;
  const files = Array.from($('file').files);
  if (!files.length || files.length > 10) {message('upload-status','请选择 1–10 个文件。','error'); return;}
  if (files.some(file => !file.size || file.size > 25 * 1024 * 1024)) {message('upload-status','文件不能为空，且每个文件不能超过 25 MB。','error'); return;}
  lock(true); $('upload-results').replaceChildren(); let completed = 0;
  for (const [i,file] of files.entries()) {
    message('upload-status',`正在处理 ${i+1}/${files.length}：${file.name}。首次加载模型可能需要稍候…`,'loading');
    const row = element('li'); $('upload-results').append(row);
    try {
      const body = new FormData(); body.append('file',file); body.append('collection_id',activeCollection);
      const uploaded = await request('/documents/upload',{method:'POST',body});
      const indexed = await post(enterpriseMode ? '/api/enterprise/index' : '/documents/index',{document_id:uploaded.document_id,collection_id:activeCollection});
      if (enterpriseMode) {
        row.textContent = `✓ ${file.name} · 已进入后台索引队列（${indexed.id.slice(0,8)}）`;
        window.enterpriseTools?.trackJob(indexed);
      } else row.textContent = `✓ ${file.name} · ${indexed.chunk_count} 个证据块${indexed.warnings.length ? ' · '+indexed.warnings.join('；') : ''}`;
      row.className = 'success'; completed++;
    } catch (error) {row.textContent = `× ${file.name}：${error.message}`; row.className = 'error';}
  }
  $('file').value = ''; message('upload-status',enterpriseMode ? `已提交 ${completed}/${files.length} 个后台索引任务。完成后可提问；提交失败的资料可在下方重试。` : `处理完成：${completed}/${files.length} 份文献已就绪。${completed < files.length ? '已上传但未索引的文献可在下方重试。' : '返回研究工作台即可提问。'}`,completed === files.length ? 'success' : 'error');
  try {await refresh(); await refreshCollections();} catch(error) {toast(error.message);} finally {lock(false);}
};
$('chat-form').onsubmit = async event => {
  event.preventDefault(); if (busy) return;
  const question = $('question').value.trim(); if (!question) {message('query-status','请先填写一个具体问题。','error'); return;}
  if (!documents.some(row => row.indexed)) {message('query-status','当前知识库没有已索引文献。请先到文献库上传资料并建立索引。','error'); return;}
  lock(true); $('ask-button').setAttribute('aria-busy','true');
  message('query-status','正在查找相关证据并整理结果…','loading'); $('result-panel').hidden = true; lastResult = null;
  try {
    const type = $('type').value;
    const result = await post('/chat',{question,workspace_mode:workspaceMode,collection_id:activeCollection,mode:$('mode').value,filters:type ? {content_type:type} : null});
    lastResult = result; lastQuestion = question; renderAnswer(result);
    message('query-status',`${modeLabels[result.retrieval_mode] || result.retrieval_mode} · ${result.latency} 秒 · ${result.mode === 'evidence_only' ? '检索证据（未启用回答模型）' : result.abstained ? '证据不足，未生成结论' : '带引用的回答'}`);
  } catch(error) {message('query-status',error.message,'error');} finally {$('ask-button').removeAttribute('aria-busy'); lock(false);}
};
$('document-search').oninput = renderDocuments;
$('nav-research').onclick = () => showView('research'); $('nav-library').onclick = () => showView('library'); $('open-library').onclick = () => showView('library');
$('close-visuals').onclick = () => {$('visual-panel').hidden = true;};
document.querySelectorAll('[data-question]').forEach(button => {button.onclick = () => {$('question').value = button.dataset.question; $('type').value = button.dataset.type || ''; $('question').focus();};});
$('copy-answer').onclick = async () => {if(!lastResult)return; try {await navigator.clipboard.writeText(exportText(lastQuestion,lastResult)); toast('已复制结果和引用来源。');} catch {toast('浏览器未允许复制，请使用导出 TXT。');}};
$('export-answer').onclick = () => {if(lastResult)downloadText(exportText(lastQuestion,lastResult));};
$('question').onkeydown = event => {if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {event.preventDefault(); $('chat-form').requestSubmit();}};
async function initialize() {
  lock(true);
  try {
    const session = await loadWorkspaceSession();
    if (session.enabled && !session.authenticated) {
      $('access-link').textContent = '登录工作空间 ↗';
      throw new Error('已启用成员权限，请点击右上角「登录工作空间」后访问资料。');
    }
    if (session.enabled) $('access-link').textContent = `${session.user.username} · 账号管理`;
    const info = await request('/health'); $('connection-state').textContent = '服务已连接';
    $('model-label').textContent = info.llm_configured ? '回答模型已配置' : '证据检索模式';
    $('capabilities').textContent = [info.embedding_configured ? '语义检索可用' : '关键词检索可用',info.image_embedding_configured ? '图像检索可用' : '未启用图像向量',info.vlm_configured ? '已配置视觉分析' : '图表保留原图与图注',info.llm_configured ? '已配置回答模型' : '连接回答模型可生成引用回答'].join(' · ');
    for (const option of $('mode').options) {
      option.disabled = (['dense','hybrid','hybrid_rerank'].includes(option.value) && !info.embedding_configured) ||
        (['image','multimodal','multimodal_rerank'].includes(option.value) && !info.image_embedding_configured) ||
        (['hybrid_rerank','multimodal_rerank'].includes(option.value) && !info.reranker_configured);
    }
    const collections = await refreshCollections();
    if (session.enabled && session.user.role !== 'admin' && !collections.some(c => c.collection_id === activeCollection)) {
      if (!collections.length) throw new Error('尚未分配知识库，请联系管理员授权。');
      activeCollection = collections[0].collection_id;
      $('collection').value = activeCollection;
      $('active-library').textContent = activeCollection; $('library-badge').textContent = activeCollection;
    }
    await refresh(); window.enterpriseTools?.refresh();
  } catch(error) {$('connection-state').textContent = '连接异常'; $('connection-state').classList.add('offline'); message('query-status',error.message,'error'); $('capabilities').textContent = '连接失败，请刷新页面重试。';}
  finally {lock(false);}
}
initialize();
