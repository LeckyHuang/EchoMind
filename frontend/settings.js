async function initSettings() {
  if (!requireAuth()) return;
  
  setPageTitle('系统设置');
  
  const main = getMainContent();
  main.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">系统设置</h1>
    </div>
    
    <div style="max-width: 720px;">
      <!-- Cleanup Settings -->
      <div class="settings-section fade-in">
        <div class="settings-section-header">清理设置</div>
        <div class="settings-section-body">
          <div class="form-group">
            <label class="form-label" for="cleanup-expire-hours">文件过期时间（小时）</label>
            <div style="display: flex; gap: 12px; align-items: center;">
              <input type="number" id="cleanup-expire-hours" class="form-input" style="max-width: 160px;" min="1" placeholder="例如: 168">
              <span style="color: var(--muted); font-size: 0.85rem;">超过此时间的录音物理文件将被自动清理（分析报告与记录永久保留）</span>
            </div>
          </div>
          
          <div class="form-group">
            <label class="form-label" for="cleanup-cron">Cron 表达式</label>
            <div style="display: flex; gap: 12px; align-items: center;">
              <input type="text" id="cleanup-cron" class="form-input" style="max-width: 200px; font-family: var(--font-mono);" placeholder="0 2 * * *">
              <span style="color: var(--muted); font-size: 0.85rem;">每天凌晨2点执行清理任务</span>
            </div>
          </div>
          
          <button class="btn btn-primary" id="save-cleanup-btn" onclick="saveCleanupSettings()">
            保存清理设置
          </button>
        </div>
      </div>
      
      <!-- Prompt Template Settings -->
      <div class="settings-section fade-in" style="animation-delay: 0.08s;">
        <div class="settings-section-header">Prompt 激活模板</div>
        <div class="settings-section-body">
          <div class="form-group">
            <label class="form-label" for="active-prompt">当前激活的 Prompt 模板</label>
            <select id="active-prompt" class="form-select" style="max-width: 320px;">
              <option value="">加载中...</option>
            </select>
            <p style="color: var(--muted); font-size: 0.85rem; margin-top: 8px;">
              选择处理录音时默认使用的 Prompt 模板
            </p>
          </div>
          
          <button class="btn btn-primary" id="save-prompt-btn" onclick="savePromptSettings()">
            保存 Prompt 设置
          </button>
        </div>
      </div>
      
      <!-- Service Providers -->
      <div class="settings-section fade-in" style="animation-delay: 0.16s;">
        <div class="settings-section-header">服务商信息</div>
        <div class="settings-section-body">
          <div id="providers-info">
            <div style="text-align: center; padding: 40px; color: var(--muted);">加载中...</div>
          </div>
        </div>
      </div>
      
      <!-- System Info -->
      <div class="settings-section fade-in" style="animation-delay: 0.24s;">
        <div class="settings-section-header">系统信息</div>
        <div class="settings-section-body">
          <div class="info-list">
            <div class="info-item">
              <span class="info-label">系统版本</span>
              <span class="info-value">v1.0.0</span>
            </div>
            <div class="info-item">
              <span class="info-label">部署环境</span>
              <span class="info-value">生产环境</span>
            </div>
            <div class="info-item">
              <span class="info-label">API 版本</span>
              <span class="info-value" style="font-family: var(--font-mono);">v1</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  
  
  // Load settings
  loadSettings();
  loadPrompts();
  loadProviders();
});

async function loadSettings() {
  try {
    const data = await getSettings();
    
    document.getElementById('cleanup-expire-hours').value = data.cleanup_expire_hours || 168;
    document.getElementById('cleanup-cron').value = data.cleanup_cron || '0 2 * * *';
    
    if (data.active_prompt_id) {
      document.getElementById('active-prompt').value = data.active_prompt_id;
    }
  } catch (error) {
    console.error('Failed to load settings:', error);
    // Use defaults
    document.getElementById('cleanup-expire-hours').value = 168;
    document.getElementById('cleanup-cron').value = '0 2 * * *';
  }
}

async function loadPrompts() {
  const select = document.getElementById('active-prompt');
  
  try {
    const data = await getPrompts();
    const prompts = data.prompts || [];
    
    if (prompts.length === 0) {
      select.innerHTML = '<option value="">暂无可用 Prompt</option>';
      return;
    }
    
    select.innerHTML = `
      <option value="">不指定（使用默认）</option>
      ${prompts.map(p => `
        <option value="${p.id}">${p.name}</option>
      `).join('')}
    `;
  } catch (error) {
    console.error('Failed to load prompts:', error);
    select.innerHTML = '<option value="">加载失败</option>';
  }
}

async function loadProviders() {
  const container = document.getElementById('providers-info');
  
  try {
    const data = await getServiceProviders();
    
    container.innerHTML = `
      <div class="info-list">
        <div class="info-item">
          <span class="info-label">ASR 提供商</span>
          <span class="info-value">${data.asr_provider || '未配置'}</span>
        </div>
        <div class="info-item">
          <span class="info-label">LLM 提供商</span>
          <span class="info-value">${data.llm_provider || '未配置'}</span>
        </div>
        <div class="info-item">
          <span class="info-label">ASR 模型</span>
          <span class="info-value">${data.asr_model || '-'}</span>
        </div>
        <div class="info-item">
          <span class="info-label">LLM 模型</span>
          <span class="info-value">${data.llm_model || '-'}</span>
        </div>
      </div>
    `;
  } catch (error) {
    console.error('Failed to load providers:', error);
    container.innerHTML = `
      <div class="info-list">
        <div class="info-item">
          <span class="info-label">ASR 提供商</span>
          <span class="info-value">Azure Speech</span>
        </div>
        <div class="info-item">
          <span class="info-label">LLM 提供商</span>
          <span class="info-value">OpenAI</span>
        </div>
        <div class="info-item">
          <span class="info-label">ASR 模型</span>
          <span class="info-value">whisper-1</span>
        </div>
        <div class="info-item">
          <span class="info-label">LLM 模型</span>
          <span class="info-value">gpt-4o</span>
        </div>
      </div>
    `;
  }
}

async function saveCleanupSettings() {
  const expireHours = document.getElementById('cleanup-expire-hours').value;
  const cron = document.getElementById('cleanup-cron').value;
  
  if (!expireHours || expireHours < 1) {
    showToast('请输入有效的过期时间', 'warning');
    return;
  }
  
  if (!cron) {
    showToast('请输入 Cron 表达式', 'warning');
    return;
  }
  
  const btn = document.getElementById('save-cleanup-btn');
  btn.disabled = true;
  btn.innerHTML = '<span>保存中...</span>';
  
  try {
    await updateSettings({
      cleanup_expire_hours: parseInt(expireHours),
      cleanup_cron: cron
    });
    showToast('清理设置已保存', 'success');
  } catch (error) {
    showToast(error.message || '保存失败', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '保存清理设置';
  }
}

async function savePromptSettings() {
  const activePromptId = document.getElementById('active-prompt').value;
  
  const btn = document.getElementById('save-prompt-btn');
  btn.disabled = true;
  btn.innerHTML = '<span>保存中...</span>';
  
  try {
    await updateSettings({
      active_prompt_id: activePromptId || null
    });
    showToast('Prompt 设置已保存', 'success');
  } catch (error) {
    showToast(error.message || '保存失败', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '保存 Prompt 设置';
  }
}
