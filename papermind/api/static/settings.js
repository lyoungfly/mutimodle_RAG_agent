const byId = id => document.getElementById(id);
const cards = {};
let dirty = false;
let working = false;
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, cache: 'no-store', headers: {'Content-Type': 'application/json'},
    ...(body ? {body: JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求失败，请检查填写内容。');
  return result;
}
function status(element, message, ok) {
  element.textContent = message;
  element.classList.remove('success', 'error');
  if (ok !== undefined) element.classList.add(ok ? 'success' : 'error');
}
function lock(value) {
  working = value;
  byId('settings-form').querySelectorAll('button, input, select').forEach(element => {element.disabled = value;});
}
function payload(kind) {
  const card = cards[kind], field = name => card.querySelector(`[data-field="${name}"]`);
  return {enabled: field('enabled').checked, base_url: field('base_url').value.trim(), model: field('model').value.trim(),
    api_key: field('api_key').value.trim() || null, clear_api_key: field('clear_api_key').checked};
}
function createCard(kind, title, description) {
  const card = byId('connection-template').content.firstElementChild.cloneNode(true);
  card.querySelector('legend').textContent = title;
  card.querySelector('.role-help').textContent = description;
  card.querySelectorAll('[data-field]').forEach(input => {
    input.id = `${kind}-${input.dataset.field}`;
    const label = card.querySelector(`[data-label="${input.dataset.field}"]`);
    if (label) label.htmlFor = input.id;
  });
  if (kind === 'vlm') card.querySelector('option[value="deepseek"]').remove();
  card.querySelector('[data-field="preset"]').onchange = event => {
    const preset = event.target.value;
    if (preset) card.querySelector('[data-field="base_url"]').value = preset === 'local' ? 'http://127.0.0.1:8001/v1' : 'https://api.deepseek.com';
    status(card.querySelector('.test-status'), '地址已填写，请核对模型名称与该服务对应的密钥。');
  };
  card.querySelector('.show-key').onclick = event => {
    const key = card.querySelector('[data-field="api_key"]');
    key.type = key.type === 'password' ? 'text' : 'password';
    event.target.textContent = key.type === 'password' ? '显示' : '隐藏';
    event.target.setAttribute('aria-pressed', String(key.type === 'text'));
  };
  card.querySelector('.test-connection').onclick = async () => {
    if (working) return;
    const output = card.querySelector('.test-status');
    const body = payload(kind);
    if (!body.model || !body.base_url) {status(output, '请先填写 API 基础地址与模型名称。', false); return;}
    lock(true); status(output, '正在发送测试请求，请稍候…');
    try {const result = await api(`/api/settings/test/${kind}`, 'POST', body); status(output, result.message, result.ok);}
    catch (error) {status(output, error.message, false);} finally {lock(false);}
  };
  card.addEventListener('input', () => {dirty = true; status(card.querySelector('.test-status'), '配置已修改，请重新测试。');});
  card.addEventListener('change', () => {dirty = true;});
  cards[kind] = card; byId('connections').append(card);
}
function populate(data) {
  for (const kind of ['llm', 'vlm']) {
    const card = cards[kind], item = data[kind];
    for (const name of ['base_url', 'model']) card.querySelector(`[data-field="${name}"]`).value = item[name];
    card.querySelector('[data-field="enabled"]').checked = item.enabled;
    const key = card.querySelector('[data-field="api_key"]'); key.value = ''; key.type = 'password';
    key.placeholder = item.has_api_key ? '已保存密钥；留空保留' : '填写 API Key（无鉴权的本地服务可留空）';
    const show = card.querySelector('.show-key'); show.textContent = '显示'; show.setAttribute('aria-pressed', 'false');
    card.querySelector('[data-field="clear_api_key"]').checked = false;
    card.querySelector('.key-status').textContent = item.has_api_key ? '密钥已保存，不回显。地址改变时需重新填写密钥或清除旧密钥。' : '尚未保存密钥。';
  }
  byId('local-models').replaceChildren();
  for (const [name, value] of Object.entries(data.local_models)) {
    const row = document.createElement('li'); row.textContent = `${{embedding:'文本向量', reranker:'重排', image_embedding:'图像向量'}[name]}：${value || '未配置'}`; byId('local-models').append(row);
  }
}
byId('settings-form').onsubmit = async event => {
  event.preventDefault(); if (working) return;
  const body = {llm: payload('llm'), vlm: payload('vlm')};
  lock(true); status(byId('save-status'), '正在保存配置…');
  try {const result = await api('/api/settings', 'PUT', body); populate(result); dirty = false; status(byId('save-status'), result.message, true);}
  catch (error) {status(byId('save-status'), error.message, false);} finally {lock(false);}
};
window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
async function initialize() {
  createCard('llm', '01 / 回答模型', '生成带引用的回答，使用时会向此服务发送问题与检索片段。关闭后仍可查看证据。');
  createCard('vlm', '02 / 视觉模型（可选）', '索引时向此服务发送提取的图片、图注和附近正文，分析图表。请选择支持图片输入的模型。');
  lock(true);
  try {populate(await api('/api/settings')); lock(false); status(byId('save-status'), '已读取当前配置。修改后请保存；测试连接不会保存配置。');}
  catch (error) {status(byId('save-status'), error.message, false);}
}
initialize();
