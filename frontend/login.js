document.addEventListener('DOMContentLoaded', () => {
  // If already logged in, redirect to dashboard
  if (getToken()) {
    window.location.href = 'dashboard.html';
    return;
  }
  
  const form = document.getElementById('login-form');
  const loginBtn = document.getElementById('login-btn');
  const errorMessage = document.getElementById('error-message');
  
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    
    if (!username || !password) {
      showError('请输入用户名和密码');
      return;
    }
    
    // Show loading state
    loginBtn.disabled = true;
    loginBtn.innerHTML = '<span>登录中...</span>';
    hideError();
    
    try {
      await login(username, password);
      
      // Success - redirect to dashboard
      window.location.href = 'dashboard.html';
    } catch (error) {
      showError(error.message || '登录失败，请检查用户名和密码');
      loginBtn.disabled = false;
      loginBtn.innerHTML = '<span>登录</span>';
    }
  });
  
  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
  }
  
  function hideError() {
    errorMessage.style.display = 'none';
  }
  
  // Clear error when user starts typing
  document.getElementById('username').addEventListener('input', hideError);
  document.getElementById('password').addEventListener('input', hideError);
});
