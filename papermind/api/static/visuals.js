function sourceLocation(source, page) {
  if (source?.format === 'xlsx') return `${source.sheet} · ${source.cell_range}`;
  if (source?.format === 'docx') return source.paragraph ? `正文第 ${source.paragraph} 段` : `表格 ${source.table_number}${source.row ? ` · 第 ${source.row} 行` : ''}`;
  return page > 0 ? `第 ${page} 页` : '原始资料';
}
const analysisLabels = {not_configured: '未启用视觉分析', complete: '已生成视觉描述', failed: '视觉分析失败，原图已保留', skipped: '本次未进行视觉分析'};
function paragraph(text, className = '') {
  const element = document.createElement('p'); element.textContent = text; element.className = className; return element;
}
function imagePreview(url, caption) {
  const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener';
  const image = document.createElement('img'); image.src = url; image.alt = caption || '文献中的图片';
  image.loading = 'lazy'; image.className = 'figure-preview'; link.append(image); return link;
}
function tablePreview(table, selectedRow = -1) {
  const wrap = document.createElement('div'); wrap.className = 'table-scroll';
  const element = document.createElement('table');
  const caption = document.createElement('caption'); caption.textContent = table.caption || table.table_id; element.append(caption);
  const head = document.createElement('thead'); const header = document.createElement('tr');
  for (const title of table.headers) {const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = title; header.append(cell);}
  head.append(header); element.append(head); const body = document.createElement('tbody');
  table.rows.forEach((row, index) => {
    const tr = document.createElement('tr');
    if (index + (table.row_offset || 0) === selectedRow) tr.className = 'selected-row';
    for (const value of row) {const cell = document.createElement('td'); cell.textContent = value; tr.append(cell);}
    body.append(tr);
  });
  element.append(body); wrap.append(element);
  if (table.extraction_method === 'vlm') wrap.append(paragraph('表格由视觉模型识别，请对照原图核验数值与单位。', 'muted'));
  if (table.total_rows > table.rows.length) wrap.append(paragraph(`显示第 ${(table.row_offset || 0) + 1}–${(table.row_offset || 0) + table.rows.length} 行，共 ${table.total_rows} 行。`, 'muted'));
  return wrap;
}
function pagedTable(table, documentId, collection) {
  const container = document.createElement('div');
  const preview = document.createElement('div'); preview.append(tablePreview(table));
  container.append(preview);
  if (table.total_rows <= table.rows.length) return container;
  const controls = document.createElement('div'); controls.className = 'table-pagination';
  const previous = document.createElement('button'); previous.textContent = '← 上一页'; previous.className = 'secondary';
  const next = document.createElement('button'); next.textContent = '下一页 →'; next.className = 'secondary';
  const status = document.createElement('span'); status.setAttribute('role','status');
  let current = table;
  function update() {previous.disabled = current.row_offset === 0; next.disabled = current.row_offset + current.rows.length >= current.total_rows;}
  async function move(offset) {
    previous.disabled = true; next.disabled = true; status.textContent = '正在读取…';
    try {
      const response = await fetch(`/documents/${documentId}/tables/${table.table_id}?collection_id=${encodeURIComponent(collection)}&offset=${offset}&limit=20`);
      if (!response.ok) throw new Error('读取失败，请重试。');
      current = await response.json(); preview.replaceChildren(tablePreview(current)); status.textContent = '';
    } catch {status.textContent = '表格读取失败，请重试。';} finally {update();}
  }
  previous.onclick = () => move(Math.max(0,current.row_offset - 20));
  next.onclick = () => move(current.row_offset + current.rows.length);
  update(); controls.append(previous,next,status); container.append(controls); return container;
}
function renderMedia(source) {
  const result = document.createElement('div');
  if (source.image_url) result.append(imagePreview(source.image_url, source.figure?.caption || source.table?.caption));
  if (source.figure) {
    const figure = source.figure;
    result.append(paragraph(analysisLabels[figure.analysis_status] || '未分析', 'muted'));
    if (figure.caption) result.append(paragraph(`原文图注：${figure.caption}`));
    if (figure.visual_description) result.append(paragraph(`视觉模型描述：${figure.visual_description}`));
    if (figure.nearby_text) {
      const details = document.createElement('details'); const summary = document.createElement('summary');
      summary.textContent = '图片附近的原文'; details.append(summary, paragraph(figure.nearby_text)); result.append(details);
    }
  }
  if (source.table) result.append(tablePreview(source.table, source.metadata?.row_index));
  return result;
}
function renderVisualGallery(data, collection) {
  const container = document.createElement('div');
  const title = document.createElement('h2'); title.textContent = `${data.title} · 图表`; container.append(title);
  for (const [kind, items] of [['figure', data.figures], ['table', data.tables]]) {
    for (const item of items) {
      const card = document.createElement('article'); card.className = 'source';
      const page = document.createElement('a');
      page.href = `/documents/${data.document_id}/file?collection_id=${encodeURIComponent(collection)}${item.page > 0 ? `#page=${item.page}` : ''}`;
      page.target = '_blank'; page.rel = 'noopener'; page.textContent = `${item.figure_id || item.table_id} · ${sourceLocation(item.source,item.page)} · ${item.section}`;
      const url = item.asset_id ? `/documents/${data.document_id}/assets/${item.asset_id}?collection_id=${encodeURIComponent(collection)}` : '';
      if (kind === 'table') {
        card.append(page);
        if (url) card.append(imagePreview(url,item.caption));
        card.append(pagedTable(item,data.document_id,collection));
      } else card.append(page, renderMedia({[kind]: item, image_url: url}));
      container.append(card);
    }
  }
  if (!data.figures.length && !data.tables.length) container.append(paragraph('这份文献还没有图表记录。已有 PDF 可重新索引以提取图片。', 'muted'));
  if (data.warnings.length) container.append(paragraph(data.warnings.join('；'), 'muted'));
  return container;
}
