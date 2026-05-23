// reports.js - 分析报告页面
var currentPage = 1;
var pageSize = 10;
var totalItems = 0;
var selectedIds = [];

function initPage() {
  var main = document.getElementById('main-content');
  if (!main) return;
  
  main.innerHTML = '<div class="page-header">' +
    '<h1 class="page-title">分析报告</h1>' +
  '</div>' +
  
  '<div class="filters-bar">' +
    '<input type="text" class="form-input" id="search-input" placeholder="搜索文件名...">' +
    '<button class="btn btn-ghost" id="clear-filters">清除筛选</button>' +
  '</div>' +
  
  '<div class="table-wrapper">' +
    '<table>' +
      '<thead>' +
        '<tr>' +
          '<th>文件名</th>' +
          '<th>生成时间</th>' +
          '<th>操作</th>' +
        '</tr>' +
      '</thead>' +
      '<tbody id="reports-table-body">' +
        '<tr><td colspan="3" style="text-align: center; padding: 40px; color: var(--muted);">加载中...</td></tr>' +
      '</tbody>' +
    '</table>' +
  '</div>' +
  
  '<div class="pagination" id="pagination"></div>';
  
  var searchInput = document.getElementById('search-input');
  if (searchInput) searchInput.addEventListener('input', debounce(handleSearch, 300));
  
  var clearBtn = document.getElementById('clear-filters');
  if (clearBtn) clearBtn.addEventListener('click', clearFilters);
  
  loadReports();
}

function loadReports() {
  var tbody = document.getElementById('reports-table-body');
  var searchInput = document.getElementById('search-input');
  var search = searchInput ? searchInput.value : '';
  
  var params = { page: currentPage, page_size: pageSize };
  if (search) params.search = search;
  
  getFiles(params).then(function(data) {
    // Filter files that have reports (completed ones)
    var files = (data.files || []).filter(function(f) {
      return f.upload_status === 'completed';
    });
    
    totalItems = files.length;
    renderReports(files);
    renderPagination();
  }).catch(function(e) {
    console.error('加载报告列表失败:', e);
    if (tbody) tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--muted);">加载失败: ' + e.message + '</td></tr>';
  });
}

function renderReports(files) {
  var tbody = document.getElementById('reports-table-body');
  if (!tbody) return;
  
  if (!files || files.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--muted);">暂无数据</td></tr>';
    return;
  }
  
  var html = '';
  for (var i = 0; i < files.length; i++) {
    var f = files[i];
    html += '<tr>' +
      '<td>' + escapeHtml(f.original_filename || '未知文件') + '</td>' +
      '<td style="font-family: var(--font-mono); font-size: 0.85rem;">' + formatDate(f.created_at) + '</td>' +
      '<td><button class="btn btn-ghost btn-sm" onclick="viewReport(' + f.id + ')">查看报告</button></td>' +
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
  loadReports();
}

function handleSearch() {
  currentPage = 1;
  loadReports();
}

function clearFilters() {
  var searchInput = document.getElementById('search-input');
  if (searchInput) searchInput.value = '';
  currentPage = 1;
  loadReports();
}

function viewReport(id) {
  window.location.href = 'report.html?id=' + id;
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString('zh-CN');
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
