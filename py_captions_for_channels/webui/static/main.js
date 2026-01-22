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

    // Update service health indicators
    if (data.services) {
      const servicesContainer = document.getElementById('services');
      if (servicesContainer) {
        let servicesHtml = '';
        for (const [key, svc] of Object.entries(data.services)) {
          const healthClass = svc.healthy ? 'service-healthy' : 'service-unhealthy';
          const statusText = svc.status || (svc.healthy ? 'Healthy' : 'Unhealthy');
          servicesHtml += `<div class="service-status" title="${statusText}"><span class="${healthClass}">●</span> ${svc.name}</div>`;
        }
        servicesContainer.innerHTML = servicesHtml;
      }
    }
  } catch (err) {
    document.getElementById('status-pill').className = 'pill pill-error';
    document.getElementById('status-pill').textContent = 'error';
    console.error('Status fetch error:', err);
  }
}

  async function fetchExecutions() {
  try {
      const res = await fetch('/api/executions?limit=50');
      if (!res.ok) throw new Error('Failed to fetch executions');
    const data = await res.json();
    
      const execList = document.getElementById('exec-list');
      const execCount = document.getElementById('exec-count');
    
      execCount.textContent = `(${data.count} items)`;
    
      if (data.executions && data.executions.length > 0) {
        execList.innerHTML = data.executions.map(exec => 
          renderExecution(exec)
      ).join('');
    } else {
        execList.innerHTML = '<li class="muted">No executions yet</li>';
    }
  } catch (err) {
      document.getElementById('exec-list').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
      console.error('Executions fetch error:', err);
  }
}

  function renderExecution(exec) {
    const statusClass = exec.status === 'running' ? 'exec-running' : (exec.success ? 'exec-success' : 'exec-failure');
    const statusIcon = exec.status === 'running' ? '⏳' : (exec.success ? '✓' : '✗');
    const statusText = exec.status === 'running' ? 'Running' : (exec.success ? 'Success' : 'Failed');
  
    const elapsed = exec.elapsed_seconds > 0 
      ? `${Math.floor(exec.elapsed_seconds / 60)}:${(exec.elapsed_seconds % 60).toFixed(1).padStart(4, '0')}`
      : '—';
  
    const startTime = new Date(exec.started_at).toLocaleTimeString();
  
    return `
      <li class="exec-item ${statusClass}" onclick="showExecutionDetail('${escapeAttr(exec.id)}')">
        <span class="exec-status">${statusIcon}</span>
        <span class="exec-title">${escapeHtml(exec.title)}</span>
        <span class="exec-time">${startTime}</span>
        <span class="exec-status-text">${statusText}</span>
        <span class="exec-elapsed">${elapsed}</span>
        ${exec.status === 'running' ? '<div class="exec-progress"><div class="progress-bar"></div></div>' : ''}
      </li>
    `;
  }

  async function showExecutionDetail(jobId) {
    try {
      const res = await fetch(`/api/executions/${encodeURIComponent(jobId)}`);
      if (!res.ok) throw new Error('Failed to fetch execution detail');
      const exec = await res.json();
    
      // Check for API-level error (e.g., "Execution not found")
      if (exec.error && !exec.title) {
        alert('Error: ' + exec.error);
        return;
      }
    
      const modal = document.getElementById('exec-modal');
      const title = document.getElementById('modal-title');
      const body = document.getElementById('modal-body');
    
      title.textContent = exec.title || 'Execution Details';
    
      // Format logs: handle both array of objects and array of strings
      const logLines = exec.logs && exec.logs.length > 0 
        ? exec.logs.map(l => typeof l === 'string' ? l : (l.message || '')).join('\n')
        : 'No logs captured for this execution';
    
      body.innerHTML = `
        <div class="detail-section">
          <h3>Overview</h3>
          <p><strong>Status:</strong> ${exec.status} ${exec.success !== null ? (exec.success ? '✓ Success' : '✗ Failed') : ''}</p>
          <p><strong>Started:</strong> ${new Date(exec.started_at).toLocaleString()}</p>
          ${exec.completed_at ? `<p><strong>Completed:</strong> ${new Date(exec.completed_at).toLocaleString()}</p>` : ''}
          <p><strong>Duration:</strong> ${exec.elapsed_seconds > 0 ? Math.floor(exec.elapsed_seconds / 60) + 'm ' + (exec.elapsed_seconds % 60).toFixed(1) + 's' : '—'}</p>
          <p><strong>Path:</strong> <code>${escapeHtml(exec.path)}</code></p>
          ${exec.error ? `<p class="error-text"><strong>Error:</strong> ${escapeHtml(exec.error)}</p>` : ''}
        </div>
        <div class="detail-section">
          <h3>Logs</h3>
          <pre class="log-output">${escapeHtml(logLines)}</pre>
        </div>
      `;
    
      modal.style.display = 'flex';
    } catch (err) {
      alert('Error loading execution detail: ' + err.message);
      console.error('Execution detail fetch error:', err);
    }
  }

  function closeModal() {
    document.getElementById('exec-modal').style.display = 'none';
  }

  // Close modal on background click
  window.onclick = function(event) {
    const modal = document.getElementById('exec-modal');
    if (event.target === modal) {
      closeModal();
    }
  }

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

  function escapeAttr(text) {
    return text.replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  }

async function fetchLogs() {
  try {
    const res = await fetch('/api/logs?lines=100');
    if (!res.ok) throw new Error('Failed to fetch logs');
    const data = await res.json();
    
    const logList = document.getElementById('log-list');
    const logCount = document.getElementById('log-count');
    
    logCount.textContent = `(${data.count} lines)`;
    
    if (data.items && data.items.length > 0) {
      logList.innerHTML = data.items.map(line => 
        `<li><code>${escapeHtml(line)}</code></li>`
      ).join('');
    } else {
      logList.innerHTML = '<li class="muted">No logs available</li>';
    }
  } catch (err) {
    document.getElementById('log-list').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
    console.error('Logs fetch error:', err);
  }
}

function switchTab(tabName) {
  // Update tab buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  event.target.classList.add('active');
  
  // Update tab content
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });
  document.getElementById(`${tabName}-tab`).classList.add('active');
}

async function showReprocessModal() {
  const modal = document.getElementById('reprocess-modal');
  const listContainer = document.getElementById('reprocess-list');
  
  // Show modal
  modal.style.display = 'flex';
  listContainer.innerHTML = '<p class="muted">Loading candidates...</p>';
  
  try {
    const res = await fetch('/api/reprocess/candidates');
    if (!res.ok) throw new Error('Failed to fetch candidates');
    const data = await res.json();
    
    if (data.candidates && data.candidates.length > 0) {
      listContainer.innerHTML = data.candidates.map((candidate, idx) => {
        const statusIcon = candidate.success ? '✓' : '✗';
        const statusClass = candidate.success ? 'text-success' : 'text-error';
        return `
          <div class="reprocess-item">
            <label>
              <input type="checkbox" name="reprocess-path" value="${escapeAttr(candidate.path)}" data-idx="${idx}">
              <span class="${statusClass}">${statusIcon}</span>
              <span class="reprocess-title">${escapeHtml(candidate.title)}</span>
              <span class="reprocess-time">${new Date(candidate.started_at).toLocaleString()}</span>
            </label>
          </div>
        `;
      }).join('');
    } else {
      listContainer.innerHTML = '<p class="muted">No completed recordings available for reprocessing</p>';
    }
  } catch (err) {
    listContainer.innerHTML = `<p class="muted">Error loading candidates: ${escapeHtml(err.message)}</p>`;
    console.error('Reprocess candidates fetch error:', err);
  }
}

function closeReprocessModal() {
  document.getElementById('reprocess-modal').style.display = 'none';
}

async function submitReprocessing() {
  const checkboxes = document.querySelectorAll('input[name="reprocess-path"]:checked');
  const paths = Array.from(checkboxes).map(cb => cb.value);
  
  if (paths.length === 0) {
    alert('Please select at least one recording to reprocess');
    return;
  }
  
  try {
    const res = await fetch('/api/reprocess/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths })
    });
    
    if (!res.ok) throw new Error('Failed to add to reprocess queue');
    const data = await res.json();
    
    if (data.error) {
      alert('Error: ' + data.error);
    } else {
      alert(`Added ${data.added} recording(s) to reprocess queue`);
      closeReprocessModal();
      fetchStatus(); // Refresh to update queue count
    }
  } catch (err) {
    alert('Error adding to reprocess queue: ' + err.message);
    console.error('Reprocess submit error:', err);
  }
}

// Initial fetch
fetchStatus();
fetchExecutions();
fetchLogs();

// Poll every 5 seconds
setInterval(fetchStatus, 5000);
setInterval(fetchExecutions, 5000);
setInterval(fetchLogs, 5000);


