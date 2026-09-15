// 在内存 DOM 中验证交互；不启动或控制用户浏览器。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname,'../papermind/api/static');
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
async function main(enterprise = false) {
  const collection = enterprise ? 'enterprise' : 'default';
  const dom = new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'), {url:`http://localhost/${enterprise ? '?workspace=enterprise' : ''}`,runScripts:'outside-only'});
  const w = dom.window, d = w.document;
  const errors = []; w.addEventListener('error', event => errors.push(event.error));
  let uploaded = 0, chats = 0, copied = '', failUploads = false;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.navigator.clipboard = {writeText: async value => {copied = value;}};
  const rows = [{document_id:'a',filename:'paper.pdf',indexed:1,chunk_count:3}];
  w.fetch = async (url, options={}) => {
    let data;
    if (url === '/health') data = {embedding_configured:true,reranker_configured:true,image_embedding_configured:false};
    else if (url === '/collections') data = [{collection_id:'papers',document_count:1}];
    else if (url.startsWith('/documents?')) data = url.endsWith('empty') ? [] : rows;
    else if (url === '/documents/upload') {uploaded++; if(failUploads)throw new Error('offline'); data = {document_id:'b'};}
    else if (url === '/documents/index') data = {chunk_count:2,warnings:[]};
    else if (url.includes('/visuals?')) data = {document_id:'a',title:'paper',figures:[],tables:[{table_id:'table_1',page:1,section:'Results',caption:'Results',headers:['Value'],rows:Array.from({length:20},(_,i)=>[String(i)]),row_offset:0,total_rows:21}],warnings:[]};
    else if (url.includes('/tables/')) data = {table_id:'table_1',headers:['Value'],rows:[['20']],row_offset:20,total_rows:21};
    else if (url === '/chat') {
      chats++; const body = JSON.parse(options.body); assert.equal(body.collection_id,collection);
      assert.equal(body.workspace_mode, enterprise ? 'enterprise' : 'research');
      data = {answer:'Safe <script>bad()</script> [1]',sources:[{id:1,filename:enterprise ? 'records.xlsx' : 'paper.pdf',page:enterprise ? 0 : 1,metadata:enterprise ? {source:{format:'xlsx',sheet:'June',cell_range:'A3:B3'}} : {},content_type:'text',section:'Method',content:'<img src=x onerror=bad()>',scores:{bm25:1},url:'/documents/a/file'}],retrieval_mode:'hybrid_rerank',latency:.2,mode:'evidence_only'};
    } else throw new Error(`Unexpected request: ${url}`);
    return {ok:true,json:async () => data};
  };
  for (const file of ['enterprise.js','visuals.js','workspace-ui.js','app.js']) new vm.Script(fs.readFileSync(path.join(root,file),'utf8')).runInContext(dom.getInternalVMContext());
  await tick();
  assert.equal(d.querySelector('#workspace-mode').value,enterprise ? 'enterprise' : 'research');
  assert.equal(d.querySelector('#collection').value,collection);
  assert.equal(d.querySelector('#enterprise-note').hidden,!enterprise);
  assert.match(d.querySelector('#file').accept,/\.docx,\.xlsx/);
  if (enterprise) assert.match(d.title,/IndustrialInsight/);
  assert.equal(d.querySelector('#stat-documents').textContent,'1');
  assert.equal(d.querySelector('#stat-chunks').textContent,'3');
  assert.equal(d.querySelector('#mode option[value=image]').disabled,true);
  d.querySelector('#nav-library').click();
  assert.equal(d.querySelector('#library-view').hidden,false);
  d.querySelector('#document-search').value='missing'; d.querySelector('#document-search').dispatchEvent(new w.Event('input'));
  assert.match(d.querySelector('#documents').textContent,/没有匹配/);
  d.querySelector('#document-search').value=''; d.querySelector('#document-search').dispatchEvent(new w.Event('input'));
  const file = new w.File(['sample text'],'upload.txt',{type:'text/plain'});
  Object.defineProperty(d.querySelector('#file'),'files',{value:[file],configurable:true});
  d.querySelector('#upload-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await tick();
  assert.equal(uploaded,1); assert.match(d.querySelector('#upload-status').textContent,/1\/1/);
  assert.equal(d.querySelector('#load').disabled,false);
  failUploads = true;
  d.querySelector('#upload-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await tick();
  assert.match(d.querySelector('#upload-status').textContent,/0\/1/); assert.equal(d.querySelector('#load').disabled,false);
  [...d.querySelectorAll('.document-actions button')].find(node=>node.textContent==='查看图表').click(); await tick();
  assert.equal(d.querySelector('#visual-panel').hidden,false);
  const pages = d.querySelectorAll('.table-pagination button'); assert.equal(pages[0].disabled,true);
  pages[1].click(); await tick(); assert.equal(pages[1].disabled,true); assert.equal(pages[0].disabled,false);
  assert.match(d.querySelector('#visuals').textContent,/21/);
  d.querySelector('#nav-research').click();
  d.querySelector('[data-question]').click(); assert.ok(d.querySelector('#question').value);
  d.querySelector('#chat-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await tick();
  assert.equal(chats,1); assert.equal(d.querySelector('#result-panel').hidden,false);
  assert.equal(d.querySelector('#answer script'),null); assert.equal(d.querySelector('#sources img'),null);
  assert.equal(d.querySelector('.citation-link').getAttribute('href'),'#evidence-1');
  d.querySelector('#copy-answer').click(); await tick(); assert.match(copied,enterprise ? /records.xlsx/ : /paper.pdf/);
  if (enterprise) {
    assert.match(d.querySelector('#sources').textContent,/June · A3:B3/);
    assert.doesNotMatch(d.querySelector('#sources').textContent,/第 0 页/);
    assert.match(copied,/IndustrialInsight/);
    assert.match(copied,/A3:B3/);
  }
  d.querySelector('#collection').value='empty'; d.querySelector('#load').click(); await tick();
  assert.equal(d.querySelector('#stat-documents').textContent,'0'); assert.equal(d.querySelector('#result-panel').hidden,true);
  d.querySelector('#chat-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await tick();
  assert.match(d.querySelector('#query-status').textContent,/没有已索引/); assert.equal(chats,1);
  assert.deepEqual(errors,[]);
  dom.window.close();
  console.log('DOM checks passed: navigation, stats, filtering, upload and failure recovery, table pagination, query, citations, escaping, copy, collection switch, empty state.');
}
main().then(() => main(true)).catch(error => {console.error(error); process.exitCode=1;});
