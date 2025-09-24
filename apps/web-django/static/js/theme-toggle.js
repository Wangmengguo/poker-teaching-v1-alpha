// Theme Toggle Functionality
// Can be reused across multiple pages

function initThemeToggle() {
  const themeToggleBtn = document.getElementById('btn-theme-toggle');
  if (!themeToggleBtn) {
    console.warn('Theme toggle button not found');
    return;
  }

  const moonIcon = themeToggleBtn.querySelector('.icon-moon');
  const sunIcon = themeToggleBtn.querySelector('.icon-sun');
  const html = document.documentElement;

  // Get saved theme or default to light
  const savedTheme = localStorage.getItem('theme') || 'light';
  const currentTheme = html.getAttribute('data-theme') || 'light';

  // Apply saved theme
  if (savedTheme === 'dark') {
    html.setAttribute('data-theme', 'dark');
    if (moonIcon) moonIcon.classList.add('hidden');
    if (sunIcon) sunIcon.classList.remove('hidden');
  } else {
    html.setAttribute('data-theme', 'light');
    if (moonIcon) moonIcon.classList.remove('hidden');
    if (sunIcon) sunIcon.classList.add('hidden');
  }

  // Toggle theme on button click
  themeToggleBtn.addEventListener('click', () => {
    const currentTheme = html.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';

    // Apply new theme
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);

    // Update icons
    if (newTheme === 'dark') {
      if (moonIcon) moonIcon.classList.add('hidden');
      if (sunIcon) sunIcon.classList.remove('hidden');
    } else {
      if (moonIcon) moonIcon.classList.remove('hidden');
      if (sunIcon) sunIcon.classList.add('hidden');
    }

    // Add smooth transition
    document.body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
    setTimeout(() => {
      document.body.style.transition = '';
    }, 300);
  });
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initThemeToggle);
} else {
  initThemeToggle();
}

// Export for manual initialization if needed
window.initThemeToggle = initThemeToggle;
