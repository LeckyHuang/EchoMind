// ==================== Prompt 配置管理页 ====================
// 三种报告类型各自独立配置 Prompt

const REPORT_TYPE_META = {
  // ── 三份分析报告 Prompt（输入变量：{text}）──
  customer_brief:            { label: '参观简报',             desc: '接待录音 → 参观简报（官方报道风格）',       color: '#6366F1', varHint: '{text} 为 ASR 转写文本' },
  business_opportunity:      { label: '商机简报',             desc: '接待录音 → 商机简报（发给客户经理）',       color: '#10B981', varHint: '{text} 为 ASR 转写文本' },
  reception_review:          { label: '接待复盘',             desc: '接待录音 → 接待复盘（运营团队参考）',       color: '#F59E0B', varHint: '{text} 为 ASR 转写文本；可用 {context_data} 注入补充上下文' },
  // ── 三份分享报告叙事化 Prompt（输入变量：{data}）──
  customer_brief_share:      { label: '参观简报·分享报告叙事化', desc: '结构化参观简报 → 新闻稿风格叙事文本（生成分享报告时调用）', color: '#8B5CF6', varHint: '{data} 为结构化报告 JSON' },
  business_opportunity_share:{ label: '商机简报·分享报告叙事化', desc: '结构化商机简报 → 内部简报叙事文本（生成分享报告时调用）',   color: '#059669', varHint: '{data} 为结构化报告 JSON' },
  reception_review_share:    { label: '接待复盘·分享报告叙事化', desc: '结构化接待复盘 → 运营简报叙事文本（生成分享报告时调用）',   color: '#D97706', varHint: '{data} 为结构化报告 JSON' },
};

let editingTemplateId = null;
let editingReportType = null;

async function initPrompts() {
  if (!requireAuth()) return;

  setPageTitle('Prompt 配置');

  const main = getMainContent();
  main.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Prompt 配置</h1>
      <p style="color:var(--muted);margin-top:4px;font-size:0.9rem;">为六种 Prompt 分别配置 LLM 提示词（3 份分析报告 + 3 份分享报告叙事化），系统优先使用已激活的数据库版本，否则使用内置文件。</p>
    </div>

    <div id="prompt-sections" class="stagger">
      <div style="text-align:center;padding:60px;color:var(--muted);">加载中...</div>
    </div>
  `;

  await loadPromptSections();
}

async function loadPromptSections() {
  const container = document.getElementById('prompt-sections');

  try {
    const data = await getPrompts();
    const allPrompts = data.prompts || [];

    // 按 report_type(name) 分组
    const byType = {};
    for (const p of allPrompts) {
      if (!byType[p.name]) byType[p.name] = [];
      byType[p.name].push(p);
    }

    const ANALYSIS_TYPES = ['customer_brief', 'business_opportunity', 'reception_review'];
    const SHARE_TYPES    = ['customer_brief_share', 'business_opportunity_share', 'reception_review_share'];

    const renderGroup = (types, groupTitle) => `
      <div style="margin-bottom:8px;">
        <h2 style="font-size:13px;font-weight:700;letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border);">${groupTitle}</h2>
        ${types.map(type => {
          const meta = REPORT_TYPE_META[type];
          const prompts = byType[type] || [];
          const active = prompts.find(p => p.is_active);
          const inactive = prompts.filter(p => !p.is_active);
          return `
            <div class="card fade-in" style="margin-bottom:24px;border-top:3px solid ${meta.color};">
              <div class="card-header" style="align-items:flex-start;">
                <div>
                  <h3 class="card-title" style="color:${meta.color};">${meta.label}</h3>
                  <p style="color:var(--muted);font-size:0.85rem;margin-top:4px;">${meta.desc}</p>
                </div>
                <button class="btn btn-primary btn-sm" onclick="showCreatePromptModal('${type}')">
                  + 新建版本
                </button>
              </div>
              <div class="card-body">
                ${active ? renderActivePromptCard(active, type) : renderNoActiveCard(type)}
                ${inactive.length > 0 ? renderInactiveList(inactive, type) : ''}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;

    container.innerHTML =
      renderGroup(ANALYSIS_TYPES, '分析报告 Prompt（输入：录音转写文本）') +
      renderGroup(SHARE_TYPES,    '分享报告叙事化 Prompt（输入：结构化报告数据）');

  } catch (error) {
    container.innerHTML = `<div style="color:var(--danger);padding:20px;">加载失败: ${error.message}</div>`;
  }
}

function renderActivePromptCard(prompt, type) {
  const preview = (prompt.content || '').substring(0, 200).replace(/</g, '&lt;');
  return `
    <div style="background:var(--surface-2);border-radius:8px;padding:16px;margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="badge badge-success">当前激活</span>
          <span style="font-size:0.85rem;color:var(--muted);">更新于 ${formatDate(prompt.updated_at)}</span>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-ghost btn-sm" onclick="showEditPromptModal('${prompt.template_id}', '${type}')">编辑</button>
          <button class="btn btn-ghost btn-sm" onclick="deactivatePrompt('${prompt.template_id}')">停用</button>
        </div>
      </div>
      ${prompt.description ? `<p style="color:var(--muted);font-size:0.85rem;margin-bottom:8px;">${escapeHtml(prompt.description)}</p>` : ''}
      <pre style="background:var(--surface-1);padding:12px;border-radius:6px;font-size:12px;max-height:120px;overflow:auto;white-space:pre-wrap;color:var(--text-secondary);">${preview}${prompt.content.length > 200 ? '\n...' : ''}</pre>
    </div>
  `;
}

function renderNoActiveCard(type) {
  return `
    <div style="border:2px dashed var(--border);border-radius:8px;padding:20px;text-align:center;color:var(--muted);margin-bottom:12px;">
      <p style="margin-bottom:12px;">当前类型未配置激活的数据库 Prompt，系统将使用内置文件版本</p>
      <button class="btn btn-secondary btn-sm" onclick="showCreatePromptModal('${type}')">
        创建并激活自定义版本
      </button>
    </div>
  `;
}

function renderInactiveList(prompts, type) {
  return `
    <details style="margin-top:8px;">
      <summary style="cursor:pointer;color:var(--muted);font-size:0.85rem;user-select:none;">
        历史版本 (${prompts.length})
      </summary>
      <div style="margin-top:12px;display:flex;flex-direction:column;gap:8px;">
        ${prompts.map(p => `
          <div style="background:var(--surface-2);border-radius:6px;padding:12px;display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:0.85rem;color:var(--muted);">${p.description || '无描述'} · ${formatDate(p.updated_at)}</span>
            <div style="display:flex;gap:6px;">
              <button class="btn btn-ghost btn-sm" onclick="activatePromptHandler('${p.template_id}', '${type}')">激活</button>
              <button class="btn btn-ghost btn-sm" onclick="showEditPromptModal('${p.template_id}', '${type}')">编辑</button>
              <button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="deletePromptHandler('${p.template_id}', '${type}')">删除</button>
            </div>
          </div>
        `).join('')}
      </div>
    </details>
  `;
}

// ==================== Modal ====================

function showCreatePromptModal(reportType) {
  editingTemplateId = null;
  editingReportType = reportType;
  const meta = REPORT_TYPE_META[reportType];
  showPromptModal(`新建 Prompt —— ${meta.label}`, null);
}

async function showEditPromptModal(templateId, reportType) {
  editingTemplateId = templateId;
  editingReportType = reportType;
  const meta = REPORT_TYPE_META[reportType];
  try {
    const prompt = await getPrompt(templateId);
    showPromptModal(`编辑 Prompt —— ${meta.label}`, prompt);
  } catch (e) {
    showToast('加载失败', 'error');
  }
}

function showPromptModal(title, prompt) {
  const modal = createModal(title, `
    <div class="form-group">
      <label class="form-label">描述（可选）</label>
      <input type="text" id="prompt-description" class="form-input"
        placeholder="简短描述此版本的用途或特点"
        value="${escapeHtml(prompt?.description || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Prompt 内容</label>
      <p style="color:var(--muted);font-size:0.8rem;margin-bottom:6px;">
        占位符：<code>${REPORT_TYPE_META[editingReportType]?.varHint || '{text} 为转写文本'}</code>
      </p>
      <textarea id="prompt-content" class="form-textarea"
        style="min-height:320px;font-family:var(--font-mono);font-size:13px;"
        placeholder="在此输入 Prompt 模板...">${escapeHtml(prompt?.content || '')}</textarea>
    </div>
    <div class="form-group">
      <label class="form-label">
        <input type="checkbox" id="prompt-is-active" ${prompt?.is_active || !editingTemplateId ? 'checked' : ''}>
        &nbsp;保存后立即激活（将替换当前激活版本）
      </label>
    </div>
  `, [
    { text: '取消', class: 'btn-secondary', action: 'close' },
    { text: prompt ? '保存' : '创建', class: 'btn-primary', action: savePromptHandler }
  ]);
  document.body.appendChild(modal);
  setTimeout(() => modal.classList.add('active'), 10);
}

async function savePromptHandler() {
  const description = document.getElementById('prompt-description').value.trim();
  const content = document.getElementById('prompt-content').value.trim();
  const isActive = document.getElementById('prompt-is-active').checked;

  if (!content) { showToast('请输入 Prompt 内容', 'warning'); return; }

  try {
    if (editingTemplateId) {
      await updatePrompt(editingTemplateId, { description, content, is_active: isActive });
      showToast('Prompt 更新成功', 'success');
    } else {
      // 创建时，name = report type
      await createPrompt({ name: editingReportType, description, content, is_active: isActive });
      showToast('Prompt 创建成功', 'success');
    }
    closeModal();
    await loadPromptSections();
  } catch (error) {
    showToast(error.message || '保存失败', 'error');
  }
}

async function activatePromptHandler(templateId, type) {
  try {
    await togglePromptActive(templateId, true);
    showToast('已激活', 'success');
    await loadPromptSections();
  } catch (e) {
    showToast(e.message || '激活失败', 'error');
  }
}

async function deactivatePrompt(templateId) {
  try {
    await togglePromptActive(templateId, false);
    showToast('已停用，系统将使用内置文件版本', 'success');
    await loadPromptSections();
  } catch (e) {
    showToast(e.message || '停用失败', 'error');
  }
}

async function deletePromptHandler(templateId, type) {
  const modal = createModal('删除确认', `
    <p style="margin-bottom:12px;">确定要删除此 Prompt 版本吗？</p>
    <p style="color:var(--danger);font-size:0.85rem;">此操作不可恢复。</p>
  `, [
    { text: '取消', class: 'btn-secondary', action: 'close' },
    { text: '删除', class: 'btn-danger', action: async () => {
      try {
        await deletePrompt(templateId);
        showToast('已删除', 'success');
        closeModal();
        await loadPromptSections();
      } catch (e) {
        showToast(e.message || '删除失败', 'error');
        closeModal();
      }
    }}
  ]);
  document.body.appendChild(modal);
  setTimeout(() => modal.classList.add('active'), 10);
}

// ==================== Modal helpers ====================

function createModal(title, content, buttons) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal" style="max-width:680px;max-height:90vh;overflow-y:auto;">
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
    const b = document.createElement('button');
    b.className = `btn ${btn.class}`;
    b.textContent = btn.text;
    b.onclick = () => typeof btn.action === 'function' ? btn.action() : closeModal();
    footer.appendChild(b);
  });
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  return modal;
}

function closeModal() {
  const modal = document.querySelector('.modal-overlay.active');
  if (modal) { modal.classList.remove('active'); setTimeout(() => modal.remove(), 200); }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

window.closeModal = closeModal;
