const menuToggle = document.getElementById('menuToggle');
const mainNav = document.getElementById('nav');
menuToggle.addEventListener('click', () => {
    const expanded = mainNav.classList.toggle('open');
    menuToggle.setAttribute('aria-expanded', String(expanded));
    menuToggle.setAttribute('aria-label', expanded ? 'Tutup navigasi' : 'Buka navigasi');
});
