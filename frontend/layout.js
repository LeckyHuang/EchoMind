// ========================================
// Layout Builder
// ========================================

const NAV_ITEMS = [
  { id: 'dashboard', label: '仪表盘', icon: 'dashboard', href: 'dashboard.html' },
  { id: 'files', label: '录音文件', icon: 'files', href: 'files.html' },
  { id: 'reports', label: '分析报告', icon: 'reports', href: 'reports.html' },
  { id: 'task-types', label: '分析类型', icon: 'tasktypes', href: 'task-types.html', adminOnly: true },
  { id: 'users', label: '用户管理', icon: 'users', href: 'users.html', adminOnly: true },
  { id: 'settings', label: '系统设置', icon: 'settings', href: 'settings.html', adminOnly: true }
];

const ICONS = {
  dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>',
  files: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  reports: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/></svg>',
  tasktypes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 10h8M8 14h5"/></svg>',
  prompts: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  logout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
  menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
  logo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>'
};

// Layout callback
var layoutCallback = null;
var layoutBuilt = false;

window.waitForLayout = function(callback) {
  if (layoutBuilt) {
    setTimeout(callback, 0);
  } else {
    layoutCallback = callback;
  }
};

function getCurrentPageId() {
  var path = window.location.pathname;
  var filename = path.substring(path.lastIndexOf('/') + 1) || 'dashboard.html';
  return filename.replace('.html', '');
}

function getNavMatch(item) {
  var current = getCurrentPageId();
  return item.id === current;
}

function getPageTitle(pageId) {
  var titles = {
    dashboard: '仪表盘',
    files: '录音文件',
    reports: '分析报告',
    'task-types': '分析类型',
    prompts: 'Prompt管理',
    users: '用户管理',
    settings: '系统设置'
  };
  return titles[pageId] || '仪表盘';
}

function getUserAvatar(user) {
  if (!user || !user.username) return 'A';
  return user.username.charAt(0).toUpperCase();
}

function getMainContent() {
  return document.getElementById('main-content');
}

function setPageTitle(title) {
  var titleEl = document.getElementById('page-title');
  if (titleEl) titleEl.textContent = title;
}

function buildLayout() {
  if (!requireAuth()) return false;
  
  var user = getCurrentUser();
  var currentPage = getCurrentPageId();

  // 普通用户只显示非 adminOnly 菜单
  var visibleNav = NAV_ITEMS;
  if (user && user.role !== 'admin') {
    visibleNav = NAV_ITEMS.filter(function(item) { return !item.adminOnly; });
  }

  var layoutHtml = '<div class="app-layout">' +
    '<aside class="sidebar" id="sidebar">' +
      '<div class="sidebar-logo">' +
        ICONS.logo +
        '<span>EchoMind</span>' +
      '</div>' +
      '<nav class="sidebar-nav">';

  for (var i = 0; i < visibleNav.length; i++) {
    var item = visibleNav[i];
    var isActive = getNavMatch(item) ? 'active' : '';
    layoutHtml += '<a href="' + item.href + '" class="nav-item ' + isActive + '" data-page="' + item.id + '">' +
      ICONS[item.icon] +
      '<span>' + item.label + '</span>' +
    '</a>';
  }
  
  layoutHtml += '</nav>' +
      '<div style="padding: 16px 24px; border-top: 1px solid var(--border);">' +
        '<button class="btn btn-ghost" style="width: 100%; justify-content: flex-start;" onclick="logout()">' +
          ICONS.logout +
          '<span>退出登录</span>' +
        '</button>' +
      '</div>' +
    '</aside>' +
    
    '<header class="topbar">' +
      '<div class="topbar-left">' +
        '<button class="btn btn-ghost mobile-menu-btn" id="mobile-menu-btn" style="display: none;">' +
          ICONS.menu +
        '</button>' +
        '<h1 class="topbar-title" id="page-title">' + getPageTitle(currentPage) + '</h1>' +
      '</div>' +
      '<div class="topbar-right">' +
        '<div class="user-info">' +
          '<div class="user-avatar">' + getUserAvatar(user) + '</div>' +
          '<span>' + (user && user.username ? user.username : '管理员') + '</span>' +
        '</div>' +
      '</div>' +
    '</header>' +
    
    '<main class="main-content" id="main-content">' +
      '<!-- Content will be injected here -->' +
    '</main>' +
  '</div>';
  
  document.body.innerHTML = layoutHtml;
  
  // Hide loading
  var loading = document.getElementById('loading');
  if (loading) loading.style.display = 'none';
  
  // Mobile menu toggle
  var mobileBtn = document.getElementById('mobile-menu-btn');
  var sidebar = document.getElementById('sidebar');
  if (mobileBtn && sidebar) {
    mobileBtn.addEventListener('click', function() {
      sidebar.classList.toggle('open');
    });
  }
  
  layoutBuilt = true;
  if (layoutCallback) {
    layoutCallback();
  }
}

function initLayout() {
  buildLayout();
  
  // Load page-specific script if exists
  var pageId = getCurrentPageId();
  var scriptMap = {
    'dashboard': 'dashboard_page.js',
    'files': 'files.js',
    'reports': 'reports.js',
    'task-types': 'task-types.js',
    'prompts': 'prompts.js',
    'users': 'users.js',
    'settings': 'settings.js'
  };
  
  if (scriptMap[pageId]) {
    var script = document.createElement('script');
    script.src = scriptMap[pageId];
    script.onload = function() {
      if (typeof initPage === 'function') {
        initPage();
      }
    };
    document.body.appendChild(script);
  }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initLayout);
} else {
  initLayout();
}

// Alias for compatibility
window.whenLayoutReady = window.waitForLayout;
