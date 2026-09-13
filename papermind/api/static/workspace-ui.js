const $ = id => document.getElementById(id);
const modeLabels = {bm25:'关键词检索', dense:'语义检索', hybrid:'融合检索', hybrid_rerank:'融合检索 + 重排', image:'图像检索', multimodal:'多模态融合', multimodal_rerank:'多模态融合 + 重排'};
function element(tag, text = '', className = '') {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
}
let toastTimer;
function toast(message) {clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false; toastTimer = setTimeout(() => {$('toast').hidden = true;}, 4500);}
function message(id, text, type = '') {
  const node = $(id); node.textContent = text; node.classList.remove('error', 'loading', 'success'); if (type) node.classList.add(type);
}
function showView(view) {
  const library = view === 'library';
  $('research-view').hidden = library; $('library-view').hidden = !library; $('visual-panel').hidden = true;
  $('view-title').textContent = library ? '文献库' : '研究工作台';
  for (const name of ['research','library']) {
    const active = name === view; $(`nav-${name}`).classList.toggle('active', active);
    if (active) $(`nav-${name}`).setAttribute('aria-current', 'page'); else $(`nav-${name}`).removeAttribute('aria-current');
  }
}
function renderAnswer(result) {
  $('answer').replaceChildren();
  const ids = new Set(result.sources.map(source => String(source.id)));
  for (const part of result.answer.split(/(\[\d+\])/g)) {
    const id = part.slice(1,-1);
    if (/^\[\d+\]$/.test(part) && ids.has(id)) {
      const link = element('a', part, 'citation-link'); link.href = `#evidence-${id}`; link.title = `查看证据 ${id}`; $('answer').append(link);
    } else $('answer').append(document.createTextNode(part));
  }
  $('source-count').textContent = result.sources.length;
  $('sources').replaceChildren();
  for (const source of result.sources) {
    const card = element('article', '', 'source'); card.id = `evidence-${source.id}`;
    const badge = element('div', {text:'正文证据',table:'表格证据',figure:'图片证据'}[source.content_type] || '来源', 'source-badge');
    const link = element('a', `[${source.id}] ${source.filename} · 第 ${source.page} 页 ↗`); link.href = source.url; link.target = '_blank'; link.rel = 'noopener';
    const meta = element('small', source.section || '未标注章节');
    const details = element('details'); details.append(element('summary','检索分数'), element('pre',JSON.stringify(source.scores,null,2)));
    card.append(badge, element('div'), link, meta, renderMedia(source), element('pre',source.content), details); $('sources').append(card);
  }
  if (!result.sources.length) $('sources').append(element('p','没有找到可引用的证据。尝试调整问题或扩大证据范围。','empty-state'));
  $('result-panel').hidden = false; $('start-panel').hidden = true;
}
function exportText(question, result) {
  return ['PaperMind · 研究结果', `问题：${question}`, '', result.answer, '', '参考证据', ...result.sources.map(source =>
    `[${source.id}] ${source.filename} · 第 ${source.page} 页 · ${source.section}\n${new URL(source.url,location.origin).href}\n${source.content}`)].join('\n\n');
}
function downloadText(text) {
  const url = URL.createObjectURL(new Blob(['\uFEFF',text],{type:'text/plain;charset=utf-8'}));
  const link = element('a'); link.href = url; link.download = `PaperMind-${new Date().toISOString().slice(0,10)}.txt`;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
}
