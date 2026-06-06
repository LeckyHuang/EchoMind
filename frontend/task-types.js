// task-types.js — 分析类型管理页面（两 Tab：我的类型 + 类型库）

var _allInstalledTypes = [];   // 已安装类型缓存
var _activeTab = 'mine';       // 当前 tab

function initPage() {
  var main = document.getElementById('main-content');
  if (!main) return;

  main.innerHTML =
    '<div class="page-header">' +
      '<h1 class="page-title">分析类型</h1>' +
    '</div>' +

    // Tab 切换
    '<div style="display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:24px;">' +
      '<button id="tab-mine" class="tab-btn tab-active" onclick="switchTab(\'mine\')">我的类型</button>' +
      '<button id="tab-library" class="tab-btn" onclick="switchTab(\'library\')">类型库</button>' +
    '</div>' +

    // 我的类型 Tab
    '<div id="tab-panel-mine">' +
      // 默认配置槽位
      '<div style="margin-bottom:28px;">' +
        '<div style="font-size:0.85rem;font-weight:700;color:var(--text);margin-bottom:4px;">默认配置</div>' +
        '<div style="font-size:0.8rem;color:var(--muted);margin-bottom:12px;">上传录音时自动勾选，最多3个，APP端按此顺序触发分析</div>' +
        '<div id="rank-slots" style="display:flex;gap:12px;flex-wrap:wrap;"></div>' +
      '</div>' +
      // 已安装类型列表
      '<div>' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">' +
          '<div style="font-size:0.85rem;font-weight:700;color:var(--text);">已安装的分析类型</div>' +
          '<button class="btn btn-primary btn-sm" onclick="showCreateTypeModal()" style="font-size:0.82rem;">+ 新建类型</button>' +
        '</div>' +
        '<div id="installed-types-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;"></div>' +
      '</div>' +
    '</div>' +

    // 类型库 Tab
    '<div id="tab-panel-library" style="display:none;">' +
      '<div style="font-size:0.8rem;color:var(--muted);margin-bottom:16px;">点击「安装」即可添加到"我的类型"，安装后可设为默认并微调 Prompt。</div>' +
      '<div id="preset-categories"></div>' +
    '</div>';

  // 注入 tab 样式
  if (!document.getElementById('tt-tab-style')) {
    var s = document.createElement('style');
    s.id = 'tt-tab-style';
    s.textContent =
      '.tab-btn{padding:8px 20px;border:none;background:none;cursor:pointer;font-size:0.9rem;color:var(--muted);font-weight:500;border-bottom:3px solid transparent;margin-bottom:-2px;}' +
      '.tab-active{color:var(--accent);border-bottom-color:var(--accent);}' +
      '.type-card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:10px;}' +
      '.rank-slot{background:#fff;border:2px dashed var(--border);border-radius:10px;padding:14px 18px;min-width:200px;flex:1;max-width:260px;}' +
      '.rank-slot.filled{border-style:solid;border-color:var(--accent);}' +
      '.preset-card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:16px 18px;}';
    document.head.appendChild(s);
  }

  loadInstalledTypes();
}

function switchTab(tab) {
  _activeTab = tab;
  document.getElementById('tab-panel-mine').style.display = tab === 'mine' ? '' : 'none';
  document.getElementById('tab-panel-library').style.display = tab === 'library' ? '' : 'none';
  document.getElementById('tab-mine').className = 'tab-btn' + (tab === 'mine' ? ' tab-active' : '');
  document.getElementById('tab-library').className = 'tab-btn' + (tab === 'library' ? ' tab-active' : '');
  if (tab === 'library') loadPresetLibrary();
}

// ==================== 我的类型 Tab ====================

function loadInstalledTypes() {
  apiRequest('/admin/task-types').then(function(data) {
    _allInstalledTypes = (data && data.task_types) || [];
    renderRankSlots();
    renderInstalledGrid();
  }).catch(function(e) {
    showToast('加载失败：' + e.message, 'error');
  });
}

function renderRankSlots() {
  var container = document.getElementById('rank-slots');
  if (!container) return;

  var ranked = [null, null, null]; // index 0→rank1, 1→rank2, 2→rank3
  _allInstalledTypes.forEach(function(t) {
    if (t.default_rank >= 1 && t.default_rank <= 3) {
      ranked[t.default_rank - 1] = t;
    }
  });

  var labels = ['默认 ①', '默认 ②', '默认 ③'];
  container.innerHTML = ranked.map(function(t, i) {
    var rank = i + 1;
    if (t) {
      return '<div class="rank-slot filled">' +
        '<div style="font-size:0.75rem;font-weight:700;color:var(--accent);margin-bottom:6px;">' + labels[i] + '</div>' +
        '<div style="font-weight:600;font-size:0.95rem;">' + escHtml(t.display_name) + '</div>' +
        '<div style="font-size:0.78rem;color:var(--muted);margin-top:3px;">' + escHtml(t.description || '') + '</div>' +
        '<button class="btn btn-ghost btn-sm" style="margin-top:8px;color:var(--danger);padding:2px 8px;font-size:0.75rem;" ' +
          'onclick="clearRank(' + rank + ')">移除</button>' +
      '</div>';
    } else {
      return '<div class="rank-slot" style="opacity:0.6;">' +
        '<div style="font-size:0.75rem;font-weight:700;color:var(--muted);margin-bottom:6px;">' + labels[i] + '</div>' +
        '<div style="font-size:0.85rem;color:var(--muted);">空槽位</div>' +
        '<div style="font-size:0.78rem;color:var(--muted);margin-top:3px;">在下方类型卡片中点击「设为默认」</div>' +
      '</div>';
    }
  }).join('');
}

function renderInstalledGrid() {
  var container = document.getElementById('installed-types-grid');
  if (!container) return;

  var active = _allInstalledTypes.filter(function(t) { return t.is_active !== false; });
  var inactive = _allInstalledTypes.filter(function(t) { return t.is_active === false; });
  var all = active.concat(inactive);

  if (all.length === 0) {
    container.innerHTML = '<div style="color:var(--muted);font-size:0.9rem;padding:16px 0;">暂无已安装类型，请前往「类型库」安装</div>';
    return;
  }

  container.innerHTML = all.map(function(t) {
    var rankBadge = t.default_rank > 0
      ? '<span style="background:var(--accent);color:#fff;font-size:0.72rem;padding:2px 8px;border-radius:10px;font-weight:600;">默认' + ['①','②','③'][t.default_rank-1] + '</span>'
      : '';
    var statusStyle = t.is_active === false ? 'opacity:0.5;' : '';

    // default_rank 操作按钮
    var rankOptions = [1,2,3].map(function(r) {
      var label = '设为默认' + ['①','②','③'][r-1];
      var isCurrent = t.default_rank === r;
      return '<option value="' + r + '"' + (isCurrent ? ' selected' : '') + '>' + label + '</option>';
    }).join('');

    return '<div class="type-card" style="' + statusStyle + '">' +
      '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;">' +
        '<div>' +
          '<div style="font-weight:600;font-size:0.95rem;">' + escHtml(t.display_name) + '</div>' +
          '<div style="font-size:0.75rem;color:var(--muted);margin-top:2px;font-family:var(--font-mono);">' + escHtml(t.name) + '</div>' +
        '</div>' +
        rankBadge +
      '</div>' +
      '<div style="font-size:0.82rem;color:var(--muted);">' + escHtml(t.description || '') + '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">' +
        '<select class="form-select" style="font-size:0.8rem;padding:4px 8px;height:auto;" ' +
          'onchange="setRank(\'' + t.type_id + '\',' + t.default_rank + ',this.value)">' +
          '<option value="0"' + (t.default_rank === 0 ? ' selected' : '') + '>不设为默认</option>' +
          rankOptions +
        '</select>' +
        '<button class="btn btn-ghost btn-sm" style="font-size:0.8rem;" ' +
          'onclick="showPromptEditor(\'' + t.type_id + '\',\'' + escHtml(t.display_name) + '\',\'' + escHtml(t.prompt_key || t.name) + '\')">编辑 Prompt</button>' +
        '<button class="btn btn-ghost btn-sm" style="font-size:0.8rem;color:' + (t.is_active === false ? 'var(--accent)' : 'var(--danger)') + ';" ' +
          'onclick="toggleActive(\'' + t.type_id + '\',' + (t.is_active !== false) + ')">' +
          (t.is_active === false ? '启用' : '停用') +
        '</button>' +
        '<button class="btn btn-ghost btn-sm" style="font-size:0.8rem;color:var(--danger);opacity:0.6;" ' +
          'onclick="deleteType(\'' + t.type_id + '\',\'' + escHtml(t.display_name) + '\')">删除</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

function setRank(typeId, currentRank, newRankStr) {
  var newRank = parseInt(newRankStr) || 0;
  if (newRank === currentRank) return;
  apiRequest('/admin/task-types/' + typeId, {
    method: 'PATCH',
    body: JSON.stringify({ default_rank: newRank })
  }).then(function() {
    showToast(newRank > 0 ? '已设为默认' + ['①','②','③'][newRank-1] : '已取消默认', 'success');
    loadInstalledTypes();
  }).catch(function(e) { showToast('设置失败：' + e.message, 'error'); });
}

function clearRank(rank) {
  var t = _allInstalledTypes.find(function(x) { return x.default_rank === rank; });
  if (!t) return;
  setRank(t.type_id, rank, 0);
}

function toggleActive(typeId, currentActive) {
  apiRequest('/admin/task-types/' + typeId, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: !currentActive })
  }).then(function() {
    showToast(currentActive ? '已停用' : '已启用', 'success');
    loadInstalledTypes();
  }).catch(function(e) { showToast('操作失败：' + e.message, 'error'); });
}

// ==================== Prompt 微调弹窗 ====================

function showPromptEditor(typeId, displayName, promptKey) {
  // 先拉取当前 prompt 内容
  apiRequest('/admin/prompts').then(function(data) {
    var templates = (data && data.prompts) || [];
    var tpl = templates.find(function(t) { return t.name === promptKey && t.is_active; });
    var content = tpl ? tpl.content : '（未找到对应 Prompt，请先在「Prompt管理」页面创建）';
    var templateId = tpl ? tpl.template_id : null;
    _showPromptEditorModal(typeId, displayName, promptKey, content, templateId);
  }).catch(function() {
    _showPromptEditorModal(typeId, displayName, promptKey, '', null);
  });
}

function _showPromptEditorModal(typeId, displayName, promptKey, content, templateId) {
  var existing = document.getElementById('prompt-editor-modal');
  if (existing) existing.remove();

  var modal = document.createElement('div');
  modal.id = 'prompt-editor-modal';
  modal.className = 'modal-overlay';
  modal.innerHTML =
    '<div class="modal" style="max-width:680px;">' +
      '<div class="modal-header">' +
        '<h3 class="modal-title">微调 Prompt — ' + escHtml(displayName) + '</h3>' +
        '<button class="btn btn-ghost btn-icon" onclick="closePromptEditor()">' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="modal-body">' +
        '<p style="font-size:0.82rem;color:var(--muted);margin-bottom:10px;">修改后保存即生效。<code style="background:var(--surface);padding:2px 6px;border-radius:4px;">{text}</code> 是录音转写文本的占位符，必须保留。</p>' +
        '<textarea id="prompt-editor-textarea" style="width:100%;height:320px;font-family:var(--font-mono);font-size:0.82rem;padding:12px;border:1px solid var(--border);border-radius:8px;resize:vertical;line-height:1.6;" spellcheck="false">' +
          escHtml(content) +
        '</textarea>' +
      '</div>' +
      '<div class="modal-footer">' +
        '<button class="btn btn-ghost" onclick="resetPromptToDefault(\'' + escHtml(promptKey) + '\')" style="margin-right:auto;">恢复默认</button>' +
        '<button class="btn btn-ghost" onclick="closePromptEditor()">取消</button>' +
        '<button class="btn btn-primary" onclick="savePromptEdit(\'' + escHtml(promptKey) + '\',\'' + (templateId||'') + '\')">保存</button>' +
      '</div>' +
    '</div>';

  document.body.appendChild(modal);
  requestAnimationFrame(function() { modal.classList.add('active'); });
}

function closePromptEditor() {
  var m = document.getElementById('prompt-editor-modal');
  if (m) m.remove();
}

function savePromptEdit(promptKey, templateId) {
  var content = document.getElementById('prompt-editor-textarea').value.trim();
  if (!content) { showToast('Prompt 内容不能为空', 'error'); return; }
  if (!content.includes('{text}')) { showToast('Prompt 必须包含 {text} 占位符', 'error'); return; }

  var doSave = function(tid) {
    apiRequest('/admin/prompts/' + tid, {
      method: 'PUT',
      body: JSON.stringify({ content: content })
    }).then(function() {
      showToast('Prompt 已保存', 'success');
      closePromptEditor();
    }).catch(function(e) { showToast('保存失败：' + e.message, 'error'); });
  };

  if (templateId) {
    doSave(templateId);
  } else {
    // 创建新模板
    apiRequest('/admin/prompts', {
      method: 'POST',
      body: JSON.stringify({ name: promptKey, content: content, description: '', is_active: true })
    }).then(function(data) {
      showToast('Prompt 已创建并保存', 'success');
      closePromptEditor();
    }).catch(function(e) { showToast('创建失败：' + e.message, 'error'); });
  }
}

function resetPromptToDefault(promptKey) {
  if (!confirm('确认恢复为系统默认 Prompt？您当前的修改将丢失。')) return;
  apiRequest('/admin/type-presets/' + promptKey + '/reset-prompt', { method: 'POST' })
    .then(function() {
      showToast('已恢复为默认 Prompt', 'success');
      closePromptEditor();
    })
    .catch(function(e) { showToast('恢复失败（该类型可能不是预置类型）：' + e.message, 'error'); });
}

// ==================== 类型库 Tab ====================

function loadPresetLibrary() {
  apiRequest('/admin/type-presets').then(function(data) {
    var presets = (data && data.presets) || [];
    renderPresetLibrary(presets);
  }).catch(function(e) {
    var c = document.getElementById('preset-categories');
    if (c) c.innerHTML = '<div style="color:var(--danger);">加载失败：' + e.message + '</div>';
  });
}

function renderPresetLibrary(presets) {
  var container = document.getElementById('preset-categories');
  if (!container) return;

  // 按 category 分组
  var groups = {};
  presets.forEach(function(p) {
    var cat = p.category || '通用';
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(p);
  });

  var catOrder = ['通用', '商业', '洞察', '客户', '展厅'];
  var html = '';
  catOrder.forEach(function(cat) {
    if (!groups[cat]) return;
    html += '<div style="margin-bottom:24px;">' +
      '<div style="font-size:0.82rem;font-weight:700;color:var(--muted);letter-spacing:1px;margin-bottom:10px;text-transform:uppercase;">' + cat + '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;">' +
      groups[cat].map(function(p) {
        var installed = p.installed;
        return '<div class="preset-card">' +
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">' +
            '<div style="font-weight:600;font-size:0.95rem;">' + escHtml(p.display_name) + '</div>' +
            (installed
              ? '<span style="font-size:0.75rem;background:#eef7f0;color:#4a7c59;padding:2px 8px;border-radius:10px;font-weight:600;">已安装</span>'
              : '<button class="btn btn-primary btn-sm" style="font-size:0.8rem;padding:4px 12px;" onclick="installPreset(\'' + p.name + '\')">安装</button>'
            ) +
          '</div>' +
          '<div style="font-size:0.82rem;color:var(--muted);">' + escHtml(p.description) + '</div>' +
        '</div>';
      }).join('') +
      '</div></div>';
  });
  // 处理未在 catOrder 中的分类
  Object.keys(groups).forEach(function(cat) {
    if (catOrder.indexOf(cat) === -1) {
      html += '<div style="margin-bottom:24px;">' +
        '<div style="font-size:0.82rem;font-weight:700;color:var(--muted);letter-spacing:1px;margin-bottom:10px;">' + cat + '</div>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;">' +
        groups[cat].map(function(p) {
          return '<div class="preset-card"><div style="font-weight:600;">' + escHtml(p.display_name) + '</div></div>';
        }).join('') +
        '</div></div>';
    }
  });

  container.innerHTML = html || '<div style="color:var(--muted);">暂无预置类型</div>';
}

function installPreset(name) {
  apiRequest('/admin/type-presets/' + name + '/install', { method: 'POST' })
    .then(function(data) {
      showToast('安装成功：' + data.task_type.display_name, 'success');
      // 刷新预设库和已安装列表
      loadPresetLibrary();
      loadInstalledTypes();
    })
    .catch(function(e) { showToast('安装失败：' + e.message, 'error'); });
}

// ==================== 删除类型 ====================

function deleteType(typeId, displayName) {
  if (!confirm('确认删除「' + displayName + '」？\n\n已生成的报告不受影响，但该类型将无法再用于新的分析。\n\n建议用「停用」代替删除。')) return;
  apiRequest('/admin/task-types/' + typeId, { method: 'DELETE' })
    .then(function() {
      showToast('已删除：' + displayName, 'success');
      loadInstalledTypes();
    })
    .catch(function(e) { showToast('删除失败：' + e.message, 'error'); });
}

// ==================== 新建自定义类型 ====================

function showCreateTypeModal() {
  var existing = document.getElementById('create-type-modal');
  if (existing) existing.remove();

  var modal = document.createElement('div');
  modal.id = 'create-type-modal';
  modal.className = 'modal-overlay';
  modal.innerHTML =
    '<div class="modal" style="max-width:620px;">' +
      '<div class="modal-header">' +
        '<h3 class="modal-title">新建分析类型</h3>' +
        '<button class="btn btn-ghost btn-icon" onclick="closeCreateTypeModal()">' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +

      '<div class="modal-body" style="display:flex;flex-direction:column;gap:16px;">' +

        // 类型标识
        '<div>' +
          '<label style="font-size:0.82rem;font-weight:600;color:var(--text);display:block;margin-bottom:6px;">' +
            '类型标识 <span style="color:var(--danger);">*</span>' +
            '<span style="font-size:0.75rem;font-weight:400;color:var(--muted);margin-left:8px;">英文小写+下划线，如 sales_review，全局唯一</span>' +
          '</label>' +
          '<input id="ct-name" type="text" class="form-input" placeholder="例如：sales_review" ' +
            'style="font-family:var(--font-mono);" ' +
            'oninput="this.value=this.value.toLowerCase().replace(/[^a-z0-9_]/g,\'\')" />' +
        '</div>' +

        // 显示名称
        '<div>' +
          '<label style="font-size:0.82rem;font-weight:600;color:var(--text);display:block;margin-bottom:6px;">' +
            '显示名称 <span style="color:var(--danger);">*</span>' +
            '<span style="font-size:0.75rem;font-weight:400;color:var(--muted);margin-left:8px;">展示给用户的名字，如「销售复盘」</span>' +
          '</label>' +
          '<input id="ct-display-name" type="text" class="form-input" placeholder="例如：销售复盘" />' +
        '</div>' +

        // 描述
        '<div>' +
          '<label style="font-size:0.82rem;font-weight:600;color:var(--text);display:block;margin-bottom:6px;">' +
            '描述' +
            '<span style="font-size:0.75rem;font-weight:400;color:var(--muted);margin-left:8px;">可选，说明这个类型能分析什么</span>' +
          '</label>' +
          '<input id="ct-description" type="text" class="form-input" placeholder="例如：销售录音 → 复盘要点与跟进建议" />' +
        '</div>' +

        // Prompt
        '<div>' +
          '<label style="font-size:0.82rem;font-weight:600;color:var(--text);display:block;margin-bottom:6px;">' +
            'Prompt 内容 <span style="color:var(--danger);">*</span>' +
            '<span style="font-size:0.75rem;font-weight:400;color:var(--muted);margin-left:8px;">' +
              '必须包含 <code style="background:var(--surface);padding:1px 5px;border-radius:3px;">{text}</code> 作为录音文本占位符' +
            '</span>' +
          '</label>' +
          '<textarea id="ct-prompt" class="form-input" rows="10" ' +
            'style="font-family:var(--font-mono);font-size:0.82rem;resize:vertical;line-height:1.6;" ' +
            'placeholder="你是一位专业的销售分析师。\n\n请分析以下销售录音，输出 JSON 格式：\n{\"title\": \"销售复盘\", \"sections\": [\n  {\"type\": \"list\", \"title\": \"关键问题\", \"items\": [...]},\n  {\"type\": \"kv\",   \"title\": \"客户画像\", \"items\": [{\"label\":\"需求\",\"value\":\"...\"}]},\n  {\"type\": \"actions\", \"title\": \"跟进行动\", \"items\": [{\"action\":\"...\",\"priority\":\"高\",\"notes\":\"...\"}]}\n]}\n\n录音内容：\n{text}">' +
          '</textarea>' +
          '<div style="font-size:0.75rem;color:var(--muted);margin-top:6px;">' +
            '💡 sections 支持的 type：' +
            '<code style="background:var(--surface);padding:1px 4px;border-radius:3px;">text</code> ' +
            '<code style="background:var(--surface);padding:1px 4px;border-radius:3px;">list</code> ' +
            '<code style="background:var(--surface);padding:1px 4px;border-radius:3px;">kv</code> ' +
            '<code style="background:var(--surface);padding:1px 4px;border-radius:3px;">tags</code> ' +
            '<code style="background:var(--surface);padding:1px 4px;border-radius:3px;">actions</code>' +
          '</div>' +
        '</div>' +

      '</div>' +

      '<div class="modal-footer">' +
        '<button class="btn btn-ghost" onclick="closeCreateTypeModal()">取消</button>' +
        '<button class="btn btn-primary" id="ct-submit-btn" onclick="submitCreateType()">创建类型</button>' +
      '</div>' +
    '</div>';

  document.body.appendChild(modal);
  requestAnimationFrame(function() { modal.classList.add('active'); });
  setTimeout(function() {
    var nameInput = document.getElementById('ct-name');
    if (nameInput) nameInput.focus();
  }, 150);
}

function closeCreateTypeModal() {
  var m = document.getElementById('create-type-modal');
  if (m) m.remove();
}

function submitCreateType() {
  var name        = (document.getElementById('ct-name').value || '').trim();
  var displayName = (document.getElementById('ct-display-name').value || '').trim();
  var description = (document.getElementById('ct-description').value || '').trim();
  var prompt      = (document.getElementById('ct-prompt').value || '').trim();

  // 校验
  if (!name) { showToast('请填写类型标识', 'error'); document.getElementById('ct-name').focus(); return; }
  if (!/^[a-z][a-z0-9_]*$/.test(name)) { showToast('类型标识只能用小写字母、数字、下划线，且须以字母开头', 'error'); return; }
  if (!displayName) { showToast('请填写显示名称', 'error'); document.getElementById('ct-display-name').focus(); return; }
  if (!prompt) { showToast('请填写 Prompt 内容', 'error'); document.getElementById('ct-prompt').focus(); return; }
  if (!prompt.includes('{text}')) { showToast('Prompt 必须包含 {text} 占位符', 'error'); return; }

  var btn = document.getElementById('ct-submit-btn');
  btn.disabled = true;
  btn.textContent = '创建中…';

  // Step 1: 先创建 PromptTemplate
  apiRequest('/admin/prompts', {
    method: 'POST',
    body: JSON.stringify({
      name: name,
      description: description || (displayName + ' — 自定义分析类型'),
      content: prompt,
      is_active: true
    })
  })
  .then(function() {
    // Step 2: 创建 TaskType，prompt_key 指向刚建的模板
    return apiRequest('/admin/task-types', {
      method: 'POST',
      body: JSON.stringify({
        name: name,
        display_name: displayName,
        description: description || '',
        prompt_key: name,
        default_rank: 0,
        sort_order: 100
      })
    });
  })
  .then(function(data) {
    showToast('✅ 类型「' + displayName + '」创建成功', 'success');
    closeCreateTypeModal();
    loadInstalledTypes();
  })
  .catch(function(e) {
    showToast('创建失败：' + e.message, 'error');
    btn.disabled = false;
    btn.textContent = '创建类型';
  });
}

// ==================== 工具函数 ====================

function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
