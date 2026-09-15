(() => {
  const get = id => document.getElementById(`access-${id}`);
  const el = (tag,text = '',className = '') => {const node = document.createElement(tag); node.textContent = text; node.className = className; return node;};
  let session = null, users = [], permissions = {grants:[],documents:[],document_grants:[]}, collection = 'enterprise', working = false;
  const roleNames = {admin:'管理员',member:'普通成员',viewer:'查看者',editor:'编辑者',none:'无单独授权'};
  const setStatus = (text,type = '') => {get('status').textContent = text; get('status').className = `access-status ${type}`;};
  async function api(path,method = 'GET',body) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && session?.csrf_token) headers['X-CSRF-Token'] = session.csrf_token;
    let response;
    try {response = await fetch(`/api/access/${path}`,{method,credentials:'same-origin',headers,body:body === undefined ? undefined : JSON.stringify(body)});}
    catch {throw new Error('无法连接服务，请确认本地服务已启动。');}
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) {session = {...session,authenticated:false}; renderSession();}
      throw new Error(typeof data.detail === 'string' ? data.detail : '操作未完成，请检查输入及权限后重试。');
    }
    return data;
  }
  async function perform(action,success = '') {
    if (working) return;
    working = true; document.querySelectorAll('button').forEach(button => {button.disabled = true;}); setStatus('正在处理…');
    try {await action(); setStatus(success,'success');}
    catch (error) {setStatus(error.message,'error');}
    finally {working = false; document.querySelectorAll('button').forEach(button => {button.disabled = false;}); renderDocument();}
  }
  function emptyRow(body,columns,message) {const row = el('tr'), cell = el('td',message,'access-empty'); cell.colSpan = columns; row.append(cell); body.append(row);}
  const username = id => users.find(user => String(user.id) === String(id))?.username || id || '—';
  function renderSession() {
    const authenticated = session?.authenticated === true;
    const bootstrap = session?.enabled === false && session?.can_bootstrap === true;
    get('login-panel').hidden = authenticated || (!session?.enabled && !bootstrap);
    get('disabled-panel').hidden = authenticated || session?.enabled !== false || bootstrap;
    get('account-panel').hidden = !authenticated;
    get('admin-panel').hidden = !authenticated || session.user?.role !== 'admin';
    get('state').textContent = authenticated ? '已登录 · '+(roleNames[session.user?.role] || '成员') : session?.enabled ? '权限已启用 · 请登录' : '尚未启用权限';
    get('login-title').textContent = bootstrap ? '创建首个管理员' : '登录工作空间';
    get('login-description').textContent = bootstrap ? '此操作会开启账户权限。使用此管理员账户管理成员、知识库和受限文档。' : '输入管理员分配的账户与密码。';
    get('login-submit').textContent = bootstrap ? '创建管理员并开启权限 →' : '登录 →';
    get('password-hint').hidden = !bootstrap;
    get('password').minLength = bootstrap ? 12 : 1;
    get('password').autocomplete = bootstrap ? 'new-password' : 'current-password';
    if (authenticated) {
      get('account-name').textContent = session.user?.username || '当前账户';
      get('account-role').textContent = session.user?.role === 'admin' ? '你是管理员，可创建成员、分配权限和查看审计记录。' : '你可以访问管理员授权的知识库和文档。如需更多权限，请联系管理员。';
    }
  }
  function renderUsers() {
    get('users').replaceChildren();
    for (const user of users) {
      const row = el('tr'), identity = el('td',String(user.id),'access-mono');
      if (user.role !== 'admin') {
        const button = el('button',user.active ? '停用账号' : '启用账号','secondary'); button.type = 'button';
        button.onclick = () => perform(async () => {await api(`users/${encodeURIComponent(user.id)}`,'PUT',{active:!Boolean(user.active)}); await loadUsers(); await loadAudit();},'成员状态已更新。停用时现有登录会话同时失效。');
        identity.append(document.createElement('br'),button);
      }
      row.append(el('td',user.username),el('td',(roleNames[user.role] || user.role) + (user.active ? '' : ' · 已停用')),identity); get('users').append(row);
    }
    if (!users.length) emptyRow(get('users'),3,'暂无成员');
    for (const select of [get('grant-user'),get('doc-user')]) {
      const selected = select.value; select.replaceChildren();
      for (const user of users.filter(user => user.role !== 'admin')) {const option = el('option',user.username); option.value = user.id; select.append(option);}
      if (!select.options.length) {const option = el('option','请先创建普通成员'); option.value = ''; select.append(option);}
      else if (Array.from(select.options).some(option => option.value === selected)) select.value = selected;
    }
  }
  async function loadUsers() {
    const data = await api('users'); users = Array.isArray(data) ? data : data.users || []; renderUsers();
  }
  function renderPermissions() {
    get('grants').replaceChildren();
    for (const grant of permissions.grants || []) {const row = el('tr'); row.append(el('td',username(grant.user_id)),el('td',roleNames[grant.role] || grant.role)); get('grants').append(row);}
    if (!permissions.grants?.length) emptyRow(get('grants'),2,'尚未为普通成员分配知识库权限');
    const previous = get('document').value; get('document').replaceChildren();
    for (const doc of permissions.documents || []) {const option = el('option',doc.filename || doc.document_id); option.value = doc.document_id; get('document').append(option);}
    if (!permissions.documents?.length) {const option = el('option','此知识库还没有文档'); option.value = ''; get('document').append(option);}
    else if (Array.from(get('document').options).some(option => option.value === previous)) get('document').value = previous;
    renderDocument();
  }
  function renderDocument() {
    const doc = (permissions.documents || []).find(item => item.document_id === get('document').value);
    get('restricted').checked = doc?.restricted === true;
    get('document-state').textContent = doc ? doc.restricted ? '当前：受限文档。仅管理员与获得该文档授权的成员可访问。' : '当前：继承知识库权限。知识库授权成员可按对应角色访问。' : '请先在企业资料库上传文档，再加载此知识库的权限。';
    for (const form of [get('restriction-form'),get('document-grant-form')]) form.querySelectorAll('button,input,select').forEach(input => {input.disabled = !doc || working;});
    get('document-grants').replaceChildren();
    const grants = (permissions.document_grants || []).filter(grant => grant.document_id === doc?.document_id);
    for (const grant of grants) {const row = el('tr'); row.append(el('td',username(grant.user_id)),el('td',roleNames[grant.role] || grant.role)); get('document-grants').append(row);}
    if (!grants.length) emptyRow(get('document-grants'),2,'此文档没有单独授权');
  }
  async function loadPermissions() {
    const scope = collection;
    const data = await api(`grants?collection_id=${encodeURIComponent(scope)}`);
    if (scope !== collection) return;
    permissions = data; renderPermissions();
  }
  async function loadAudit() {
    const data = await api('audit'); get('audit-rows').replaceChildren();
    const events = Array.isArray(data) ? data : data.events || [];
    for (const event of events) {
      const row = el('tr'), value = event.at ?? event.created_at ?? event.timestamp ?? event.time, date = new Date(typeof value === 'number' ? value * 1000 : value);
      const details = [event.target || '', event.detail || ''].filter(Boolean).join(' · ');
      row.append(el('td',Number.isNaN(date.getTime()) ? String(value || '') : date.toLocaleString()),
        el('td',event.username || username(event.actor || event.user_id || event.actor_id)),el('td',String(event.action || event.event || '')),
        el('td',typeof details === 'object' ? JSON.stringify(details) : String(details)));
      get('audit-rows').append(row);
    }
    if (!events.length) emptyRow(get('audit-rows'),4,'暂无审计记录');
  }
  async function initialize() {
    session = await api('me'); renderSession();
    if (session.authenticated && session.user?.role === 'admin') {await loadUsers(); await loadPermissions(); await loadAudit();}
  }
  get('login-form').onsubmit = event => {
    event.preventDefault();
    perform(async () => {
      const bootstrap = session?.enabled === false && session?.can_bootstrap;
      await api(bootstrap ? 'bootstrap' : 'login','POST',{username:get('username').value.trim(),password:get('password').value});
      get('password').value = ''; await initialize();
    },'登录成功。你可以进入企业工作台。');
  };
  get('logout').onclick = () => perform(async () => {await api('logout','POST',{}); get('password').value = ''; users = []; permissions = {grants:[],documents:[],document_grants:[]}; renderUsers(); renderPermissions(); await initialize();},'已退出登录。');
  get('user-form').onsubmit = event => {
    event.preventDefault(); perform(async () => {await api('users','POST',{username:get('new-username').value.trim(),password:get('new-password').value}); get('new-password').value = ''; get('new-username').value = ''; await loadUsers();},'成员已创建。请继续分配资料权限。');
  };
  get('scope-form').onsubmit = event => {
    event.preventDefault(); perform(async () => {
      const previous = collection; collection = get('collection').value.trim();
      try {await loadPermissions();} catch (error) {collection = previous; get('collection').value = previous; throw error;}
    },'知识库权限已加载。');
  };
  get('grant-form').onsubmit = event => {
    event.preventDefault(); perform(async () => {await api('grants','PUT',{collection_id:collection,user_id:get('grant-user').value,role:get('grant-role').value}); await loadPermissions(); await loadAudit();},'知识库权限已保存。');
  };
  get('restriction-form').onsubmit = event => {
    event.preventDefault(); perform(async () => {await api('document-grants','PUT',{collection_id:collection,document_id:get('document').value,restricted:get('restricted').checked,role:'none'}); await loadPermissions(); await loadAudit();},'文档访问范围已保存。');
  };
  get('document-grant-form').onsubmit = event => {
    event.preventDefault(); perform(async () => {
      const doc = (permissions.documents || []).find(item => item.document_id === get('document').value);
      if (!doc?.restricted) throw new Error('请先将此文档设为受限并保存，再分配文档权限。');
      await api('document-grants','PUT',{collection_id:collection,document_id:doc.document_id,restricted:true,user_id:get('doc-user').value,role:get('doc-role').value}); await loadPermissions(); await loadAudit();
    },'文档权限已保存。');
  };
  get('document').onchange = renderDocument;
  get('refresh-users').onclick = () => perform(async () => {await loadUsers(); renderPermissions();},'成员列表已更新。');
  get('refresh-audit').onclick = () => perform(loadAudit,'审计记录已更新。');
  initialize().catch(error => setStatus(error.message,'error'));
})();
