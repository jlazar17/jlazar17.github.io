(function () {
    var STORAGE_KEY = 'theme';

    function getSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        var btn = document.getElementById('theme-toggle');
        if (btn) btn.textContent = '[' + (theme === 'dark' ? 'light' : 'dark') + ' mode]';
    }

    function toggle() {
        var current = document.documentElement.getAttribute('data-theme') || getSystemTheme();
        var next = current === 'dark' ? 'light' : 'dark';
        localStorage.setItem(STORAGE_KEY, next);
        applyTheme(next);
    }

    // Apply saved theme immediately to avoid flash
    var saved = localStorage.getItem(STORAGE_KEY);
    applyTheme(saved || getSystemTheme());

    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.getElementById('theme-toggle');
        if (btn) btn.addEventListener('click', toggle);
    });
})();
