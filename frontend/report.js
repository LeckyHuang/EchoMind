// ==================== 报告详情页 ====================
// 通过 file_id 加载，展示三份报告：参观简报 / 商机简报 / 接待复盘

const REPORT_TYPES = {
  customer_brief:       { label: '参观简报', desc: '官方报道风格' },
  business_opportunity: { label: '商机简报', desc: '发给客户经理' },
  reception_review:     { label: '接待复盘', desc: '运营团队参考' },
};

// 当前加载的报告数据（含 report_id，用于编辑/分享操作）
let currentReports = {};
// 当前文件 ID
let currentFileId = null;
// 语音识别实例
let speechRecognition = null;
let speechRecognizing = false;

async function initReport() {
  if (!requireAuth()) return;

  const urlParams = new URLSearchParams(window.location.search);
  currentFileId = urlParams.get('id') || urlParams.get('file_id');

  if (!currentFileId) {
    showToast('未指定文件ID', 'error');
    window.location.href = 'files.html';
    return;
  }

  setPageTitle('报告详情');

  const main = getMainContent();
  main.innerHTML = `
    <div class="breadcrumb">
      <a href="files.html">录音文件</a>
      <span class="breadcrumb-sep">/</span>
      <span class="breadcrumb-current">报告详情</span>
    </div>

    <div id="report-content">
      <!-- 录音信息卡片 -->
      <div class="card fade-in" style="margin-bottom: 24px;">
        <div class="card-header"><h3 class="card-title">录音信息</h3></div>
        <div class="card-body">
          <div class="info-list" id="file-info">
            <div style="text-align:center;padding:40px;color:var(--muted);">加载中...</div>
          </div>
        </div>
      </div>

      <!-- ASR 转写文本 -->
      <div class="card fade-in" style="margin-bottom:24px;animation-delay:0.08s;">
        <div class="card-header">
          <h3 class="card-title">原始转写文本</h3>
          <button class="btn btn-ghost btn-sm" id="toggle-transcript">收起</button>
        </div>
        <div class="card-body" id="transcript-container" style="padding:0 20px 20px;">
          <div class="transcript-box" id="transcript-content">加载中...</div>
        </div>
      </div>

      <!-- 三份报告 -->
      <div class="card fade-in" style="animation-delay:0.16s;">
        <div class="card-header"><h3 class="card-title">分析报告</h3></div>
        <div class="card-body" style="padding-top:0;">
          <!-- 一级 Tab：三种报告类型 -->
          <div class="tabs" id="report-type-tabs" style="padding: 16px 0 0;">
            ${Object.entries(REPORT_TYPES).map(([key, cfg], i) => `
              <button class="tab-btn${i === 0 ? ' active' : ''}" data-type="${key}">
                ${cfg.label}
                <span style="font-size:11px;color:var(--muted);margin-left:4px;">${cfg.desc}</span>
              </button>
            `).join('')}
          </div>

          <!-- 各报告内容面板 -->
          ${Object.keys(REPORT_TYPES).map((key, i) => `
            <div id="panel-${key}" class="report-panel${i === 0 ? ' active' : ''}" style="padding:16px 0;">
              <div id="content-${key}">
                <div style="text-align:center;padding:40px;color:var(--muted);">加载中...</div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    </div>

    <!-- 手机预览弹窗 -->
    <div id="phone-preview-modal" class="phone-preview-overlay" style="display:none;">
      <div class="phone-preview-dialog">
        <div class="phone-preview-header">
          <button class="btn btn-ghost btn-sm" onclick="closePhonePreview()">✕ 关闭</button>
          <span style="font-weight:600;">手机端预览</span>
          <button class="btn btn-primary btn-sm" id="copy-share-link" title="复制分享链接" style="display:flex;align-items:center;gap:6px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
            分享
          </button>
        </div>
        <div class="phone-frame-wrapper">
          <div class="phone-frame">
            <div class="phone-notch"></div>
            <iframe id="share-preview-iframe" src="" frameborder="0"></iframe>
          </div>
        </div>
      </div>
    </div>
  `;

  // Tab 切换
  document.getElementById('report-type-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.tab-btn');
    if (!btn) return;
    const type = btn.dataset.type;
    document.querySelectorAll('#report-type-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.report-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`panel-${type}`).classList.add('active');
  });

  // 折叠转写文本
  document.getElementById('toggle-transcript').addEventListener('click', () => {
    const container = document.getElementById('transcript-container');
    const btn = document.getElementById('toggle-transcript');
    if (container.style.maxHeight && container.style.maxHeight !== 'none') {
      container.style.maxHeight = 'none';
      btn.textContent = '收起';
    } else {
      container.style.maxHeight = '240px';
      btn.textContent = '展开';
    }
  });

  await loadFileReports(currentFileId);
}

async function loadFileReports(fileId) {
  try {
    const detail = await apiRequest(`/admin/files/${fileId}/detail`);

    // 文件基本信息
    document.getElementById('file-info').innerHTML = `
      <div class="info-item">
        <span class="info-label">文件名</span>
        <span class="info-value">${detail.original_filename || '未知'}</span>
      </div>
      <div class="info-item">
        <span class="info-label">时长</span>
        <span class="info-value" style="font-family:var(--font-mono);">${detail.duration_formatted || formatDuration(detail.duration)}</span>
      </div>
      <div class="info-item">
        <span class="info-label">格式</span>
        <span class="info-value">${(detail.file_format || '-').toUpperCase()}</span>
      </div>
      <div class="info-item">
        <span class="info-label">上传时间</span>
        <span class="info-value" style="font-family:var(--font-mono);">${formatDate(detail.created_at)}</span>
      </div>
      <div class="info-item">
        <span class="info-label">状态</span>
        <span class="info-value">${getStatusBadge(detail.upload_status)}</span>
      </div>
    `;

    // ASR 转写文本
    document.getElementById('transcript-content').textContent =
      detail.asr_text || '（暂无转写文本）';

    // 渲染三份报告
    const reports = detail.reports || {};
    currentReports = reports;

    for (const [type, cfg] of Object.entries(REPORT_TYPES)) {
      const container = document.getElementById(`content-${type}`);
      const report = reports[type];
      if (!report) {
        container.innerHTML = '<p style="color:var(--muted);padding:16px 0;">该报告尚未生成</p>';
      } else if (report.status === 'failed') {
        container.innerHTML = `<div class="badge badge-danger" style="padding:8px 12px;">生成失败：${report.error_message || '未知错误'}</div>`;
      } else if (report.status === 'completed' && report.data) {
        // 合并 AI 数据和用户编辑数据
        const mergedData = mergeReportData(report.data, report.user_edited_data);
        container.innerHTML = renderReportPanel(type, report.report_id, mergedData, report);
        bindPanelEvents(type, report.report_id);
      } else {
        container.innerHTML = '<p style="color:var(--muted);padding:16px 0;">报告状态异常</p>';
      }
    }

  } catch (error) {
    console.error('加载报告失败:', error);
    showToast('加载报告失败: ' + error.message, 'error');
  }
}

// 合并 AI 数据与用户编辑数据（用户编辑覆盖 AI 数据）
function mergeReportData(aiData, userEdits) {
  if (!userEdits) return aiData;
  return deepMerge(aiData, userEdits);
}

function deepMerge(target, source) {
  if (!source) return target;
  const result = { ...target };
  for (const key of Object.keys(source)) {
    if (source[key] !== null && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      result[key] = deepMerge(target[key] || {}, source[key]);
    } else if (source[key] !== null && source[key] !== undefined && source[key] !== '') {
      result[key] = source[key];
    }
  }
  return result;
}

// ==================== 报告面板完整渲染（含工具栏）====================

function renderReportPanel(type, reportId, data, reportMeta) {
  const photos = reportMeta.photos || [];
  const supplementaryText = reportMeta.supplementary_text || '';

  return `
    <!-- 报告主体内容 -->
    <div id="view-${type}" class="report-view-mode">
      ${renderReportByType(type, data, reportMeta.user_edited_data)}

      <!-- 照片展示区 -->
      ${photos.length > 0 ? renderPhotosView(photos, type) : ''}

      <!-- 专家讲解展示（仅接待复盘） -->
      ${type === 'reception_review' && reportMeta.expert_notes ? `
        <div class="collapsible open" style="margin-bottom:16px;">
          <div class="collapsible-header" onclick="toggleCollapsible(this)">
            <span>专家讲解</span>
            <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </div>
          <div class="collapsible-body"><div class="collapsible-content" style="line-height:1.8;white-space:pre-wrap;">${escapeHtml(reportMeta.expert_notes)}</div></div>
        </div>
      ` : ''}

      <!-- 补充内容展示 -->
      ${supplementaryText ? `
        <div class="collapsible open" style="margin-bottom:16px;">
          <div class="collapsible-header" onclick="toggleCollapsible(this)">
            <span>补充说明</span>
            <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </div>
          <div class="collapsible-body"><div class="collapsible-content" style="line-height:1.8;white-space:pre-wrap;">${escapeHtml(supplementaryText)}</div></div>
        </div>
      ` : ''}

      <!-- AI 辅助补录面板 -->
      ${renderAiSupplementPanel(type, reportId, reportMeta)}
    </div>

    <!-- 编辑模式（初始隐藏）-->
    <div id="edit-${type}" class="report-edit-mode" style="display:none;">
      <div class="edit-notice" style="background:var(--accent-muted);border-radius:var(--radius-sm);padding:12px 16px;margin-bottom:16px;font-size:13px;color:var(--accent-dark);">
        ✏ 编辑模式 — 修改后点击「保存」生效，标注 <span class="badge-manual">手动填写</span> 的字段为你补充的内容
      </div>
      <div id="edit-fields-${type}">
        <!-- 由 enterEditMode() 动态生成 -->
      </div>

      <!-- 补充文字 -->
      <div style="margin-bottom:20px;">
        <label style="display:block;font-weight:600;margin-bottom:8px;font-size:13px;">补充说明</label>
        <div style="position:relative;">
          <textarea id="supp-text-${type}" rows="4" style="width:100%;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font-body);font-size:13px;resize:vertical;line-height:1.7;"
            placeholder="可在此补充录音未覆盖的信息，或其他需要说明的内容...">${escapeHtml(supplementaryText)}</textarea>
          <button class="btn btn-ghost btn-sm voice-input-btn" id="voice-btn-${type}" title="语音输入"
            style="position:absolute;right:8px;bottom:8px;"
            onclick="toggleVoiceInput('${type}')">
            🎤 语音
          </button>
        </div>
        <div id="voice-status-${type}" style="font-size:12px;color:var(--muted);margin-top:4px;display:none;">● 正在录音，点击麦克风停止</div>
      </div>

      <!-- 专家讲解（仅接待复盘） -->
      ${type === 'reception_review' ? `
        <div style="margin-bottom:20px;">
          <label style="display:block;font-weight:600;margin-bottom:8px;font-size:13px;">专家讲解</label>
          <div style="font-size:12px;color:var(--muted);margin-bottom:8px;">可复制粘贴ASR转写文本中的优秀讲解段落，AI将帮助梳理分段</div>
          <div style="position:relative;">
            <textarea id="expert-notes-${type}" rows="6" style="width:100%;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font-body);font-size:13px;resize:vertical;line-height:1.7;"
              placeholder="粘贴本次接待中专家/讲解员的优秀讲解内容...">${escapeHtml(reportMeta.expert_notes || '')}</textarea>
          </div>
          <div style="display:flex;gap:8px;margin-top:8px;">
            <button class="btn btn-secondary btn-sm" id="btn-organize-${type}" onclick="organizeExpertNotes('${type}','${reportId}')">
              ✨ AI整理
            </button>
            <span id="organize-status-${type}" style="font-size:12px;color:var(--muted);display:none;align-items:center;">⏳ AI整理中...</span>
          </div>
        </div>
      ` : ''}

      <!-- 照片管理 -->
      <div style="margin-bottom:20px;">
        <label style="display:block;font-weight:600;margin-bottom:8px;font-size:13px;">照片</label>
        <div id="photos-edit-${type}">
          ${renderPhotosEdit(photos, reportId, type)}
        </div>
        <div class="photo-add-tabs" style="margin-top:12px;">
          <div class="tabs" style="margin-bottom:8px;">
            <button class="tab-btn active" onclick="switchPhotoTab('${type}','local',this)">本地上传</button>
            <button class="tab-btn" onclick="switchPhotoTab('${type}','url',this)">URL 链接</button>
          </div>
          <div id="photo-tab-local-${type}">
            <div class="photo-drop-zone" id="drop-zone-${type}"
              onclick="document.getElementById('photo-file-${type}').click()"
              ondragover="event.preventDefault();this.classList.add('drag-over')"
              ondragleave="this.classList.remove('drag-over')"
              ondrop="handlePhotoDrop(event,'${type}','${reportId}')">
              <input type="file" id="photo-file-${type}" accept="image/jpeg,image/png,image/webp" multiple style="display:none"
                onchange="handlePhotoFileSelect(event,'${type}','${reportId}')">
              <div style="text-align:center;color:var(--muted);padding:20px;">
                <div style="font-size:24px;margin-bottom:8px;">📷</div>
                <div>点击或拖拽上传照片（JPG/PNG/WebP）</div>
              </div>
            </div>
          </div>
          <div id="photo-tab-url-${type}" style="display:none;">
            <div style="display:flex;gap:8px;">
              <input type="text" id="photo-url-input-${type}" placeholder="粘贴图片 URL（https://...）"
                style="flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;">
              <button class="btn btn-secondary btn-sm" onclick="handlePhotoUrl('${type}','${reportId}')">添加</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 操作工具栏 -->
    <div class="report-toolbar" id="toolbar-${type}">
      <div id="toolbar-view-${type}">
        <button class="btn btn-secondary btn-sm" onclick="enterEditMode('${type}','${reportId}')">✏ 编辑</button>
        ${reportMeta.share_id
          ? `<button class="btn btn-ghost btn-sm" onclick="openSharePreview('${type}')">📱 查看报告</button>
             <button class="btn btn-ghost btn-sm" onclick="regenerateSharePage('${type}','${reportId}')" title="重新生成分享页">🔄 重新生成</button>`
          : `<button class="btn btn-ghost btn-sm" onclick="generateSharePage('${type}','${reportId}')">🔗 生成预览</button>`
        }
      </div>
      <div id="toolbar-edit-${type}" style="display:none;">
        <button class="btn btn-primary btn-sm" onclick="saveReport('${type}','${reportId}')">💾 保存</button>
        <button class="btn btn-ghost btn-sm" onclick="exitEditMode('${type}')">✕ 取消</button>
      </div>
    </div>
  `;
}

function bindPanelEvents(type, reportId) {
  // 照片拖拽事件已通过 HTML 属性绑定
}

// ==================== 查看模式：报告渲染函数 ====================

function renderReportByType(type, data, userEdits) {
  let html = '';
  switch (type) {
    case 'customer_brief':       html = renderCustomerBrief(data, userEdits); break;
    case 'business_opportunity': html = renderBusinessOpportunity(data, userEdits); break;
    case 'reception_review':     html = renderReceptionReview(data, userEdits); break;
    default: html = renderRawJson(data);
  }
  return `<div style="font-size:13px;">${html}</div>`;
}

// 参观简报渲染
function renderCustomerBrief(d, userEdits) {
  if (!d) return '<p style="color:var(--muted)">暂无数据</p>';
  const ue = userEdits || {};

  const nullField = (val, label) =>
    (val === null || val === undefined)
      ? `<span style="color:var(--muted);font-style:italic;border-bottom:1px dashed var(--border);" title="录音无法提取，可在编辑模式补充">待补充</span>`
      : val;

  const isEdited = (key) => ue && ue[key] !== undefined && ue[key] !== null && ue[key] !== '';

  const guestInfo = d.guest_info || {};
  const guestFeedback = d.guest_feedback || {};

  return `
    <!-- 基本信息卡 -->
    <div class="collapsible open" style="margin-bottom:16px;">
      <div class="collapsible-header" onclick="toggleCollapsible(this)">
        <span>接待基本信息</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content">
        <div class="info-list">
          <div class="info-item">
            <span class="info-label">接待时间</span>
            <span class="info-value ${isEdited('reception_time') ? 'manually-edited' : ''}">${nullField(d.reception_time, '接待时间')}</span>
          </div>
          <div class="info-item">
            <span class="info-label">接待地点</span>
            <span class="info-value ${isEdited('reception_location') ? 'manually-edited' : ''}">${nullField(d.reception_location, '接待地点')}</span>
          </div>
          <div class="info-item">
            <span class="info-label">接待主题</span>
            <span class="info-value">${nullField(d.reception_theme, '接待主题')}</span>
          </div>
          <div class="info-item">
            <span class="info-label">来访单位</span>
            <span class="info-value">${nullField(guestInfo.organization, '来访单位')}</span>
          </div>
          <div class="info-item">
            <span class="info-label">主要嘉宾</span>
            <span class="info-value">${guestInfo.key_guests && guestInfo.key_guests.length ? guestInfo.key_guests.join('、') : nullField(null, '主要嘉宾')}</span>
          </div>
          ${guestInfo.group_size ? `<div class="info-item"><span class="info-label">来访人数</span><span class="info-value">${guestInfo.group_size}</span></div>` : ''}
          ${guestInfo.guest_background ? `<div class="info-item"><span class="info-label">来访背景</span><span class="info-value">${guestInfo.guest_background}</span></div>` : ''}
        </div>
      </div></div>
    </div>

    ${infoCard('活动概述', d.overview)}

    ${d.key_demonstrations && d.key_demonstrations.length ? renderObjectList('重点演示内容', d.key_demonstrations, item => `<b>${item.item}</b>：${item.description || ''}`) : ''}

    ${(() => {
      const hasFeedback = (guestFeedback.suggestions && guestFeedback.suggestions.length) ||
                         (guestFeedback.opinions && guestFeedback.opinions.length) ||
                         (guestFeedback.highlights && guestFeedback.highlights.length);
      if (!hasFeedback) return '';
      return `
        <div class="collapsible open" style="margin-bottom:16px;">
          <div class="collapsible-header" onclick="toggleCollapsible(this)">
            <span>来宾反馈</span>
            <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </div>
          <div class="collapsible-body"><div class="collapsible-content">
            ${guestFeedback.highlights && guestFeedback.highlights.length ? `
              <div style="margin-bottom:12px;"><b style="font-size:13px;color:var(--muted);">特别关注</b>
                <ul style="margin:6px 0 0 20px;line-height:2;">${guestFeedback.highlights.map(i => `<li>${i}</li>`).join('')}</ul>
              </div>` : ''}
            ${guestFeedback.suggestions && guestFeedback.suggestions.length ? `
              <div style="margin-bottom:12px;"><b style="font-size:13px;color:var(--muted);">提出建议</b>
                <ul style="margin:6px 0 0 20px;line-height:2;">${guestFeedback.suggestions.map(i => `<li>${i}</li>`).join('')}</ul>
              </div>` : ''}
            ${guestFeedback.opinions && guestFeedback.opinions.length ? `
              <div><b style="font-size:13px;color:var(--muted);">表达意见</b>
                <ul style="margin:6px 0 0 20px;line-height:2;">${guestFeedback.opinions.map(i => `<li>${i}</li>`).join('')}</ul>
              </div>` : ''}
          </div></div>
        </div>
      `;
    })()}

    ${listCard('促成合作与共识', d.cooperation_outcomes, 'badge-success')}
    ${listCard('后续跟进事项', d.next_steps, 'badge-warning')}
  `;
}

// 商机简报渲染
function renderBusinessOpportunity(d, userEdits) {
  if (!d) return '<p style="color:var(--muted)">暂无数据</p>';

  return `
    ${d.summary ? `
      <div style="background:var(--surface-2);border-left:3px solid var(--accent);padding:14px 16px;border-radius:0 var(--radius-sm) var(--radius-sm) 0;margin-bottom:16px;line-height:1.8;font-size:13px;color:var(--text-body);">
        ${escapeHtml(d.summary)}
      </div>
    ` : ''}

    ${d.key_leads && d.key_leads.length ? `
      <div class="collapsible open" style="margin-bottom:16px;border:1.5px solid var(--accent);border-radius:var(--radius-sm);">
        <div class="collapsible-header" onclick="toggleCollapsible(this)" style="background:var(--accent-muted);">
          <span style="font-weight:700;color:var(--accent-dark);">⚡ 核心商机线索</span>
          <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="collapsible-body"><div class="collapsible-content">
          <ul style="margin-left:0;list-style:none;padding:0;">
            ${d.key_leads.map(lead => `<li style="padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;font-weight:500;line-height:1.6;">${escapeHtml(lead)}</li>`).join('')}
          </ul>
        </div></div>
      </div>
    ` : ''}

    ${infoCard('讨论要点概述', d.discussion_overview)}

    ${d.questions_asked && d.questions_asked.length ? `
      <div class="collapsible open" style="margin-bottom:16px;">
        <div class="collapsible-header" onclick="toggleCollapsible(this)">
          <span>客户提问 (${d.questions_asked.length})</span>
          <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="collapsible-body"><div class="collapsible-content">
          <ul style="margin-left:20px;line-height:2.2;">
            ${d.questions_asked.map(q => `<li style="margin-bottom:4px;">❓ ${q}</li>`).join('')}
          </ul>
        </div></div>
      </div>
    ` : ''}

    ${d.doubts_objections && d.doubts_objections.length ? renderObjectList(
      `客户质疑与顾虑 (${d.doubts_objections.length})`,
      d.doubts_objections,
      item => `<b>${item.topic}</b>：${item.content || ''}`
    ) : ''}

    ${d.interest_points && d.interest_points.length ? `
      <div class="collapsible open" style="margin-bottom:16px;">
        <div class="collapsible-header" onclick="toggleCollapsible(this)">
          <span>明显感兴趣点 (${d.interest_points.length})</span>
          <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="collapsible-body"><div class="collapsible-content">
          ${d.interest_points.map(i => `<span class="badge badge-accent" style="margin:3px;">${i}</span>`).join('')}
        </div></div>
      </div>
    ` : ''}

    ${d.explicit_needs && d.explicit_needs.length ? renderObjectList(
      `显性需求 (${d.explicit_needs.length})`,
      d.explicit_needs,
      item => `<b>${item.need}</b>${item.detail ? `：${item.detail}` : ''}`
    ) : ''}

    ${d.hidden_pain_points && d.hidden_pain_points.length ? renderObjectList(
      `潜在痛点（隐性）(${d.hidden_pain_points.length})`,
      d.hidden_pain_points,
      item => `<b>${item.pain_point}</b><br><small style="color:var(--muted)">推断依据：${item.evidence || ''}</small>`
    ) : ''}

    ${d.next_actions && d.next_actions.length ? renderObjectList(
      `下一步行动 (${d.next_actions.length})`,
      d.next_actions,
      item => `<span class="badge badge-${item.priority === '高' ? 'danger' : item.priority === '中' ? 'warning' : 'muted'}" style="margin-right:8px;">${item.priority || '-'}</span><b>${item.action}</b>${item.notes ? `<br><small style="color:var(--muted)">${item.notes}</small>` : ''}`
    ) : ''}
  `;
}

// 接待复盘渲染
function renderReceptionReview(d, userEdits) {
  if (!d) return '<p style="color:var(--muted)">暂无数据</p>';
  const overview = d.reception_overview || {};
  const guide = d.guide_performance || {};

  return `
    ${d.summary ? `
      <div style="background:var(--surface-2);border-left:3px solid var(--accent);padding:14px 16px;border-radius:0 var(--radius-sm) var(--radius-sm) 0;margin-bottom:16px;line-height:1.8;font-size:13px;color:var(--text-body);">
        ${escapeHtml(d.summary)}
      </div>
    ` : ''}

    ${(d.top_highlights && d.top_highlights.length) || (d.top_improvements && d.top_improvements.length) ? `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
        ${d.top_highlights && d.top_highlights.length ? `
          <div style="background:#eef7f0;border-radius:var(--radius-sm);padding:14px 16px;">
            <div style="font-size:11px;font-weight:700;color:#4a7c59;letter-spacing:1px;margin-bottom:8px;">接待亮点</div>
            <ul style="margin-left:0;list-style:none;padding:0;">
              ${d.top_highlights.map(h => `<li style="font-size:13px;padding:4px 0;border-bottom:1px solid #d4eada;color:#2d5a3d;line-height:1.6;">✓ ${escapeHtml(h)}</li>`).join('')}
            </ul>
          </div>
        ` : '<div></div>'}
        ${d.top_improvements && d.top_improvements.length ? `
          <div style="background:#fff8f0;border-radius:var(--radius-sm);padding:14px 16px;">
            <div style="font-size:11px;font-weight:700;color:#b85c1a;letter-spacing:1px;margin-bottom:8px;">待改进</div>
            <ul style="margin-left:0;list-style:none;padding:0;">
              ${d.top_improvements.map(i => `<li style="font-size:13px;padding:4px 0;border-bottom:1px solid #f5dfc0;color:#7a4a1a;line-height:1.6;">→ ${escapeHtml(i)}</li>`).join('')}
            </ul>
          </div>
        ` : '<div></div>'}
      </div>
    ` : ''}

    <!-- 接待概况 -->
    <div class="collapsible open" style="margin-bottom:16px;">
      <div class="collapsible-header" onclick="toggleCollapsible(this)">
        <span>接待概况</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content">
        <div class="info-list">
          ${overview.duration ? `<div class="info-item"><span class="info-label">接待时长</span><span class="info-value">${overview.duration}</span></div>` : ''}
          ${overview.client_type ? `<div class="info-item"><span class="info-label">客户类型</span><span class="info-value">${overview.client_type}</span></div>` : ''}
          ${overview.atmosphere ? `<div class="info-item"><span class="info-label">整体氛围</span><span class="info-value">${overview.atmosphere}</span></div>` : ''}
          ${overview.engagement ? `<div class="info-item"><span class="info-label">参与度</span><span class="info-value">
            <span class="badge badge-${overview.engagement === '高' ? 'success' : overview.engagement === '中' ? 'warning' : 'muted'}">${overview.engagement}</span>
          </span></div>` : ''}
        </div>
      </div></div>
    </div>

    ${d.effective_aspects && d.effective_aspects.length ? renderObjectList(
      `有效环节 (${d.effective_aspects.length})`,
      d.effective_aspects,
      item => `<b>${item.aspect}</b>：${item.description || ''}`
    ) : ''}

    ${d.needs_improvement && d.needs_improvement.length ? renderObjectList(
      `需调优环节 (${d.needs_improvement.length})`,
      d.needs_improvement,
      item => `<span class="badge badge-${item.severity === '高' ? 'danger' : item.severity === '中' ? 'warning' : 'muted'}" style="margin-right:8px;">${item.severity || '-'}</span><b>${item.aspect}</b>：${item.issue || ''}`
    ) : ''}

    <!-- 讲解员表现 -->
    ${(guide.overall || (guide.highlights && guide.highlights.length) || (guide.improvements && guide.improvements.length)) ? `
      <div class="collapsible open" style="margin-bottom:16px;">
        <div class="collapsible-header" onclick="toggleCollapsible(this)">
          <span>讲解员表现</span>
          <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="collapsible-body"><div class="collapsible-content">
          ${guide.overall ? `<p style="line-height:1.8;margin-bottom:12px;">${guide.overall}</p>` : ''}
          ${guide.highlights && guide.highlights.length ? `
            <div style="margin-bottom:12px;"><b style="font-size:13px;color:var(--success);">✓ 亮点</b>
              <ul style="margin:6px 0 0 20px;line-height:2;">${guide.highlights.map(h => `<li>${h}</li>`).join('')}</ul>
            </div>` : ''}
          ${guide.improvements && guide.improvements.length ? `
            <div><b style="font-size:13px;color:var(--warning);">→ 改进方向</b>
              <ul style="margin:6px 0 0 20px;line-height:2;">${guide.improvements.map(i => `<li>${i}</li>`).join('')}</ul>
            </div>` : ''}
        </div></div>
      </div>
    ` : ''}

    ${d.optimization_suggestions && d.optimization_suggestions.length ? renderObjectList(
      `优化建议 (${d.optimization_suggestions.length})`,
      d.optimization_suggestions,
      item => `<span class="badge badge-${item.priority === '高' ? 'danger' : item.priority === '中' ? 'warning' : 'muted'}" style="margin-right:8px;">${item.priority || '-'}</span><b>${item.area}</b>：${item.suggestion || ''}`
    ) : ''}
  `;
}

// ==================== 编辑模式 ====================

function enterEditMode(type, reportId) {
  document.getElementById(`view-${type}`).style.display = 'none';
  document.getElementById(`edit-${type}`).style.display = 'block';
  document.getElementById(`toolbar-view-${type}`).style.display = 'none';
  document.getElementById(`toolbar-edit-${type}`).style.display = 'flex';

  // 生成编辑表单
  const report = currentReports[type];
  if (!report) return;
  const mergedData = mergeReportData(report.data, report.user_edited_data);
  document.getElementById(`edit-fields-${type}`).innerHTML = renderEditFields(type, mergedData);
}

function exitEditMode(type) {
  document.getElementById(`view-${type}`).style.display = 'block';
  document.getElementById(`edit-${type}`).style.display = 'none';
  document.getElementById(`toolbar-view-${type}`).style.display = 'flex';
  document.getElementById(`toolbar-edit-${type}`).style.display = 'none';
  stopVoiceInput(type);
}

function renderEditFields(type, data) {
  switch (type) {
    case 'customer_brief':       return renderCustomerBriefEditFields(data);
    case 'business_opportunity': return renderBusinessOpportunityEditFields(data);
    case 'reception_review':     return renderReceptionReviewEditFields(data);
    default: return '';
  }
}

// 参观简报编辑字段
function renderCustomerBriefEditFields(d) {
  const gi = d.guest_info || {};
  const gf = d.guest_feedback || {};
  return `
    <div class="edit-section">
      <h4 class="edit-section-title">基本信息</h4>
      ${editField('reception_time', '接待时间', d.reception_time, 'input', '如：2025年5月8日下午')}
      ${editField('reception_location', '接待地点', d.reception_location, 'input', '如：北京展厅 / 上海体验中心')}
      ${editField('reception_theme', '接待主题', d.reception_theme, 'input', '如：参观智慧展厅暨产品交流会')}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">来访嘉宾信息</h4>
      ${editField('guest_info.organization', '来访单位', gi.organization, 'input', '来访机构或公司名称')}
      ${editField('guest_info.key_guests', '主要嘉宾', gi.key_guests ? gi.key_guests.join('\n') : '', 'textarea', '每行一位，如：张总（董事长）', 2)}
      ${editField('guest_info.group_size', '来访人数', gi.group_size, 'input', '如：12人')}
      ${editField('guest_info.guest_background', '来访背景', gi.guest_background, 'textarea', '一句话描述来访方背景', 2)}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">活动内容</h4>
      ${editField('overview', '活动概述', d.overview, 'textarea', '官方报道风格，2-3句话概述', 4)}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">合作成果与跟进</h4>
      ${editField('cooperation_outcomes', '促成合作', d.cooperation_outcomes ? d.cooperation_outcomes.join('\n') : '', 'textarea', '每行一条合作事项', 3)}
      ${editField('next_steps', '后续跟进', d.next_steps ? d.next_steps.join('\n') : '', 'textarea', '每行一条跟进事项', 3)}
    </div>
  `;
}

// 商机简报编辑字段
function renderBusinessOpportunityEditFields(d) {
  return `
    <div class="edit-section">
      <h4 class="edit-section-title">讨论概述</h4>
      ${editField('discussion_overview', '讨论要点', d.discussion_overview, 'textarea', '3-5条要点概述', 4)}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">客户行为</h4>
      ${editField('questions_asked', '客户提问', d.questions_asked ? d.questions_asked.join('\n') : '', 'textarea', '每行一个问题', 4)}
      ${editField('interest_points', '感兴趣点', d.interest_points ? d.interest_points.join('\n') : '', 'textarea', '每行一个兴趣点', 3)}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">跟进动作</h4>
      ${editField('next_actions_text', '下一步行动', d.next_actions ? d.next_actions.map(a => `[${a.priority||'中'}] ${a.action}${a.notes ? ' — '+a.notes : ''}`).join('\n') : '', 'textarea', '格式：[高/中/低] 动作描述 — 备注', 4)}
    </div>
  `;
}

// 复盘简报编辑字段
function renderReceptionReviewEditFields(d) {
  const ov = d.reception_overview || {};
  const gp = d.guide_performance || {};
  return `
    <div class="edit-section">
      <h4 class="edit-section-title">接待概况</h4>
      ${editField('reception_overview.duration', '接待时长', ov.duration, 'input', '如：约45分钟')}
      ${editField('reception_overview.client_type', '客户类型', ov.client_type, 'input', '如：采购决策者、政府考察团')}
      ${editField('reception_overview.atmosphere', '整体氛围', ov.atmosphere, 'input', '如：积极热情、审慎观察')}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">讲解员表现</h4>
      ${editField('guide_performance.overall', '整体评价', gp.overall, 'textarea', '综合评价讲解员表现', 3)}
      ${editField('guide_performance.highlights', '表现亮点', gp.highlights ? gp.highlights.join('\n') : '', 'textarea', '每行一条亮点', 3)}
      ${editField('guide_performance.improvements', '改进方向', gp.improvements ? gp.improvements.join('\n') : '', 'textarea', '每行一条改进建议', 3)}
    </div>
    <div class="edit-section">
      <h4 class="edit-section-title">优化方向</h4>
      ${editField('optimization_text', '优化建议', d.optimization_suggestions ? d.optimization_suggestions.map(s => `[${s.priority||'中'}] ${s.area}：${s.suggestion}`).join('\n') : '', 'textarea', '格式：[高/中/低] 优化方向：具体建议', 5)}
    </div>
  `;
}

function editField(key, label, value, type = 'input', placeholder = '', rows = 3) {
  const safeVal = value !== null && value !== undefined ? escapeHtml(String(value)) : '';
  const isEmpty = !value || (typeof value === 'string' && value.trim() === '');
  return `
    <div class="edit-field ${isEmpty ? 'field-empty' : ''}">
      <label class="edit-field-label">
        ${label}
        ${isEmpty ? '<span class="badge-manual">待补充</span>' : ''}
      </label>
      ${type === 'textarea'
        ? `<textarea name="${key}" rows="${rows}" class="edit-input" placeholder="${placeholder}">${safeVal}</textarea>`
        : `<input type="text" name="${key}" class="edit-input" value="${safeVal}" placeholder="${placeholder}">`
      }
    </div>
  `;
}

async function saveReport(type, reportId) {
  const editContainer = document.getElementById(`edit-fields-${type}`);
  const inputs = editContainer.querySelectorAll('[name]');
  const rawData = {};
  inputs.forEach(el => { rawData[el.name] = el.value; });

  // 将扁平化的 rawData 构建成嵌套结构
  const userEditedData = buildEditedData(type, rawData);
  const supplementaryText = document.getElementById(`supp-text-${type}`).value;

  const payload = { user_edited_data: userEditedData, supplementary_text: supplementaryText };
  if (type === 'reception_review') {
    const expertNotesEl = document.getElementById(`expert-notes-${type}`);
    if (expertNotesEl) {
      payload.expert_notes = expertNotesEl.value;
    }
  }

  try {
    await apiRequest(`/admin/reports/${reportId}/edit`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    });

    showToast('保存成功', 'success');

    // 刷新当前报告数据
    const detail = await apiRequest(`/admin/files/${currentFileId}/detail`);
    const report = (detail.reports || {})[type];
    if (report) {
      currentReports[type] = report;
      const mergedData = mergeReportData(report.data, report.user_edited_data);
      document.getElementById(`content-${type}`).innerHTML = renderReportPanel(type, report.report_id, mergedData, report);
      bindPanelEvents(type, report.report_id);
    }
  } catch (err) {
    showToast('保存失败：' + err.message, 'error');
  }
}

function buildEditedData(type, raw) {
  const result = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!value || value.trim() === '') continue;
    // 支持 "guest_info.organization" 这样的嵌套 key
    const parts = key.split('.');
    let obj = result;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!obj[parts[i]]) obj[parts[i]] = {};
      obj = obj[parts[i]];
    }
    const lastKey = parts[parts.length - 1];
    // 多行字段转数组
    const multilineKeys = ['key_guests', 'cooperation_outcomes', 'next_steps', 'questions_asked',
      'interest_points', 'highlights', 'improvements', 'next_actions_text', 'optimization_text'];
    if (multilineKeys.includes(lastKey)) {
      obj[lastKey] = value.split('\n').map(s => s.trim()).filter(Boolean);
    } else {
      obj[lastKey] = value.trim();
    }
  }
  return result;
}

// ==================== 语音输入 ====================

function toggleVoiceInput(type) {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('当前浏览器不支持语音输入，请使用 Chrome 浏览器', 'warning');
    return;
  }

  if (speechRecognizing && speechRecognition) {
    stopVoiceInput(type);
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  speechRecognition = new SpeechRecognition();
  speechRecognition.lang = 'zh-CN';
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;

  const textarea = document.getElementById(`supp-text-${type}`);
  const statusEl = document.getElementById(`voice-status-${type}`);
  const btn = document.getElementById(`voice-btn-${type}`);
  let finalText = textarea.value;

  speechRecognition.onstart = () => {
    speechRecognizing = true;
    statusEl.style.display = 'block';
    btn.textContent = '⏹ 停止';
    btn.style.color = 'var(--danger)';
  };

  speechRecognition.onresult = (event) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        finalText += event.results[i][0].transcript;
      } else {
        interim = event.results[i][0].transcript;
      }
    }
    textarea.value = finalText + interim;
  };

  speechRecognition.onend = () => {
    textarea.value = finalText;
    stopVoiceInput(type);
  };

  speechRecognition.onerror = () => {
    showToast('语音识别出错，请重试', 'error');
    stopVoiceInput(type);
  };

  speechRecognition.start();
}

function stopVoiceInput(type) {
  if (speechRecognition) {
    speechRecognition.stop();
    speechRecognition = null;
  }
  speechRecognizing = false;
  const statusEl = document.getElementById(`voice-status-${type}`);
  const btn = document.getElementById(`voice-btn-${type}`);
  if (statusEl) statusEl.style.display = 'none';
  if (btn) { btn.textContent = '🎤 语音'; btn.style.color = ''; }
}

async function organizeExpertNotes(type, reportId) {
  const textarea = document.getElementById(`expert-notes-${type}`);
  const statusEl = document.getElementById(`organize-status-${type}`);
  const btn = document.getElementById(`btn-organize-${type}`);

  if (!textarea || !textarea.value.trim()) {
    showToast('请先填写专家讲解内容', 'warning');
    return;
  }

  // 先保存当前内容
  try {
    btn.disabled = true;
    statusEl.style.display = 'inline-flex';

    await apiRequest(`/admin/reports/${reportId}/expert-notes`, {
      method: 'PATCH',
      body: JSON.stringify({ expert_notes: textarea.value })
    });

    const result = await apiRequest(`/admin/reports/${reportId}/expert-notes/organize`, {
      method: 'POST'
    });

    if (result.success && result.organized_text) {
      textarea.value = result.organized_text;
      showToast('AI整理完成', 'success');
    } else {
      showToast('整理未返回结果，已保留原文', 'warning');
    }
  } catch (err) {
    showToast('AI整理失败：' + err.message, 'error');
  } finally {
    btn.disabled = false;
    statusEl.style.display = 'none';
  }
}

// ==================== 照片管理 ====================

function renderPhotosView(photos, type) {
  if (!photos || photos.length === 0) return '';
  return `
    <div class="collapsible open" style="margin-bottom:16px;">
      <div class="collapsible-header" onclick="toggleCollapsible(this)">
        <span>照片 (${photos.length})</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content">
        <div class="photos-grid">
          ${photos.map(p => `
            <div class="photo-thumb">
              <img src="${p.url}" alt="${escapeHtml(p.caption || '')}" loading="lazy"
                onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect fill=%22%23eee%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2255%22 text-anchor=%22middle%22 fill=%22%23999%22>图片</text></svg>'">
              ${p.caption ? `<div class="photo-caption">${escapeHtml(p.caption)}</div>` : ''}
            </div>
          `).join('')}
        </div>
      </div></div>
    </div>
  `;
}

function renderPhotosEdit(photos, reportId, type) {
  if (!photos || photos.length === 0) return '<div style="color:var(--muted);font-size:13px;margin-bottom:8px;">暂无照片</div>';
  return `
    <div class="photos-grid" id="photos-grid-${type}" data-report-id="${reportId}" data-type="${type}"
      ondragover="handlePhotoDragOver(event,'${type}')" ondrop="handlePhotoDropSort(event,'${type}')">
      ${photos.map(p => `
        <div class="photo-thumb photo-thumb-edit" id="photo-item-${p.id}"
          draggable="true"
          ondragstart="handlePhotoDragStart(event,'${p.id}','${type}')"
          ondragend="handlePhotoDragEnd(event,'${type}')"
        >
          <div class="drag-handle" style="position:absolute;top:4px;left:4px;background:rgba(0,0,0,0.4);color:#fff;border-radius:4px;padding:2px 6px;font-size:11px;cursor:move;z-index:5;">⋮⋮</div>
          <img src="${p.url}" alt="${escapeHtml(p.caption || '')}" loading="lazy"
            onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><rect fill=%22%23eee%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2255%22 text-anchor=%22middle%22 fill=%22%23999%22>图片</text></svg>'">
          <input type="text" value="${escapeHtml(p.caption || '')}" placeholder="图片说明（可选）"
            class="photo-caption-input"
            onchange="updatePhotoCaption('${reportId}','${p.id}',this.value,'${type}')">
          <button class="btn-photo-delete" onclick="deletePhoto('${reportId}','${p.id}','${type}')" title="删除">✕</button>
        </div>
      `).join('')}
    </div>
    <div style="font-size:12px;color:var(--muted);margin-top:6px;">提示：拖拽 ⋮⋮ 可调整照片顺序</div>
  `;
}

// ==================== 照片拖拽排序 ====================

let _dragPhotoId = null;
let _dragType = null;

function handlePhotoDragStart(event, photoId, type) {
  _dragPhotoId = photoId;
  _dragType = type;
  event.dataTransfer.effectAllowed = 'move';
  event.target.style.opacity = '0.5';
}

function handlePhotoDragEnd(event, type) {
  event.target.style.opacity = '1';
  _dragPhotoId = null;
  _dragType = null;
}

function handlePhotoDragOver(event, type) {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
}

function handlePhotoDropSort(event, type) {
  event.preventDefault();
  if (!_dragPhotoId || _dragType !== type) return;

  const grid = document.getElementById(`photos-grid-${type}`);
  if (!grid) return;

  // 找到放置目标元素
  const targetEl = event.target.closest('.photo-thumb-edit');
  const draggedEl = document.getElementById(`photo-item-${_dragPhotoId}`);
  if (!draggedEl || draggedEl === targetEl) return;

  // 在DOM中重新排序
  if (targetEl) {
    const rect = targetEl.getBoundingClientRect();
    const afterDrop = event.clientY > rect.top + rect.height / 2;
    if (afterDrop) {
      targetEl.after(draggedEl);
    } else {
      targetEl.before(draggedEl);
    }
  }

  // 收集新的顺序
  const newOrder = Array.from(grid.querySelectorAll('.photo-thumb-edit')).map(el => {
    const m = el.id.match(/^photo-item-(.+)$/);
    return m ? m[1] : null;
  }).filter(Boolean);

  const reportId = grid.dataset.reportId;
  savePhotoOrder(reportId, newOrder, type);
}

async function savePhotoOrder(reportId, photoIds, type) {
  try {
    await apiRequest(`/admin/reports/${reportId}/reorder-photos`, {
      method: 'POST',
      body: JSON.stringify({ photo_ids: photoIds })
    });
    showToast('照片顺序已保存', 'success');
  } catch (err) {
    showToast('保存顺序失败：' + err.message, 'error');
  }
}

async function regenerateSharePage(type, reportId) {
  const btn = document.querySelector(`#toolbar-view-${type} [onclick*="regenerateSharePage"]`);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }

  try {
    const result = await apiRequest(`/admin/reports/${reportId}/generate-share?force=true`, { method: 'POST' });
    if (currentReports[type]) {
      currentReports[type].share_id = result.share_id;
    }
    showToast('分享页已重新生成', 'success');
    openSharePreview(type);
    // 刷新工具栏按钮
    if (btn) {
      btn.textContent = '🔄 重新生成';
      btn.disabled = false;
    }
  } catch (err) {
    showToast('重新生成失败：' + err.message, 'error');
    if (btn) { btn.textContent = '🔄 重新生成'; btn.disabled = false; }
  }
}

function switchPhotoTab(type, tab, btn) {
  document.querySelectorAll(`#photo-tab-local-${type}, #photo-tab-url-${type}`).forEach(el => el.style.display = 'none');
  document.getElementById(`photo-tab-${tab}-${type}`).style.display = 'block';
  btn.closest('.tabs').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

async function handlePhotoFileSelect(event, type, reportId) {
  const files = Array.from(event.target.files);
  for (const file of files) {
    await uploadPhotoFile(file, reportId, type);
  }
  event.target.value = '';
}

async function handlePhotoDrop(event, type, reportId) {
  event.preventDefault();
  document.getElementById(`drop-zone-${type}`).classList.remove('drag-over');
  const files = Array.from(event.dataTransfer.files).filter(f => f.type.startsWith('image/'));
  for (const file of files) {
    await uploadPhotoFile(file, reportId, type);
  }
}

async function uploadPhotoFile(file, reportId, type) {
  const formData = new FormData();
  formData.append('file', file);
  try {
    await apiRequest(`/admin/reports/${reportId}/photos`, { method: 'POST', body: formData });
    await refreshPhotos(reportId, type);
    showToast('照片上传成功', 'success');
  } catch (err) {
    showToast('照片上传失败：' + err.message, 'error');
  }
}

async function handlePhotoUrl(type, reportId) {
  const input = document.getElementById(`photo-url-input-${type}`);
  const url = input.value.trim();
  if (!url) { showToast('请输入图片 URL', 'warning'); return; }
  try {
    await apiRequest(`/admin/reports/${reportId}/photos/url`, {
      method: 'POST',
      body: JSON.stringify({ url })
    });
    input.value = '';
    await refreshPhotos(reportId, type);
    showToast('图片链接已添加', 'success');
  } catch (err) {
    showToast('添加失败：' + err.message, 'error');
  }
}

async function deletePhoto(reportId, photoId, type) {
  try {
    await apiRequest(`/admin/reports/${reportId}/photos/${photoId}`, { method: 'DELETE' });
    await refreshPhotos(reportId, type);
    showToast('照片已删除', 'success');
  } catch (err) {
    showToast('删除失败：' + err.message, 'error');
  }
}

async function updatePhotoCaption(reportId, photoId, caption, type) {
  try {
    await apiRequest(`/admin/reports/${reportId}/photos/${photoId}/caption`, {
      method: 'PATCH',
      body: JSON.stringify({ caption })
    });
  } catch (err) {
    console.error('更新说明失败', err);
  }
}

async function refreshPhotos(reportId, type) {
  const detail = await apiRequest(`/admin/files/${currentFileId}/detail`);
  const report = (detail.reports || {})[type];
  if (report) {
    currentReports[type] = report;
    const photos = report.photos || [];
    document.getElementById(`photos-edit-${type}`).innerHTML = renderPhotosEdit(photos, reportId, type);
    // 同步更新查看模式
    const mergedData = mergeReportData(report.data, report.user_edited_data);
    document.getElementById(`view-${type}`).querySelector('.photos-view-placeholder')?.remove?.();
  }
}

// ==================== 生成分享报告 ====================

async function generateSharePage(type, reportId) {
  const btn = document.querySelector(`#toolbar-view-${type} [onclick*="generateSharePage"]`);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }

  try {
    const result = await apiRequest(`/admin/reports/${reportId}/generate-share`, { method: 'POST' });
    // Cache share_id locally so subsequent clicks skip the API call
    if (currentReports[type]) {
      currentReports[type].share_id = result.share_id;
    }
    // Swap the toolbar button to "查看分享报告"
    if (btn) {
      btn.onclick = () => openSharePreview(type);
      btn.textContent = '📱 查看分享报告';
      btn.disabled = false;
    }
    openPhonePreview(result.share_url);
  } catch (err) {
    showToast('生成失败：' + err.message, 'error');
    if (btn) { btn.textContent = '🔗 生成分享报告'; btn.disabled = false; }
  }
}

function openSharePreview(type) {
  const report = currentReports[type];
  if (!report || !report.share_id) {
    showToast('分享页尚未生成', 'warning');
    return;
  }
  openPhonePreview(`/share/${report.share_id}`);
}

let currentShareUrl = '';

function openPhonePreview(shareUrl) {
  // Always build a full absolute URL for sharing
  currentShareUrl = shareUrl.startsWith('http') ? shareUrl : (window.location.origin + shareUrl);
  document.getElementById('share-preview-iframe').src = shareUrl;
  document.getElementById('phone-preview-modal').style.display = 'flex';

  const copyBtn = document.getElementById('copy-share-link');
  const SHARE_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg> 分享`;
  copyBtn.innerHTML = SHARE_ICON;
  copyBtn.onclick = () => {
    const url = currentShareUrl;
    const onSuccess = () => {
      copyBtn.innerHTML = '✓ 已复制！';
      setTimeout(() => { copyBtn.innerHTML = SHARE_ICON; }, 2000);
    };
    // 优先使用 Clipboard API（需 HTTPS），不可用时降级到 execCommand
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(onSuccess).catch(() => _fallbackCopy(url, onSuccess));
      } else {
        _fallbackCopy(url, onSuccess);
      }
    } catch (e) {
      _fallbackCopy(url, onSuccess);
    }
  };
}

function _fallbackCopy(text, onSuccess) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    if (document.execCommand('copy')) {
      onSuccess && onSuccess();
    } else {
      prompt('请手动复制链接：', text);
    }
  } catch (e) {
    prompt('请手动复制链接：', text);
  }
  document.body.removeChild(ta);
}

function closePhonePreview() {
  document.getElementById('phone-preview-modal').style.display = 'none';
  document.getElementById('share-preview-iframe').src = '';
}

// ==================== UI 组件 ====================

function infoCard(title, text) {
  if (!text) return '';
  return `
    <div class="collapsible open" style="margin-bottom:16px;">
      <div class="collapsible-header" onclick="toggleCollapsible(this)">
        <span>${title}</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content" style="line-height:1.8;">${escapeHtml(text)}</div></div>
    </div>`;
}

function listCard(title, items, badgeClass) {
  if (!items || items.length === 0) return '';
  const inner = badgeClass
    ? items.map(i => `<span class="badge ${badgeClass}" style="margin:3px;">${escapeHtml(i)}</span>`).join('')
    : `<ul style="margin-left:20px;line-height:2;">${items.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>`;
  return `
    <div class="collapsible open" style="margin-bottom:16px;">
      <div class="collapsible-header" onclick="toggleCollapsible(this)">
        <span>${title} (${items.length})</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content">${inner}</div></div>
    </div>`;
}

function renderObjectList(title, items, renderFn) {
  if (!items || items.length === 0) return '';
  return `
    <div class="collapsible open" style="margin-bottom:16px;">
      <div class="collapsible-header" onclick="toggleCollapsible(this)">
        <span>${title}</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content">
        <ul style="margin-left:20px;line-height:2.2;">
          ${items.map(item => `<li style="margin-bottom:8px;">${renderFn(item)}</li>`).join('')}
        </ul>
      </div></div>
    </div>`;
}

function renderRawJson(data) {
  return `<pre style="background:var(--surface-2);padding:16px;border-radius:8px;overflow:auto;font-size:12px;">${JSON.stringify(data, null, 2)}</pre>`;
}

function toggleCollapsible(header) {
  header.parentElement.classList.toggle('open');
}

function getStatusBadge(status) {
  const map = {
    completed:  '<span class="badge badge-success">已完成</span>',
    pending:    '<span class="badge badge-warning">待处理</span>',
    processing: '<span class="badge badge-warning">处理中</span>',
    failed:     '<span class="badge badge-danger">失败</span>'
  };
  return map[status] || `<span class="badge badge-muted">${status || '未知'}</span>`;
}

// ==================== AI 辅助补录 ====================

function _getMissingFieldLabels(type, data) {
  if (!data) return [];
  const missing = [];
  if (type === 'customer_brief') {
    if (!data.reception_time) missing.push('接待时间');
    if (!data.reception_location) missing.push('接待地点');
    if (!data.reception_theme) missing.push('接待主题');
    const gi = data.guest_info || {};
    if (!gi.organization) missing.push('来访单位');
    if (!gi.key_guests || !gi.key_guests.length) missing.push('主要嘉宾');
    if (!gi.group_size) missing.push('来访人数');
  } else if (type === 'business_opportunity') {
    if (!data.discussion_overview) missing.push('讨论要点');
  } else if (type === 'reception_review') {
    const ov = data.reception_overview || {};
    if (!ov.duration) missing.push('接待时长');
    if (!ov.client_type) missing.push('客户类型');
  }
  return missing;
}

function renderAiSupplementPanel(type, reportId, reportMeta) {
  const data = mergeReportData(reportMeta.data, reportMeta.user_edited_data);
  const missing = _getMissingFieldLabels(type, data);
  const missingHtml = missing.length
    ? `<div style="font-size:12px;color:var(--warning,#c9a227);margin-bottom:10px;">
        待补充字段：${missing.map(f => `<span style="background:var(--accent-muted,#fff3e0);padding:1px 7px;border-radius:10px;margin-right:4px;">${f}</span>`).join('')}
       </div>`
    : `<div style="font-size:12px;color:var(--muted);margin-bottom:10px;">所有字段均已填写，你仍可输入更多内容让 AI 更新</div>`;

  const placeholder = type === 'customer_brief'
    ? '例如：今天下午3点，来自上海某科技公司的张总（CEO）一行5人前来参观，双方就智能制造展区进行了深入交流...'
    : type === 'business_opportunity'
    ? '例如：客户对我们的供应链管理模块非常感兴趣，提出了关于系统集成和价格方面的问题...'
    : '例如：本次接待约1小时，来访方为政府考察团，整体氛围积极，讲解员在互动环节表现出色...';

  return `
    <div class="collapsible open" id="ai-panel-${type}" style="margin-bottom:16px;border:1.5px solid var(--accent,#C45D3E);border-radius:var(--radius-sm,8px);">
      <div class="collapsible-header" onclick="toggleCollapsible(this)" style="background:var(--accent-muted,#fff8f5);">
        <span style="font-weight:700;color:var(--accent-dark,#9b3d22);">✨ AI 辅助补录</span>
        <svg class="collapsible-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="collapsible-body"><div class="collapsible-content" style="padding-top:4px;">
        ${missingHtml}
        <div style="font-size:12px;color:var(--muted);margin-bottom:8px;">描述本次接待情况，AI 将自动识别并回填缺失字段，你再确认后保存</div>
        <div style="position:relative;margin-bottom:10px;">
          <textarea
            id="ai-supp-input-${type}"
            rows="4"
            style="width:100%;padding:10px 44px 10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm,6px);font-family:var(--font-body);font-size:13px;resize:vertical;line-height:1.7;"
            placeholder="${placeholder}"></textarea>
          <button
            class="btn btn-ghost btn-sm"
            id="ai-voice-btn-${type}"
            title="语音输入"
            style="position:absolute;right:6px;bottom:8px;padding:4px 8px;"
            onclick="toggleAiVoiceInput('${type}')">🎤</button>
        </div>
        <div id="ai-voice-status-${type}" style="font-size:12px;color:var(--danger,#d64545);margin-bottom:6px;display:none;">● 录音中，点击麦克风停止</div>
        <button
          class="btn btn-primary btn-sm"
          id="ai-extract-btn-${type}"
          onclick="runAiExtract('${type}','${reportId}')"
          style="width:100%;justify-content:center;">
          ✨ AI提取并自动回填
        </button>
      </div></div>
    </div>`;
}

let _aiSpeechRec = null;
let _aiSpeechRecognizing = false;

function toggleAiVoiceInput(type) {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('当前浏览器不支持语音输入，请使用 Chrome', 'warning');
    return;
  }
  if (_aiSpeechRecognizing && _aiSpeechRec) {
    _stopAiVoiceInput(type);
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  _aiSpeechRec = new SpeechRecognition();
  _aiSpeechRec.lang = 'zh-CN';
  _aiSpeechRec.continuous = true;
  _aiSpeechRec.interimResults = true;

  const textarea = document.getElementById(`ai-supp-input-${type}`);
  const statusEl = document.getElementById(`ai-voice-status-${type}`);
  const btn = document.getElementById(`ai-voice-btn-${type}`);
  let finalText = textarea.value;

  _aiSpeechRec.onstart = () => {
    _aiSpeechRecognizing = true;
    statusEl.style.display = 'block';
    btn.textContent = '⏹';
    btn.style.color = 'var(--danger,#d64545)';
  };
  _aiSpeechRec.onresult = (event) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else interim = event.results[i][0].transcript;
    }
    textarea.value = finalText + interim;
  };
  _aiSpeechRec.onend = () => { textarea.value = finalText; _stopAiVoiceInput(type); };
  _aiSpeechRec.onerror = () => { showToast('语音识别出错，请重试', 'error'); _stopAiVoiceInput(type); };
  _aiSpeechRec.start();
}

function _stopAiVoiceInput(type) {
  if (_aiSpeechRec) { _aiSpeechRec.stop(); _aiSpeechRec = null; }
  _aiSpeechRecognizing = false;
  const statusEl = document.getElementById(`ai-voice-status-${type}`);
  const btn = document.getElementById(`ai-voice-btn-${type}`);
  if (statusEl) statusEl.style.display = 'none';
  if (btn) { btn.textContent = '🎤'; btn.style.color = ''; }
}

async function runAiExtract(type, reportId) {
  const textarea = document.getElementById(`ai-supp-input-${type}`);
  const btn = document.getElementById(`ai-extract-btn-${type}`);
  if (!textarea || !textarea.value.trim()) {
    showToast('请先输入补充说明文字', 'warning');
    return;
  }
  btn.disabled = true;
  btn.textContent = '⏳ AI提取中...';

  try {
    const result = await apiRequest(`/admin/reports/${reportId}/ai-extract`, {
      method: 'POST',
      body: JSON.stringify({ supplement_text: textarea.value.trim() })
    });

    if (!result.success || !result.extracted_data) {
      showToast('AI提取未返回有效结果，请重试', 'warning');
      return;
    }

    const count = (result.extracted_fields || []).length;
    showToast(`AI提取完成，识别到 ${count} 个字段，请在编辑模式确认后保存`, 'success');

    // 进入编辑模式，然后预填字段
    enterEditMode(type, reportId);
    _prefillEditFields(type, result.extracted_data);

  } catch (err) {
    showToast('AI提取失败：' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '✨ AI提取并自动回填';
  }
}

function _prefillEditFields(type, extractedData) {
  if (!extractedData) return;

  // 将嵌套对象扁平化为 "guest_info.organization" 格式（数组不继续展开）
  function flattenObj(obj, prefix) {
    const result = {};
    for (const [k, v] of Object.entries(obj || {})) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
        Object.assign(result, flattenObj(v, key));
      } else {
        result[key] = v;
      }
    }
    return result;
  }

  // 编辑表单中某些字段名与 AI 返回的 key 不同，需要特殊映射
  const KEY_REMAP = {
    // 商机简报：next_actions 对象数组 → next_actions_text 格式化文本
    'next_actions': (val) => {
      if (!Array.isArray(val)) return null;
      return {
        key: 'next_actions_text',
        value: val.map(a => {
          const pri = a.priority || '中';
          const act = a.action || '';
          const notes = a.notes ? ` — ${a.notes}` : '';
          return `[${pri}] ${act}${notes}`;
        }).join('\n')
      };
    }
  };

  const flat = flattenObj(extractedData, '');

  function applyToEl(el, val) {
    if (val === null || val === undefined || val === '') return;
    if (Array.isArray(val)) {
      el.value = val.map(v => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join('\n');
    } else {
      el.value = String(val);
    }
    el.style.borderColor = 'var(--success,#4a7c59)';
    el.style.boxShadow = '0 0 0 2px rgba(74,124,89,0.15)';
    el.addEventListener('input', () => { el.style.borderColor = ''; el.style.boxShadow = ''; }, { once: true });
  }

  for (const [fieldKey, val] of Object.entries(flat)) {
    if (val === null || val === undefined || val === '') continue;

    // 检查是否需要特殊 remap
    if (KEY_REMAP[fieldKey]) {
      const remapped = KEY_REMAP[fieldKey](val);
      if (remapped) {
        const el = document.querySelector(`[name="${remapped.key}"]`);
        if (el) applyToEl(el, remapped.value);
      }
      continue;
    }

    const el = document.querySelector(`[name="${fieldKey}"]`);
    if (!el) continue;
    applyToEl(el, val);
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

