'use strict';
// Bearer links use fragments: tokens never enter the HTTP URL/access log.
const tokenField = document.querySelector('[data-fragment-token]');
if (location.hash) {
    const parameters = new URLSearchParams(location.hash.slice(1));
    const token = parameters.get('token');
    if (tokenField && token) tokenField.value = token;
    history.replaceState(null, '', location.pathname);
}
document.querySelectorAll('[data-password-toggle]').forEach(button => {
    button.addEventListener('click', () => {
        const field = document.getElementById(button.dataset.passwordToggle);
        const visible = field.type === 'password';
        field.type = visible ? 'text' : 'password';
        button.textContent = visible ? 'Sembunyikan password' : 'Tampilkan password';
        button.setAttribute('aria-pressed', String(visible));
    });
});
document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
});
