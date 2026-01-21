async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error('Failed to fetch status');
    const data = await res.json();
    
    // Update status pill color based on status/error
    const statusPill = document.getElementById('status-pill');
    if (data.status === 'error') {
      statusPill.className = 'pill pill-error';
    } else if (data.status === 'running') {
      statusPill.className = 'pill pill-success';
    } else {
      statusPill.className = 'pill pill-muted';
    }
    
    statusPill.textContent = data.status || 'unknown';
    document.getElementById('app-name').textContent = data.app || '—';
    document.getElementById('app-version').textContent = data.version || '—';
    document.getElementById('dry-run').textContent = data.dry_run ? 'YES (test mode)' : 'NO (live)';
    document.getElementById('last-processed').textContent = data.last_processed 
      ? new Date(data.last_processed).toLocaleString() 
      : 'never';
    document.getElementById('reprocess-queue').textContent = `${data.reprocess_queue_size} items`;
  } catch (err) {
    document.getElementById('status-pill').className = 'pill pill-error';
    document.getElementById('status-pill').textContent = 'error';
    console.error('Status fetch error:', err);
  }
}

async function fetchLogs() {
  try {
    const res = await fetch('/api/logs?lines=50');
    if (!res.ok) throw new Error('Failed to fetch logs');
    const data = await res.json();
    
    const logList = document.getElementById('log-list');
    const logCount = document.getElementById('log-count');
    
    logCount.textContent = `(${data.count} lines)`;
    
    if (data.items && data.items.length > 0) {
      logList.innerHTML = data.items.map(line => 
        `<li>${escapeHtml(line)}</li>`
      ).join('');
    } else {
      logList.innerHTML = '<li class="muted">No logs available</li>';
    }
  } catch (err) {
    document.getElementById('log-list').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
    console.error('Logs fetch error:', err);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Initial fetch
fetchStatus();
fetchLogs();

// Poll every 5 seconds
setInterval(fetchStatus, 5000);
setInterval(fetchLogs, 5000);

