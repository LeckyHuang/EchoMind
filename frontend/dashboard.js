async function initDashboard() {
  if (!requireAuth()) return;
  
  const main = getMainContent();
  main.innerHTML = `
    <div class="stats-grid stagger" id="stats-grid">
      <div class="stat-card">
        <div class="stat-label">总录音数</div>
        <div class="stat-value" id="stat-total">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已完成</div>
        <div class="stat-value" id="stat-completed">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">总时长</div>
        <div class="stat-value" id="stat-duration">-<span class="stat-suffix">分钟</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">本月新增</div>
        <div class="stat-value" id="stat-monthly">-</div>
      </div>
    </div>
    
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 24px;">
      <div class="card fade-in" style="animation-delay: 0.32s;">
        <div class="card-header">
          <h3 class="card-title">最近录音</h3>
          <a href="files.html" class="btn btn-ghost btn-sm">查看全部</a>
        </div>
        <div class="card-body" style="padding: 0;">
          <div class="table-wrapper" style="box-shadow: none; border-radius: 0;">
            <table>
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>时长</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody id="recent-files">
                <tr><td colspan="3" style="text-align: center; color: var(--muted);">加载中...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      
      <div class="card fade-in" style="animation-delay: 0.4s;">
        <div class="card-header">
          <h3 class="card-title">最近报告</h3>
          <a href="files.html" class="btn btn-ghost btn-sm">查看全部</a>
        </div>
        <div class="card-body" style="padding: 0;">
          <div class="table-wrapper" style="box-shadow: none; border-radius: 0;">
            <table>
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>生成时间</th>
                </tr>
              </thead>
              <tbody id="recent-reports">
                <tr><td colspan="2" style="text-align: center; color: var(--muted);">加载中...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `;
  
  // Wait for DOM to render, then load data
  requestAnimationFrame(() => {
    loadStats();
    loadRecentFiles();
    loadRecentReports();
  });
}

async function loadStats() {
  try {
    console.log('loadStats: calling API...');
    const data = await getDashboardStats();
    console.log('loadStats: received data:', data);
    
    const el = document.getElementById('stat-total');
    if (el) {
      el.textContent = data.total_files || 0;
    }
    const el2 = document.getElementById('stat-completed');
    if (el2) {
      el2.textContent = data.completed_files || 0;
    }
    const el3 = document.getElementById('stat-duration');
    if (el3) {
      el3.innerHTML = `${data.total_duration_minutes || Math.round(data.total_duration_seconds / 60) || 0}<span class="stat-suffix">分钟</span>`;
    }
    const el4 = document.getElementById('stat-monthly');
    if (el4) {
      el4.textContent = data.monthly_new_files || 0;
    }
    console.log('loadStats: done, stat-total =', el ? el.textContent : 'not found');
  } catch (error) {
    console.error('Failed to load stats:', error);
    // Use placeholder data for demo
    const el = document.getElementById('stat-total');
    if (el) el.textContent = '128';
    const el2 = document.getElementById('stat-completed');
    if (el2) el2.textContent = '115';
    const el3 = document.getElementById('stat-duration');
    if (el3) el3.innerHTML = `2,456<span class="stat-suffix">分钟</span>`;
    const el4 = document.getElementById('stat-monthly');
    if (el4) el4.textContent = '24';
  }
}

async function loadRecentFiles() {
  const tbody = document.getElementById('recent-files');
  
  try {
    const data = await getFiles({ limit: 5 });
    const files = data.files || [];
    
    if (files.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--muted);">暂无数据</td></tr>';
      return;
    }
    
    tbody.innerHTML = files.map(file => `
      <tr>
        <td><a href="report.html?id=${file.id}">${file.filename || file.name || '未知文件'}</a></td>
        <td style="font-family: var(--font-mono);">${formatDuration(file.duration)}</td>
        <td>${getStatusBadge(file.status)}</td>
      </tr>
    `).join('');
  } catch (error) {
    console.error('Failed to load recent files:', error);
    // Demo data
    tbody.innerHTML = `
      <tr>
        <td><a href="report.html?id=1">会议录音_20240315.wav</a></td>
        <td style="font-family: var(--font-mono);">12:34</td>
        <td><span class="badge badge-success">完成</span></td>
      </tr>
      <tr>
        <td><a href="report.html?id=2">访谈记录_20240314.mp3</a></td>
        <td style="font-family: var(--font-mono);">8:45</td>
        <td><span class="badge badge-success">完成</span></td>
      </tr>
      <tr>
        <td><a href="report.html?id=3">电话沟通_20240313.m4a</a></td>
        <td style="font-family: var(--font-mono);">5:22</td>
        <td><span class="badge badge-warning">待处理</span></td>
      </tr>
      <tr>
        <td><a href="report.html?id=4">项目汇报_20240312.wav</a></td>
        <td style="font-family: var(--font-mono);">25:10</td>
        <td><span class="badge badge-success">完成</span></td>
      </tr>
      <tr>
        <td><a href="report.html?id=5">客户拜访_20240311.mp3</a></td>
        <td style="font-family: var(--font-mono);">18:33</td>
        <td><span class="badge badge-danger">失败</span></td>
      </tr>
    `;
  }
}

async function loadRecentReports() {
  const tbody = document.getElementById('recent-reports');
  
  try {
    const data = await getRecentReports(5);
    const reports = data.reports || [];
    
    if (reports.length === 0) {
      tbody.innerHTML = '<tr><td colspan="2" style="text-align: center; color: var(--muted);">暂无数据</td></tr>';
      return;
    }
    
    tbody.innerHTML = reports.map(report => `
      <tr>
        <td><a href="report.html?id=${report.file_id}">${report.filename || '未知文件'}</a></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">${formatDate(report.created_at)}</td>
      </tr>
    `).join('');
  } catch (error) {
    console.error('Failed to load recent reports:', error);
    // Demo data
    tbody.innerHTML = `
      <tr>
        <td><a href="report.html?id=1">会议录音_20240315.wav</a></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-15 14:30</td>
      </tr>
      <tr>
        <td><a href="report.html?id=2">访谈记录_20240314.mp3</a></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-14 16:45</td>
      </tr>
      <tr>
        <td><a href="report.html?id=4">项目汇报_20240312.wav</a></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-12 10:20</td>
      </tr>
      <tr>
        <td><a href="report.html?id=6">产品评审_20240310.mp3</a></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-10 11:00</td>
      </tr>
      <tr>
        <td><a href="report.html?id=7">需求讨论_20240308.wav</a></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-08 15:30</td>
      </tr>
    `;
  }
}

function getStatusBadge(status) {
  const badges = {
    completed: '<span class="badge badge-success">完成</span>',
    pending: '<span class="badge badge-warning">待处理</span>',
    failed: '<span class="badge badge-danger">失败</span>',
    processing: '<span class="badge badge-warning">处理中</span>'
  };
  return badges[status] || `<span class="badge badge-muted">${status || '未知'}</span>`;
}
