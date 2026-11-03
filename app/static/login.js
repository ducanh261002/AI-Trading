document.getElementById('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const password = document.getElementById('password');
  const button = event.target.querySelector('button'); button.disabled = true;
  try {
    const response = await fetch('/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: password.value}), signal: AbortSignal.timeout(15000)});
    password.value = '';
    if (!response.ok) throw new Error(response.status === 429 ? 'Thử lại sau 10 phút.' : 'Không đăng nhập được. Kiểm tra mật khẩu.');
    location.assign('/');
  } catch (error) { document.getElementById('login-feedback').textContent = error.message; }
  finally { button.disabled = false; }
});
