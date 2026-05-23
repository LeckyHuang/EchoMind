// dashboard_page.js
function initPage() {
  var main = document.getElementById('main-content');
  if (!main) return;
  
  main.innerHTML = '<div class="stats-grid stagger" id="stats-grid">' +
    '<div class="stat-card">' +
      '<div class="stat-label">总录音数</div>' +
      '<div class="stat-value" id="stat-total">-</div>' +
    '</div>' +
    '<div class="stat-card">' +
      '<div class="stat-label">已完成</div>' +
      '<div class="stat-value" id="stat-completed">-</div>' +
    '</div>' +
    '<div class="stat-card">' +
      '<div class="stat-label">总时长</div>' +
      '<div class="stat-value" id="stat-duration">-<span class="stat-suffix">分钟</span></div>' +
    '</div>' +
    '<div class="stat-card">' +
      '<div class="stat-label">本月新增</div>' +
      '<div class="stat-value" id="stat-monthly">-</div>' +
    '</div>' +
  '</div>' +
  
  '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 24px;">' +
    '<div class="card fade-in" style="animation-delay: 0.32s;">' +
      '<div class="card-header">' +
        '<h3 class="card-title">最近录音</h3>' +
        '<a href="files.html" class="btn btn-ghost btn-sm">查看全部</a>' +
      '</div>' +
      '<div class="card-body" style="padding: 0;">' +
        '<div class="table-wrapper" style="box-shadow: none; border-radius: 0;">' +
          '<table>' +
            '<thead><tr><th>文件名</th><th>时长</th><th>状态</th></tr></thead>' +
            '<tbody id="recent-files">' +
              '<tr><td colspan="3" style="text-align: center; color: var(--muted);">加载中...</td></tr>' +
            '</tbody>' +
          '</table>' +
        '</div>' +
      '</div>' +
    '</div>' +
    
    '<div class="card fade-in" style="animation-delay: 0.4s;">' +
      '<div class="card-header">' +
        '<h3 class="card-title">最近报告</h3>' +
        '<a href="files.html" class="btn btn-ghost btn-sm">查看全部</a>' +
      '</div>' +
      '<div class="card-body" style="padding: 0;">' +
        '<div class="table-wrapper" style="box-shadow: none; border-radius: 0;">' +
          '<table>' +
            '<thead><tr><th>文件名</th><th>生成时间</th></tr></thead>' +
            '<tbody id="recent-reports">' +
              '<tr><td colspan="2" style="text-align: center; color: var(--muted);">暂无数据</td></tr>' +
            '</tbody>' +
          '</table>' +
        '</div>' +
      '</div>' +
    '</div>' +
  '</div>';
  
  loadDashboardData();
}

function loadDashboardData() {
  getDashboardStats().then(function(stats) {
    var el = document.getElementById('stat-total');
    if (el) el.textContent = stats.total_files || 0;
    
    el = document.getElementById('stat-completed');
    if (el) el.textContent = stats.completed_files || 0;
    
    el = document.getElementById('stat-duration');
    if (el) el.innerHTML = Math.round((stats.total_duration_seconds || 0) / 60) + '<span class="stat-suffix">分钟</span>';
    
    el = document.getElementById('stat-monthly');
    if (el) el.textContent = stats.monthly_new_files || 0;
  }).catch(function(e) {
    console.error('加载统计数据失败:', e);
  });
  
  getFiles({ limit: 5 }).then(function(data) {
    var tbody = document.getElementById('recent-files');
    if (tbody && data.files && data.files.length > 0) {
      var html = '';
      for (var i = 0; i < data.files.length; i++) {
        var f = data.files[i];
        html += '<tr>' +
          '<td><a href="report.html?id=' + f.id + '">' + escapeHtml(f.original_filename || '未知文件') + '</a></td>' +
          '<td style="font-family: var(--font-mono);">' + formatDuration(f.duration) + '</td>' +
          '<td>' + getStatusBadge(f.upload_status) + '</td>' +
        '</tr>';
      }
      tbody.innerHTML = html;
    }
  }).catch(function(e) {
    console.error('加载录音列表失败:', e);
  });
}

function formatDuration(seconds) {
  if (!seconds) return '0:00';
  var mins = Math.floor(seconds / 60);
  var secs = Math.floor(seconds % 60);
  return mins + ':' + (secs < 10 ? '0' : '') + secs;
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
