async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error('Failed to fetch status');
    const data = await res.json();
    document.getElementById('status-pill').textContent = data.status || 'unknown';
    document.getElementById('app-name').textContent = data.app || '—';
    document.getElementById('app-version').textContent = data.version || '—';
    document.getElementById('app-notes').textContent = data.notes || '—';
  } catch (err) {
    document.getElementById('status-pill').textContent = 'error';
    document.getElementById('app-notes').textContent = err.message;
  }
}

fetchStatus();
setInterval(fetchStatus, 5000);
