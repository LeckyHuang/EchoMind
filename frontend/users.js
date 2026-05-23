async function initUsers() {
  if (!requireAuth()) return;
  
  setPageTitle('用户管理');
  
  const main = getMainContent();
  main.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">用户管理</h1>
      <div class="page-actions">
        <button class="btn btn-primary" id="new-user-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="8.5" cy="7" r="4"/>
            <line x1="20" y1="8" x2="20" y2="14"/>
            <line x1="23" y1="11" x2="17" y2="11"/>
          </svg>
          <span>新建用户</span>
        </button>
      </div>
    </div>
    
    <div class="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>用户名</th>
            <th>邮箱</th>
            <th>角色</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="users-table-body">
          <tr><td colspan="6" style="text-align: center; padding: 40px; color: var(--muted);">加载中...</td></tr>
        </tbody>
      </table>
    </div>
  `;
  
  
  // New user button
  document.getElementById('new-user-btn').addEventListener('click', () => {
    showUserModal();
  });
  
  // Load users
  loadUsers();
});

async function loadUsers() {
  const tbody = document.getElementById('users-table-body');
  const currentUser = getCurrentUser();
  
  try {
    const data = await getUsers();
    const users = data.users || [];
    
    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><p>暂无用户</p></td></tr>';
      return;
    }
    
    tbody.innerHTML = users.map(user => {
      const isSelf = user.id === currentUser?.id;
      return `
        <tr data-id="${user.id}">
          <td>${user.username}</td>
          <td>${user.email || '-'}</td>
          <td>${getRoleBadge(user.role)}</td>
          <td>${getStatusBadge(user.is_active !== false)}</td>
          <td style="font-family: var(--font-mono); font-size: 0.85rem;">${formatDate(user.created_at)}</td>
          <td>
            <div class="table-actions">
              <button class="btn btn-ghost btn-sm" onclick="resetUserPassword(${user.id})" title="重置密码">重置密码</button>
              <button class="btn btn-ghost btn-sm" onclick="toggleUserStatusHandler(${user.id}, ${user.is_active !== false})" title="${user.is_active !== false ? '禁用' : '启用'}">
                ${user.is_active !== false ? '禁用' : '启用'}
              </button>
              ${!isSelf ? `<button class="btn btn-ghost btn-sm" style="color: var(--danger);" onclick="deleteUserHandler(${user.id}, '${escapeHtml(user.username)}')">删除</button>` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');
    
  } catch (error) {
    console.error('Failed to load users:', error);
    showToast(error.message || '加载失败', 'error');
    // Demo data
    tbody.innerHTML = `
      <tr data-id="1">
        <td>admin</td>
        <td>admin@example.com</td>
        <td><span class="badge badge-accent">管理员</span></td>
        <td><span class="badge badge-success">正常</span></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-01-01 10:00</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-ghost btn-sm" onclick="resetUserPassword(1)">重置密码</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleUserStatusHandler(1, true)">禁用</button>
          </div>
        </td>
      </tr>
      <tr data-id="2">
        <td>zhangsan</td>
        <td>zhangsan@example.com</td>
        <td><span class="badge badge-muted">用户</span></td>
        <td><span class="badge badge-success">正常</span></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-02-15 14:30</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-ghost btn-sm" onclick="resetUserPassword(2)">重置密码</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleUserStatusHandler(2, true)">禁用</button>
            <button class="btn btn-ghost btn-sm" style="color: var(--danger);" onclick="deleteUserHandler(2, 'zhangsan')">删除</button>
          </div>
        </td>
      </tr>
      <tr data-id="3">
        <td>lisi</td>
        <td>lisi@example.com</td>
        <td><span class="badge badge-muted">用户</span></td>
        <td><span class="badge badge-danger">已禁用</span></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-01 09:15</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-ghost btn-sm" onclick="resetUserPassword(3)">重置密码</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleUserStatusHandler(3, false)">启用</button>
            <button class="btn btn-ghost btn-sm" style="color: var(--danger);" onclick="deleteUserHandler(3, 'lisi')">删除</button>
          </div>
        </td>
      </tr>
      <tr data-id="4">
        <td>wangwu</td>
        <td>wangwu@example.com</td>
        <td><span class="badge badge-warning">操作员</span></td>
        <td><span class="badge badge-success">正常</span></td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">2024-03-10 16:45</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-ghost btn-sm" onclick="resetUserPassword(4)">重置密码</button>
            <button class="btn btn-ghost btn-sm" onclick="toggleUserStatusHandler(4, true)">禁用</button>
            <button class="btn btn-ghost btn-sm" style="color: var(--danger);" onclick="deleteUserHandler(4, 'wangwu')">删除</button>
          </div>
        </td>
      </tr>
    `;
  }
}

// Modal state
let editingUserId = null;

function showUserModal(user = null) {
  editingUserId = user?.id || null;
  
  const modal = createModal(user ? '编辑用户' : '新建用户', `
    <div class="form-group">
      <label class="form-label" for="user-username">用户名</label>
      <input type="text" id="user-username" class="form-input" placeholder="输入用户名" value="${user?.username || ''}" ${user ? 'readonly' : ''}>
    </div>
    
    <div class="form-group">
      <label class="form-label" for="user-email">邮箱</label>
      <input type="email" id="user-email" class="form-input" placeholder="输入邮箱地址" value="${user?.email || ''}">
    </div>
    
    <div class="form-group">
      <label class="form-label" for="user-password">密码 ${user ? '（留空则不修改）' : ''}</label>
      <input type="password" id="user-password" class="form-input" placeholder="${user ? '输入新密码' : '输入密码'}" ${!user ? 'required' : ''}>
    </div>
    
    <div class="form-group">
      <label class="form-label" for="user-role">角色</label>
      <select id="user-role" class="form-select">
        <option value="user" ${user?.role === 'user' ? 'selected' : ''}>用户</option>
        <option value="operator" ${user?.role === 'operator' ? 'selected' : ''}>操作员</option>
        <option value="admin" ${user?.role === 'admin' ? 'selected' : ''}>管理员</option>
      </select>
    </div>
  `, [
    { text: '取消', class: 'btn-secondary', action: 'close' },
    { text: user ? '保存' : '创建', class: 'btn-primary', action: saveUser }
  ]);
  
  document.body.appendChild(modal);
  setTimeout(() => modal.classList.add('active'), 10);
}

async function saveUser() {
  const username = document.getElementById('user-username').value.trim();
  const email = document.getElementById('user-email').value.trim();
  const password = document.getElementById('user-password').value;
  const role = document.getElementById('user-role').value;
  
  if (!username) {
    showToast('请输入用户名', 'warning');
    return;
  }
  
  if (!editingUserId && !password) {
    showToast('请输入密码', 'warning');
    return;
  }
  
  try {
    const data = { username, email, role };
    if (password) {
      data.password = password;
    }
    
    if (editingUserId) {
      await updateUser(editingUserId, data);
      showToast('用户更新成功', 'success');
    } else {
      await createUser(data);
      showToast('用户创建成功', 'success');
    }
    
    closeModal();
    loadUsers();
  } catch (error) {
    showToast(error.message || '保存失败', 'error');
  }
}

async function resetUserPassword(userId) {
  const modal = createModal('重置密码', `
    <p style="margin-bottom: 16px;">确定要重置该用户的密码吗？</p>
    <p style="color: var(--warning); font-size: 0.85rem;">重置后密码将恢复为默认密码，请告知用户。</p>
  `, [
    { text: '取消', class: 'btn-secondary', action: 'close' },
    { text: '重置', class: 'btn-primary', action: () => confirmResetPassword(userId) }
  ]);
  document.body.appendChild(modal);
  setTimeout(() => modal.classList.add('active'), 10);
}

async function confirmResetPassword(userId) {
  try {
    const result = await resetUserPassword(userId);
    showToast('密码已重置', 'success');
    if (result?.password) {
      showToast(`新密码: ${result.password}`, 'warning');
    }
    closeModal();
  } catch (error) {
    showToast(error.message || '重置失败', 'error');
    closeModal();
  }
}

async function toggleUserStatusHandler(userId, isActive) {
  try {
    await toggleUserStatus(userId, isActive);
    showToast(isActive ? '用户已启用' : '用户已禁用', 'success');
    loadUsers();
  } catch (error) {
    showToast(error.message || '操作失败', 'error');
  }
}

function deleteUserHandler(userId, username) {
  const modal = createModal('删除用户', `
    <p style="margin-bottom: 16px;">确定要删除用户 <strong>${username}</strong> 吗？</p>
    <p style="color: var(--danger); font-size: 0.85rem;">此操作不可恢复，该用户的所有数据将被删除。</p>
  `, [
    { text: '取消', class: 'btn-secondary', action: 'close' },
    { text: '删除', class: 'btn-danger', action: () => confirmDeleteUser(userId) }
  ]);
  document.body.appendChild(modal);
  setTimeout(() => modal.classList.add('active'), 10);
}

async function confirmDeleteUser(userId) {
  try {
    await deleteUser(userId);
    showToast('用户删除成功', 'success');
    closeModal();
    loadUsers();
  } catch (error) {
    showToast(error.message || '删除失败', 'error');
    closeModal();
  }
}

// Helpers
function getRoleBadge(role) {
  const badges = {
    admin: '<span class="badge badge-accent">管理员</span>',
    operator: '<span class="badge badge-warning">操作员</span>',
    user: '<span class="badge badge-muted">用户</span>'
  };
  return badges[role] || `<span class="badge badge-muted">${role || '未知'}</span>`;
}

function getStatusBadge(isActive) {
  return isActive 
    ? '<span class="badge badge-success">正常</span>'
    : '<span class="badge badge-danger">已禁用</span>';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Modal helpers
function createModal(title, content, buttons) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <h3 class="modal-title">${title}</h3>
        <button class="modal-close" onclick="closeModal()">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
      <div class="modal-body">${content}</div>
      <div class="modal-footer" id="modal-footer"></div>
    </div>
  `;
  
  const footer = modal.querySelector('#modal-footer');
  buttons.forEach(btn => {
    const button = document.createElement('button');
    button.className = `btn ${btn.class}`;
    button.textContent = btn.text;
    button.onclick = () => {
      if (btn.action === 'close') {
        closeModal();
      } else {
        btn.action();
      }
    };
    footer.appendChild(button);
  });
  
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });
  
  return modal;
}

function closeModal() {
  const modal = document.querySelector('.modal-overlay.active');
  if (modal) {
    modal.classList.remove('active');
    setTimeout(() => modal.remove(), 200);
  }
}

window.closeModal = closeModal;
