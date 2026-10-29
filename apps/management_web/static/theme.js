// Presentation preference only: never stores business configuration or credentials.
(() => {
  'use strict';
  const key = 'fishery.ui.theme';
  const valid = value => value === 'dark' ? 'dark' : 'light';
  let theme = 'light';
  try { theme = valid(window.localStorage.getItem(key)); } catch (_) { /* Storage may be disabled. */ }
  const paint = () => {
    document.documentElement.setAttribute('data-theme', theme);
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const action = theme === 'dark' ? '切换到浅色主题' : '切换到深蓝主题';
    button.setAttribute('aria-label', action);
    button.setAttribute('title', action);
    button.setAttribute('aria-pressed', String(theme === 'dark'));
    button.querySelector('.theme-label').textContent = theme === 'dark' ? '深蓝主题' : '浅色主题';
  };
  paint(); // Runs before styles load, avoiding a light flash on a saved dark page.
  const mount = () => {
    paint();
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      paint();
      try { window.localStorage.setItem(key, theme); } catch (_) { /* This tab still works. */ }
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
