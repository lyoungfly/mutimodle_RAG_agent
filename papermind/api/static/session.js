let workspaceSession = null;
async function loadWorkspaceSession() {
  const response = await fetch('/api/access/me', {credentials:'same-origin',cache:'no-store'});
  if (!response.ok) throw new Error('无法读取登录状态，请刷新页面。');
  workspaceSession = await response.json();
  return workspaceSession;
}
async function sessionHeaders(options = {}) {
  const headers = new Headers(options.headers || {});
  if (!['GET','HEAD','OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
    const session = workspaceSession || await loadWorkspaceSession();
    if (session.csrf_token) headers.set('X-CSRF-Token',session.csrf_token);
  }
  return headers;
}
