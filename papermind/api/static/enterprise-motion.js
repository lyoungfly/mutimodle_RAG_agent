(() => {
  if (!document.body.classList.contains('enterprise')) return;
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const animations = new Map(), tablists = new Set(), positions = new WeakMap();
  const closing = new WeakSet();
  const easing = 'cubic-bezier(.22, 1, .36, 1)';
  let navigating = false;
  const enabled = () => !preference.matches && !document.hidden;

  function cancel(node) {
    const record = animations.get(node);
    if (!record) return;
    animations.delete(node); record.animation.cancel(); record.cleanup();
  }
  function play(node, frames, options = {}, cleanup = () => {}, finish = () => {}) {
    cancel(node);
    if (!enabled() || !node.animate) {cleanup(); finish(); return null;}
    const animation = node.animate(frames, {duration:300, easing, ...options});
    const record = {animation,cleanup}; animations.set(node, record);
    animation.finished.then(() => {
      if (animations.get(node) !== record) return;
      animations.delete(node); animation.cancel(); cleanup(); finish();
    }, () => {});
    return animation;
  }
  function enter(node, options = {}) {
    if (!node || node.hidden || !node.getClientRects().length) return;
    play(node, [{opacity:0, translate:'0 12px'}, {opacity:1, translate:'0 0'}], options);
  }
  function resize(node, previousHeight) {
    if (!node || !previousHeight || !enabled()) return;
    cancel(node);
    const height = node.getBoundingClientRect().height;
    if (!height || Math.abs(height - previousHeight) < 2) return;
    const overflow = node.style.overflow;
    node.style.overflow = 'hidden';
    play(node, [{height:`${previousHeight}px`}, {height:`${height}px`}], {duration:240}, () => {node.style.overflow = overflow;});
  }
  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => {
    for (const {target} of entries) positionTabs(target, false);
  }) : null;

  function positionTabs(tablist, animate = true) {
    const selected = tablist.querySelector('[aria-selected="true"]');
    const indicator = tablist.querySelector('.enterprise-tab-indicator');
    if (!selected || !indicator || !selected.getClientRects().length) return;
    const next = {left:selected.offsetLeft, top:selected.offsetTop, width:selected.offsetWidth, height:selected.offsetHeight};
    const previous = positions.get(tablist);
    positions.set(tablist,next);
    cancel(indicator);
    Object.assign(indicator.style, {left:`${next.left}px`,top:`${next.top}px`,width:`${next.width}px`,height:`${next.height}px`});
    if (animate && previous && next.width && (previous.left !== next.left || previous.width !== next.width)) {
      play(indicator, [
        {transform:`translate(${previous.left-next.left}px, ${previous.top-next.top}px) scaleX(${previous.width/next.width})`},
        {transform:'translate(0, 0) scaleX(1)'}
      ], {duration:280});
    }
  }
  function tabs(tablist) {
    if (!tablist) return;
    if (!tablists.has(tablist)) {tablists.add(tablist); resizeObserver?.observe(tablist);}
    positionTabs(tablist);
  }
  function scrollTo(node) {
    node?.scrollIntoView({behavior:enabled() ? 'smooth' : 'auto',block:'center'});
  }

  // 展开时保留原生 details 语义，快速连点会取消上一段动画。
  document.addEventListener('click', event => {
    const summary = event.target.closest('summary');
    const detail = summary?.parentElement;
    if (!detail?.matches('details') || !detail.closest('#main-content') || !enabled()) return;
    if (event.target.closest('a,button,input,select,textarea')) return;
    event.preventDefault();
    const expand = !detail.open || closing.has(detail);
    const previousHeight = detail.getBoundingClientRect().height;
    cancel(detail); closing.delete(detail);
    const overflow = detail.style.overflow;
    detail.open = true;
    if (expand) detail.dispatchEvent(new Event('enterprise:expand'));
    const style = getComputedStyle(detail);
    const nextHeight = expand ? detail.getBoundingClientRect().height :
      summary.getBoundingClientRect().bottom - detail.getBoundingClientRect().top +
      parseFloat(style.paddingBottom || 0) + parseFloat(style.borderBottomWidth || 0);
    if (!expand) closing.add(detail);
    detail.style.overflow = 'hidden';
    play(detail, [{height:`${previousHeight}px`}, {height:`${nextHeight}px`}], {duration:240},
      () => {detail.style.overflow = overflow; closing.delete(detail);},
      () => {detail.open = expand;});
  });

  async function navigate(destination) {
    if (navigating) return;
    navigating = true;
    const shell = document.querySelector('.app-shell');
    const animation = play(shell, [{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(6px)'}], {duration:140,fill:'forwards'});
    if (animation) await animation.finished.catch(() => {});
    location.assign(destination);
  }
  function viewChanged(event) {
    enter(document.getElementById(`${event.detail.view}-view`));
    for (const tablist of tablists) positionTabs(tablist, false);
    enter(document.getElementById('view-title'), {duration:200});
  }
  function stopAnimations() {
    for (const node of [...animations.keys()]) cancel(node);
  }
  function visibilityChanged() {
    document.body.classList.toggle('enterprise-page-hidden',document.hidden);
    if (document.hidden) stopAnimations();
  }
  preference.addEventListener('change', () => {if (preference.matches) stopAnimations();});
  document.addEventListener('visibilitychange',visibilityChanged);
  document.addEventListener('workspace:view',viewChanged);
  window.addEventListener('pagehide', () => {stopAnimations(); resizeObserver?.disconnect();});
  window.addEventListener('pageshow', event => {
    navigating = false;
    if (event.persisted) {
      document.getElementById('workspace-mode').value = workspaceMode;
      for (const tablist of tablists) {resizeObserver?.observe(tablist); positionTabs(tablist,false);}
      visibilityChanged();
    }
  });
  window.enterpriseMotion = {enter,resize,tabs,scrollTo,navigate};
  document.addEventListener('DOMContentLoaded', () => {
    const nodes = document.querySelectorAll('.hero-copy, .enterprise-hero-visual, .metrics, .composer-panel, .enterprise-tools');
    nodes.forEach((node,index) => enter(node, {delay:index*45,duration:440,fill:'backwards'}));
    for (const tablist of document.querySelectorAll('.enterprise-tool-tabs')) tabs(tablist);
  }, {once:true});
})();
