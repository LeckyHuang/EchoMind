const API_BASE = 'http://183.56.228.31:8001/api/v1';

// ========================================
// Auth
// ========================================

async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '登录失败' }));
    throw new Error(err.detail || '登录失败');
  }
  
  const data = await res.json();
  localStorage.setItem('token', data.access_token);
  localStorage.setItem('user', JSON.stringify(data.user));
  return data;
}

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  window.location.href = 'login.html';
}

function getCurrentUser() {
  const user = localStorage.getItem('user');
  return user ? JSON.parse(user) : null;
}

function getToken() {
  return localStorage.getItem('token');
}

function requireAuth() {
  if (!getToken()) {
    window.location.href = 'login.html';
    return false;
  }
  return true;
}

// ========================================
// API Helper
// ========================================

async function apiRequest(endpoint, options = {}) {
  const token = getToken();
  
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...options.headers
    },
    ...options
  };
  
  // Remove Content-Type for FormData
  if (options.body instanceof FormData) {
    delete config.headers['Content-Type'];
  }
  
  const res = await fetch(`${API_BASE}${endpoint}`, config);
  
  if (res.status === 401) {
    logout();
    throw new Error('登录已过期，请重新登录');
  }
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || '请求失败');
  }
  
  return res.json();
}

// ========================================
// Stats
// ========================================

async function getStats() {
  return apiRequest('/admin/stats');
}

async function getDashboardStats() {
  return apiRequest('/admin/dashboard/stats');
}

// ========================================
// Files
// ========================================

async function getFiles(params = {}) {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/admin/files${query ? '?' + query : ''}`);
}

async function getFile(fileId) {
  return apiRequest(`/admin/files/${fileId}`);
}

async function deleteFile(fileId) {
  return apiRequest(`/admin/files/${fileId}`, { method: 'DELETE' });
}

async function deleteFiles(fileIds) {
  return apiRequest('/admin/files/batch-delete', {
    method: 'POST',
    body: JSON.stringify(fileIds)
  });
}

async function uploadAnalyze(file, onProgress, taskTypes) {
  const token = getToken();
  const formData = new FormData();
  formData.append('file', file);
  if (taskTypes && taskTypes.length > 0) {
    formData.append('task_types', taskTypes.join(','));
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/admin/files/upload-analyze`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    if (onProgress) {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      });
    }

    xhr.onload = () => {
      if (xhr.status === 401) { logout(); return reject(new Error('登录已过期')); }
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 400) return reject(new Error(data.detail || '上传失败'));
        resolve(data);
      } catch { reject(new Error('响应解析失败')); }
    };
    xhr.onerror = () => reject(new Error('网络错误'));
    xhr.send(formData);
  });
}

async function mergeAnalyze(fileIds) {
  return apiRequest('/admin/analyze/merge', {
    method: 'POST',
    body: JSON.stringify({ file_ids: fileIds })
  });
}

async function downloadFile(fileId) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/admin/files/${fileId}/download`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  
  if (!res.ok) throw new Error('下载失败');
  
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}

// ========================================
// Reports
// ========================================

async function getReports(params = {}) {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/admin/reports${query ? '?' + query : ''}`);
}

async function getReport(reportId) {
  return apiRequest(`/admin/reports/${reportId}`);
}

async function getRecentReports(limit = 5) {
  return apiRequest(`/admin/reports/recent?limit=${limit}`);
}

// ========================================
// Prompts
// ========================================

async function getPrompts() {
  return apiRequest('/admin/prompts');
}

async function getPrompt(promptId) {
  return apiRequest(`/admin/prompts/${promptId}`);
}

async function createPrompt(data) {
  return apiRequest('/admin/prompts', {
    method: 'POST',
    body: JSON.stringify(data)
  });
}

async function updatePrompt(promptId, data) {
  return apiRequest(`/admin/prompts/${promptId}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  });
}

async function deletePrompt(promptId) {
  return apiRequest(`/admin/prompts/${promptId}`, { method: 'DELETE' });
}

async function togglePromptActive(promptId, isActive) {
  return apiRequest(`/admin/prompts/${promptId}/toggle`, {
    method: 'POST',
    body: JSON.stringify({ is_active: isActive })
  });
}

async function previewPrompt(promptId, variables = {}) {
  return apiRequest(`/admin/prompts/${promptId}/preview`, {
    method: 'POST',
    body: JSON.stringify({ variables })
  });
}

// ========================================
// Users
// ========================================

async function getUsers() {
  return apiRequest('/admin/users');
}

async function getUser(userId) {
  return apiRequest(`/admin/users/${userId}`);
}

async function createUser(data) {
  return apiRequest('/admin/users', {
    method: 'POST',
    body: JSON.stringify(data)
  });
}

async function updateUser(userId, data) {
  return apiRequest(`/admin/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(data)
  });
}

async function deleteUser(userId) {
  return apiRequest(`/admin/users/${userId}`, { method: 'DELETE' });
}

async function resetUserPassword(userId) {
  return apiRequest(`/admin/users/${userId}/reset-password`, {
    method: 'POST'
  });
}

async function deleteUserApi(userId) {
  return apiRequest(`/admin/users/${userId}`, { method: 'DELETE' });
}

async function toggleUserStatus(userId, isActive) {
  return apiRequest(`/admin/users/${userId}/toggle-status`, {
    method: 'POST',
    body: JSON.stringify({ is_active: isActive })
  });
}

// ========================================
// Settings
// ========================================

async function getSettings() {
  return apiRequest('/admin/settings');
}

async function updateSettings(data) {
  return apiRequest('/admin/settings', {
    method: 'PUT',
    body: JSON.stringify(data)
  });
}

async function getServiceProviders() {
  return apiRequest('/admin/settings/providers');
}

// ========================================
// Toast Helper
// ========================================

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container') || createToastContainer();
  
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  const iconSvg = type === 'success' 
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
    : type === 'error'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
  
  toast.innerHTML = `
    <span class="toast-icon">${iconSvg}</span>
    <span class="toast-message">${message}</span>
  `;
  
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function createToastContainer() {
  const container = document.createElement('div');
  container.id = 'toast-container';
  container.className = 'toast-container';
  document.body.appendChild(container);
  return container;
}

// ========================================
// Format Helpers
// ========================================

function formatDuration(seconds) {
  if (!seconds) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function formatFileSize(bytes) {
  if (!bytes) return '-';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024;
    i++;
  }
  return `${bytes.toFixed(1)} ${units[i]}`;
}
