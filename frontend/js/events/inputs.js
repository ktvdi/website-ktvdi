document.addEventListener('input', e => { if (e.target && e.target.id === 'databaseQuery') {
    state.databaseQuery = e.target.value;
    const active = document.activeElement;
    render();
    const input = document.getElementById('databaseQuery');
    if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }
    return;
} });
document.addEventListener('change', e => { if (e.target && e.target.id === 'databaseProvince') {
    state.databaseProvince = e.target.value;
    state.databaseArea = '';
    state.databaseMux = '';
    state.databaseRequestTarget = null;
    render();
    return;
} if (e.target && e.target.id === 'databaseArea') {
    state.databaseArea = e.target.value;
    state.databaseMux = '';
    state.databaseRequestTarget = null;
    render();
    return;
} if (e.target && e.target.id === 'databaseMux') {
    state.databaseMux = e.target.value;
    state.databaseRequestTarget = null;
    render();
    return;
} if (e.target && e.target.id === 'pointTargetSelect') {
    state.pointSelected = e.target.value;
    render();
    return;
} });

