// files.js - 录音文件页面逻辑
var currentPage = 1;
var pageSize = 10;
var totalItems = 0;
var selectedIds = [];
var selectedFileIds = [];

function initPage() {
  var main = document.getElementById('main-content');
  if (!main) return;

  main.innerHTML = '<div class="page-header">' +
    '<h1 class="page-title">录音文件</h1>' +
    '<div class="page-actions">' +
      '<button class="btn btn-primary" id="upload-btn" onclick="showUploadModal()">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>' +
        '<span>上传录音</span>' +
      '</button>' +
      '<button class="btn btn-secondary" id="merge-analyze-btn" style="display: none;" onclick="showMergeConfirm()">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>' +
        '<span>合并分析 (<span id="merge-count">0</span>)</span>' +
      '</button>' +
      '<button class="btn btn-danger" id="batch-delete-btn" style="display: none;">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
        '<span>批量删除 (<span id="selected-count">0</span>)</span>' +
      '</button>' +
    '</div>' +
  '</div>' +
  
  '<div class="filters-bar">' +
    '<input type="text" class="form-input" id="search-input" placeholder="搜索文件名...">' +
    '<select class="form-select" id="status-filter">' +
      '<option value="">全部状态</option>' +
      '<option value="pending">待处理</option>' +
      '<option value="processing">处理中</option>' +
      '<option value="completed">已完成</option>' +
      '<option value="failed">失败</option>' +
    '</select>' +
    '<button class="btn btn-ghost" id="clear-filters">清除筛选</button>' +
  '</div>' +
  
  '<div class="table-wrapper">' +
    '<table>' +
      '<thead>' +
        '<tr>' +
          '<th class="table-checkbox"><input type="checkbox" id="select-all"></th>' +
          '<th>文件名</th>' +
          '<th>时长</th>' +
          '<th>格式</th>' +
          '<th>状态</th>' +
          '<th>上传时间</th>' +
          '<th>操作</th>' +
        '</tr>' +
      '</thead>' +
      '<tbody id="files-table-body">' +
        '<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--muted);">加载中...</td></tr>' +
      '</tbody>' +
    '</table>' +
  '</div>' +
  
  '<div class="pagination" id="pagination"></div>';
  
  var searchInput = document.getElementById('search-input');
  if (searchInput) searchInput.addEventListener('input', debounce(handleSearch, 300));
  
  var statusFilter = document.getElementById('status-filter');
  if (statusFilter) statusFilter.addEventListener('change', handleFilterChange);
  
  var clearFilters = document.getElementById('clear-filters');
  if (clearFilters) clearFilters.addEventListener('click', clearFiltersHandler);
  
  var selectAll = document.getElementById('select-all');
  if (selectAll) selectAll.addEventListener('change', handleSelectAll);
  
  var batchBtn = document.getElementById('batch-delete-btn');
  if (batchBtn) batchBtn.addEventListener('click', showBatchDeleteConfirm);
  
  loadFiles();
}

function loadFiles() {
  var tbody = document.getElementById('files-table-body');
  var searchInput = document.getElementById('search-input');
  var statusFilter = document.getElementById('status-filter');
  
  var search = searchInput ? searchInput.value : '';
  var status = statusFilter ? statusFilter.value : '';
  
  var params = { page: currentPage, page_size: pageSize };
  if (search) params.search = search;
  if (status) params.status = status;
  
  getFiles(params).then(function(data) {
    totalItems = data.total || 0;
    renderFiles(data.files || []);
    renderPagination();
  }).catch(function(e) {
    console.error('加载文件列表失败:', e);
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--muted);">加载失败: ' + e.message + '</td></tr>';
  });
}

function renderFiles(files) {
  var tbody = document.getElementById('files-table-body');
  if (!tbody) return;
  
  if (!files || files.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--muted);">暂无数据</td></tr>';
    return;
  }
  
  var html = '';
  for (var i = 0; i < files.length; i++) {
    var f = files[i];
    html += '<tr data-id="' + f.id + '">' +
      '<td class="table-checkbox"><input type="checkbox" class="file-checkbox" value="' + f.id + '" data-file-id="' + f.file_id + '" data-status="' + f.upload_status + '" onchange="updateSelectedUI()"></td>' +
      '<td><a href="report.html?id=' + f.file_id + '">' + escapeHtml(f.original_filename || '未知文件') + '</a></td>' +
      '<td style="font-family: var(--font-mono);">' + formatDuration(f.duration) + '</td>' +
      '<td>' + (f.file_format || '-') + '</td>' +
      '<td>' + getStatusBadge(f.upload_status) + '</td>' +
      '<td style="font-family: var(--font-mono); font-size: 0.85rem;">' + formatDate(f.created_at) + '</td>' +
      '<td>' +
        '<button class="btn btn-ghost btn-sm" onclick="downloadFile(' + f.id + ')">下载</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="confirmDeleteFile(\'' + f.file_id + '\')">删除</button>' +
      '</td>' +
    '</tr>';
  }
  tbody.innerHTML = html;
}

function renderPagination() {
  var totalPages = Math.ceil(totalItems / pageSize) || 1;
  var pagination = document.getElementById('pagination');
  if (!pagination) return;
  
  var html = '';
  if (totalPages > 1) {
    html += '<button class="btn btn-ghost"' + (currentPage === 1 ? ' disabled' : '') + ' onclick="goToPage(' + (currentPage - 1) + ')">上一页</button>';
    html += '<span class="page-info">第 ' + currentPage + ' / ' + totalPages + ' 页</span>';
    html += '<button class="btn btn-ghost"' + (currentPage === totalPages ? ' disabled' : '') + ' onclick="goToPage(' + (currentPage + 1) + ')">下一页</button>';
  }
  pagination.innerHTML = html;
}

function goToPage(page) {
  currentPage = page;
  loadFiles();
}

function handleSearch(e) {
  currentPage = 1;
  loadFiles();
}

function handleFilterChange() {
  currentPage = 1;
  loadFiles();
}

function clearFiltersHandler() {
  var searchInput = document.getElementById('search-input');
  var statusFilter = document.getElementById('status-filter');
  if (searchInput) searchInput.value = '';
  if (statusFilter) statusFilter.value = '';
  currentPage = 1;
  loadFiles();
}

function handleSelectAll(e) {
  var checkboxes = document.querySelectorAll('.file-checkbox');
  for (var i = 0; i < checkboxes.length; i++) {
    checkboxes[i].checked = e.target.checked;
  }
  updateSelectedUI();
}

function updateSelectedUI() {
  var checked = document.querySelectorAll('.file-checkbox:checked');
  selectedIds = [];
  selectedFileIds = [];
  var completedFileIds = [];

  for (var i = 0; i < checked.length; i++) {
    selectedIds.push(parseInt(checked[i].value));
    selectedFileIds.push(checked[i].dataset.fileId);
    if (checked[i].dataset.status === 'completed') {
      completedFileIds.push(checked[i].dataset.fileId);
    }
  }

  var count = selectedIds.length;
  var btn = document.getElementById('batch-delete-btn');
  var countEl = document.getElementById('selected-count');
  if (btn) btn.style.display = count > 0 ? 'flex' : 'none';
  if (countEl) countEl.textContent = count;

  // 合并分析：选中 2 个及以上且全部已完成 ASR
  var mergeBtn = document.getElementById('merge-analyze-btn');
  var mergeCountEl = document.getElementById('merge-count');
  var mergeEligible = completedFileIds.length >= 2 && completedFileIds.length === count;
  if (mergeBtn) mergeBtn.style.display = mergeEligible ? 'flex' : 'none';
  if (mergeCountEl) mergeCountEl.textContent = completedFileIds.length;
}

function confirmDeleteFile(id) {
  if (!confirm('确定要删除这个文件吗？')) return;
  performDelete([id]);
}

async function performDelete(ids) {
  try {
    if (ids.length === 1) {
      await deleteFile(ids[0]);
    } else {
      await deleteFiles(ids);
    }
    showToast('删除成功', 'success');
  } catch (e) {
    showToast('删除失败：' + (e.message || e), 'error');
    return;
  }
  selectedIds = [];
  loadFiles();
}

async function downloadFile(id) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/admin/files/${id}/download`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert('下载失败: ' + (err.detail || res.status));
    return;
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  a.remove();
}

function showBatchDeleteConfirm() {
  if (selectedFileIds.length === 0) return;
  if (!confirm('确定要删除选中的 ' + selectedFileIds.length + ' 个文件吗？')) return;
  performDelete(selectedFileIds);
}

function formatDuration(seconds) {
  if (!seconds) return '0:00';
  var mins = Math.floor(seconds / 60);
  var secs = Math.floor(seconds % 60);
  return mins + ':' + (secs < 10 ? '0' : '') + secs;
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString('zh-CN');
}

function getStatusBadge(status) {
  var badges = {
    completed: '<span class="badge badge-success">完成</span>',
    pending: '<span class="badge badge-warning">待处理</span>',
    failed: '<span class="badge badge-danger">失败</span>',
    processing: '<span class="badge badge-info">处理中</span>'
  };
  return badges[status] || '<span class="badge badge-muted">' + (status || '未知') + '</span>';
}

function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function debounce(fn, delay) {
  var timer;
  return function() {
    var args = arguments;
    var context = this;
    clearTimeout(timer);
    timer = setTimeout(function() { fn.apply(context, args); }, delay);
  };
}

function showToast(message, type) {
  var container = document.getElementById('toast-container');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(function() { toast.remove(); }, 3000);
}

// ==================== 上传录音 Modal ====================

function showUploadModal() {
  var existing = document.getElementById('upload-modal');
  if (existing) existing.remove();

  var modal = document.createElement('div');
  modal.id = 'upload-modal';
  modal.className = 'modal-overlay';
  modal.innerHTML =
    '<div class="modal" style="max-width: 500px;">' +
      '<div class="modal-header">' +
        '<h3 class="modal-title">上传录音文件</h3>' +
        '<button class="btn btn-ghost btn-icon" onclick="closeUploadModal()">' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="modal-body">' +
        '<p style="color: var(--muted); margin-bottom: 16px; font-size: 0.9rem;">上传录音后自动完成 ASR 转写与智能分析，支持 iOS / PC 等设备。</p>' +
        '<div id="upload-drop-zone" class="upload-drop-zone" onclick="document.getElementById(\'upload-file-input\').click()" ondragover="event.preventDefault()" ondrop="handleUploadDrop(event)">' +
          '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--muted); margin-bottom: 12px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>' +
          '<p style="color: var(--muted);">点击选择或拖拽文件到此处</p>' +
          '<p style="color: var(--muted); font-size: 0.8rem; margin-top: 4px;">支持 .m4a .mp3 .wav .amr .3gp</p>' +
          '<input type="file" id="upload-file-input" accept=".m4a,.mp3,.wav,.amr,.3gp" style="display:none" onchange="handleUploadFileSelected(event)">' +
        '</div>' +
        '<div id="upload-file-info" style="display:none; margin-top: 12px; padding: 12px; background: var(--surface); border-radius: 8px;">' +
          '<div style="display: flex; align-items: center; gap: 8px;">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>' +
            '<span id="upload-file-name" style="font-size: 0.9rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"></span>' +
          '</div>' +
        '</div>' +
        '<div id="upload-task-types-area" style="margin-top: 16px;">' +
          '<div style="font-size: 0.85rem; font-weight: 600; color: var(--text); margin-bottom: 8px;">选择分析类型</div>' +
          '<div id="task-types-checkboxes" style="display: flex; flex-wrap: wrap; gap: 8px;">' +
            '<span style="font-size: 0.8rem; color: var(--muted);">加载中...</span>' +
          '</div>' +
        '</div>' +
        '<div id="upload-progress-area" style="display:none; margin-top: 12px;">' +
          '<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">' +
            '<span id="upload-status-text" style="font-size: 0.85rem; color: var(--muted);">上传中...</span>' +
            '<span id="upload-pct" style="font-size: 0.85rem; font-family: var(--font-mono);">0%</span>' +
          '</div>' +
          '<div style="height: 6px; background: var(--border); border-radius: 3px;">' +
            '<div id="upload-progress-bar" style="height: 100%; background: var(--accent); border-radius: 3px; width: 0%; transition: width 0.3s;"></div>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="modal-footer">' +
        '<button class="btn btn-ghost" onclick="closeUploadModal()">取消</button>' +
        '<button class="btn btn-primary" id="upload-submit-btn" onclick="doUpload()" disabled>开始上传</button>' +
      '</div>' +
    '</div>';

  document.body.appendChild(modal);
  requestAnimationFrame(function() { modal.classList.add('active'); });
  modal.addEventListener('click', function(e) { if (e.target === modal) closeUploadModal(); });

  // 异步加载任务类型列表
  loadTaskTypesForUpload();
}

function loadTaskTypesForUpload() {
  var container = document.getElementById('task-types-checkboxes');
  if (!container) return;

  apiRequest('/task-types').then(function(data) {
    var types = (data && data.task_types) || [];
    var active = types.filter(function(t) { return t.is_active !== false; });
    if (active.length === 0) {
      container.innerHTML = '<span style="font-size: 0.8rem; color: var(--muted);">暂无可用分析类型，请先在「分析类型」页面配置</span>';
      return;
    }
    // 按 default_rank 优先排序：rank 1/2/3 在前，0 在后
    active.sort(function(a, b) {
      var ra = a.default_rank > 0 ? a.default_rank : 999;
      var rb = b.default_rank > 0 ? b.default_rank : 999;
      return ra - rb;
    });
    container.innerHTML = active.map(function(t) {
      var checked = t.default_rank > 0 ? 'checked' : '';
      var rankLabel = t.default_rank > 0
        ? '<span style="font-size:0.68rem;background:var(--accent);color:#fff;padding:1px 5px;border-radius:6px;margin-left:4px;">默认' + ['①','②','③'][t.default_rank-1] + '</span>'
        : '';
      var borderColor = t.default_rank > 0 ? 'var(--accent)' : 'var(--border)';
      return '<label style="display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid ' + borderColor + ';border-radius:20px;cursor:pointer;font-size:0.85rem;background:var(--surface);">' +
        '<input type="checkbox" name="task_type_sel" value="' + t.name + '" ' + checked + ' style="width:14px;height:14px;">' +
        t.display_name + rankLabel +
      '</label>';
    }).join('');
  }).catch(function() {
    container.innerHTML = '<span style="font-size: 0.8rem; color: var(--muted);">加载失败</span>';
  });
}

function closeUploadModal() {
  var modal = document.getElementById('upload-modal');
  if (modal) modal.remove();
}

function handleUploadDrop(event) {
  event.preventDefault();
  var files = event.dataTransfer.files;
  if (files && files.length > 0) applyUploadFile(files[0]);
}

function handleUploadFileSelected(event) {
  if (event.target.files && event.target.files.length > 0) {
    applyUploadFile(event.target.files[0]);
  }
}

function applyUploadFile(file) {
  var info = document.getElementById('upload-file-info');
  var nameEl = document.getElementById('upload-file-name');
  var submitBtn = document.getElementById('upload-submit-btn');
  if (info) info.style.display = 'block';
  if (nameEl) nameEl.textContent = file.name + ' (' + formatFileSize(file.size) + ')';
  if (submitBtn) submitBtn.disabled = false;
  window._uploadPendingFile = file;
}

async function doUpload() {
  var file = window._uploadPendingFile;
  if (!file) return;

  // 收集勾选的任务类型
  var checkedBoxes = document.querySelectorAll('input[name="task_type_sel"]:checked');
  var selectedTaskTypes = Array.from(checkedBoxes).map(function(cb) { return cb.value; });
  if (selectedTaskTypes.length === 0) {
    showToast('请至少选择一种分析类型', 'error');
    return;
  }

  var submitBtn = document.getElementById('upload-submit-btn');
  var cancelBtn = document.querySelector('#upload-modal .modal-footer .btn-ghost');
  var progressArea = document.getElementById('upload-progress-area');
  var progressBar = document.getElementById('upload-progress-bar');
  var pctEl = document.getElementById('upload-pct');
  var statusText = document.getElementById('upload-status-text');

  if (submitBtn) submitBtn.disabled = true;
  if (cancelBtn) cancelBtn.disabled = true;
  if (progressArea) progressArea.style.display = 'block';

  try {
    await uploadAnalyze(file, function(pct) {
      if (progressBar) progressBar.style.width = Math.min(pct, 95) + '%';
      if (pctEl) pctEl.textContent = Math.min(pct, 95) + '%';
    }, selectedTaskTypes);

    if (progressBar) progressBar.style.width = '100%';
    if (pctEl) pctEl.textContent = '100%';
    if (statusText) statusText.textContent = 'ASR 转写与分析中，请稍候...';

    // 轮询等待服务端处理（ASR+LLM 耗时较长，uploadAnalyze 会等到完成才返回）
    if (progressBar) progressBar.style.width = '100%';
    if (statusText) statusText.textContent = '分析完成！';

    closeUploadModal();
    showToast('上传分析完成，报告已生成', 'success');
    loadFiles();
  } catch (e) {
    if (statusText) { statusText.textContent = '失败：' + e.message; statusText.style.color = 'var(--danger)'; }
    if (submitBtn) submitBtn.disabled = false;
    if (cancelBtn) cancelBtn.disabled = false;
    showToast('上传失败：' + e.message, 'error');
  }
}

// ==================== 合并分析 Dialog ====================

function showMergeConfirm() {
  var existing = document.getElementById('merge-modal');
  if (existing) existing.remove();

  var fileIds = selectedFileIds.slice();
  if (fileIds.length < 2) {
    showToast('请至少选择 2 个已完成的录音文件', 'warning');
    return;
  }

  // 获取选中文件的名称用于展示
  var checked = document.querySelectorAll('.file-checkbox:checked');
  var fileListHtml = '';
  for (var i = 0; i < checked.length; i++) {
    var row = checked[i].closest('tr');
    var name = row ? (row.querySelector('a') ? row.querySelector('a').textContent : '文件 ' + (i+1)) : '文件 ' + (i+1);
    fileListHtml += '<li style="padding: 4px 0; font-size: 0.9rem;">' + (i+1) + '. ' + escapeHtml(name) + '</li>';
  }

  var modal = document.createElement('div');
  modal.id = 'merge-modal';
  modal.className = 'modal-overlay';
  modal.innerHTML =
    '<div class="modal" style="max-width: 480px;">' +
      '<div class="modal-header">' +
        '<h3 class="modal-title">合并分析</h3>' +
        '<button class="btn btn-ghost btn-icon" onclick="closeMergeModal()">' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="modal-body">' +
        '<p style="color: var(--muted); margin-bottom: 12px; font-size: 0.9rem;">将以下 ' + fileIds.length + ' 段录音的转写文本按顺序合并，统一生成三份分析报告：</p>' +
        '<ul style="list-style: none; padding: 0; margin: 0 0 16px 0; background: var(--surface); border-radius: 8px; padding: 12px;">' +
          fileListHtml +
        '</ul>' +
        '<p style="font-size: 0.8rem; color: var(--muted);">注意：合并顺序与您勾选的顺序一致，请确认顺序正确后再提交。</p>' +
        '<div id="merge-progress-area" style="display:none; margin-top: 12px;">' +
          '<div style="display: flex; align-items: center; gap: 8px;">' +
            '<div class="loading-spinner" style="width:16px; height:16px; border-width: 2px;"></div>' +
            '<span style="font-size: 0.85rem; color: var(--muted);">正在合并分析，请稍候（约1-3分钟）...</span>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="modal-footer">' +
        '<button class="btn btn-ghost" id="merge-cancel-btn" onclick="closeMergeModal()">取消</button>' +
        '<button class="btn btn-primary" id="merge-submit-btn" onclick="doMergeAnalyze(' + JSON.stringify(fileIds) + ')">确认合并分析</button>' +
      '</div>' +
    '</div>';

  document.body.appendChild(modal);
  requestAnimationFrame(function() { modal.classList.add('active'); });
  modal.addEventListener('click', function(e) { if (e.target === modal) closeMergeModal(); });
}

function closeMergeModal() {
  var modal = document.getElementById('merge-modal');
  if (modal) modal.remove();
}

async function doMergeAnalyze(fileIds) {
  var submitBtn = document.getElementById('merge-submit-btn');
  var cancelBtn = document.getElementById('merge-cancel-btn');
  var progressArea = document.getElementById('merge-progress-area');

  if (submitBtn) submitBtn.disabled = true;
  if (cancelBtn) cancelBtn.disabled = true;
  if (progressArea) progressArea.style.display = 'block';

  try {
    var result = await mergeAnalyze(fileIds);
    closeMergeModal();
    showToast('合并分析完成，报告已生成', 'success');
    loadFiles();
    if (result && result.file_id) {
      setTimeout(function() {
        window.location.href = 'report.html?id=' + result.file_id;
      }, 800);
    }
  } catch (e) {
    if (submitBtn) submitBtn.disabled = false;
    if (cancelBtn) cancelBtn.disabled = false;
    if (progressArea) progressArea.style.display = 'none';
    showToast('合并分析失败：' + e.message, 'error');
  }
}
