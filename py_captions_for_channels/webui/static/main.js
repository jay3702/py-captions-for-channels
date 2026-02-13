let lastUiUpdate = 0;

async function fetchStatus() {
  try {
    const res = await fetch(`/api/status?ts=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch status');
    const data = await res.json();
    lastUiUpdate = Date.now();
    
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
    const versionText = data.build_number ? `${data.version}+${data.build_number}` : data.version || '—';
    document.getElementById('app-version').textContent = versionText;
    document.getElementById('timezone').textContent = data.timezone || '—';
    document.getElementById('dry-run').textContent = data.dry_run ? 'YES' : 'NO';
    document.getElementById('keep-original').textContent = data.keep_original ? 'YES' : 'NO';
    document.getElementById('log-verbosity').textContent = data.log_verbosity ? data.log_verbosity : '—';
    document.getElementById('whisper-model').textContent = data.whisper_model ? data.whisper_model : '—';
    document.getElementById('skip-caption-generation').textContent = data.skip_caption_generation ? 'YES' : 'NO';
    document.getElementById('last-processed').textContent = data.last_processed 
      ? new Date(data.last_processed).toLocaleString() 
      : 'never';
    const lastUpdate = document.getElementById('last-update');
    if (lastUpdate) {
      const ts = data.timestamp ? new Date(data.timestamp) : new Date();
      lastUpdate.textContent = ts.toLocaleString();
    }
    document.getElementById('manual-process-queue').textContent = `${data.manual_process_queue_size} items`;

    // Update service health indicators (external services only)
    if (data.services) {
      const servicesContainer = document.getElementById('services');
      if (servicesContainer) {
        let servicesHtml = '';
        for (const [key, svc] of Object.entries(data.services)) {
          if (
            key === 'whisper' ||
            key === 'ffmpeg' ||
            key === 'misc' ||
            svc.name === 'File Ops'
          ) {
            continue;
          }
          const healthClass = svc.healthy ? 'service-healthy' : 'service-unhealthy';
          const statusText = svc.status || (svc.healthy ? 'Healthy' : 'Unhealthy');
          servicesHtml += `<div class="service-status" title="${statusText}"><span class="${healthClass}">●</span> ${svc.name}</div>`;
        }
        servicesContainer.innerHTML = servicesHtml;
      }
    }

    // Update process indicators for Whisper/ffmpeg
    if (data.services) {
      const processesContainer = document.getElementById('processes');
      if (processesContainer) {
        const processKeys = ['whisper', 'ffmpeg', 'misc'];
        let processesHtml = '';
        for (const key of processKeys) {
          const svc = data.services[key];
          if (!svc) {
            continue;
          }
          const healthClass = svc.healthy ? 'service-healthy' : 'service-unhealthy';
          const statusText = svc.status || (svc.healthy ? 'Running' : 'Idle');

          let progress = null;
          let progressJobId = null;
          if (data.progress) {
            const matches = Object.entries(data.progress)
              .filter(([, prog]) => prog.process_type === key)
              .sort((a, b) => (a[1].age_seconds ?? 999) - (b[1].age_seconds ?? 999));
            if (matches.length) {
              progressJobId = matches[0][0];
              progress = matches[0][1];
            }
          }

          let progressHtml = '';
          if (progress) {
            const percent = Math.round(progress.percent);
            progressHtml = `
              <div class="service-progress">
                <div class="progress-bar-compact">
                  <div class="progress-fill" style="width: ${progress.percent}%"></div>
                </div>
                <span class="progress-text">${percent}%</span>
              </div>
            `;
          }

          let jobMetaHtml = '';
          if (progress && (progress.job_number || progressJobId)) {
            const jobNumberText = progress.job_number ? `Job ${progress.job_number}` : '';
            const titleText = progressJobId ? formatJobTitle(progressJobId) : '';
            jobMetaHtml = `
              <div class="process-right">
                ${jobNumberText ? `<span class="process-job">${jobNumberText}</span>` : ''}
                ${titleText ? `<span class="process-title" title="${escapeAttr(titleText)}">${escapeHtml(titleText)}</span>` : ''}
              </div>
            `;
          }

          processesHtml += `
            <div class="service-status process-row" title="${statusText}">
              <span class="${healthClass}">●</span>
              ${svc.name}
              ${progressHtml}
              ${jobMetaHtml}
            </div>
          `;
        }

        processesContainer.innerHTML = processesHtml || '<div class="service-status"><span class="service-unhealthy">●</span> No process data</div>';
      }
    }

    // Update heartbeat indicators with pulse animation
    if (data.heartbeat) {
      for (const [name, hb] of Object.entries(data.heartbeat)) {
        const indicator = document.getElementById(`heartbeat-${name}`);
        if (indicator) {
          if (hb.alive && hb.age_seconds < 15) {
            // Recent heartbeat - pulse it with 1-second green flash
            indicator.classList.remove('pulse'); // Remove first to restart animation
            void indicator.offsetWidth; // Force reflow
            indicator.classList.add('pulse');
            setTimeout(() => indicator.classList.remove('pulse'), 1000);
          } else if (hb.alive) {
            // Alive but not super fresh - keep cyan but no pulse
            indicator.style.color = '#5ce1e6';
          } else {
            // Stale - grey
            indicator.style.color = '#666';
          }
        }
      }
    }

    // Progress bars are now handled inline with services above
  } catch (err) {
    document.getElementById('status-pill').className = 'pill pill-error';
    document.getElementById('status-pill').textContent = 'error';
    console.error('Status fetch error:', err);
  }
}

  async function fetchExecutions() {
  try {
      const res = await fetch(`/api/executions?limit=50&ts=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error('Failed to fetch executions');
    const data = await res.json();
    
      const execListActive = document.getElementById('exec-list-active');
      const execListBacklog = document.getElementById('exec-list-backlog');
      const execCount = document.getElementById('exec-count');
    
      execCount.textContent = `(${data.count} items)`;
    
      if (data.executions && data.executions.length > 0) {
        const activeStatuses = new Set(['running', 'pending']);
        const activeExecutions = data.executions.filter(exec => activeStatuses.has(exec.status));
        const backlogExecutions = data.executions.filter(exec => !activeStatuses.has(exec.status));

        const sortedActive = [...activeExecutions].sort(compareActiveExecutions);
        const sortedBacklog = [...backlogExecutions].sort(compareBacklogExecutions);

        execListActive.innerHTML = sortedActive.length
          ? sortedActive.map(exec => renderExecution(exec)).join('')
          : '<li class="muted">No active executions</li>';

        execListBacklog.innerHTML = sortedBacklog.length
          ? sortedBacklog.map(exec => renderExecution(exec)).join('')
          : '<li class="muted">No queued executions</li>';
    } else {
        execListActive.innerHTML = '<li class="muted">No active executions</li>';
        execListBacklog.innerHTML = '<li class="muted">No queued executions</li>';
    }
  } catch (err) {
      document.getElementById('exec-list-active').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
      document.getElementById('exec-list-backlog').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
      console.error('Executions fetch error:', err);
  }
}

function compareActiveExecutions(a, b) {
  const statusRank = {
    running: 0,
    pending: 1,
  };

  const rankA = statusRank[a.status] ?? 99;
  const rankB = statusRank[b.status] ?? 99;
  if (rankA !== rankB) {
    return rankA - rankB;
  }

  const jobNumberA = Number.isFinite(a.job_number) ? a.job_number : -1;
  const jobNumberB = Number.isFinite(b.job_number) ? b.job_number : -1;
  if (jobNumberA !== jobNumberB) {
    return jobNumberB - jobNumberA;
  }

  const startedA = a.started_at ? Date.parse(a.started_at) : 0;
  const startedB = b.started_at ? Date.parse(b.started_at) : 0;
  return startedB - startedA;
}

function compareBacklogExecutions(a, b) {
  const backlogRank = {
    discovered: 0,
  };

  const rankA = backlogRank[a.status] ?? 99;
  const rankB = backlogRank[b.status] ?? 99;
  if (rankA !== rankB) {
    return rankA - rankB;
  }

  // Sort by start time descending (most recent first)
  const startedA = a.started_at ? Date.parse(a.started_at) : 0;
  const startedB = b.started_at ? Date.parse(b.started_at) : 0;
  return startedB - startedA;
}

  function renderExecution(exec) {
    // Determine status display
    let statusClass, statusIcon, statusText;
    
    if (exec.status === 'pending') {
      statusClass = 'exec-pending';
      statusIcon = '⏸';
      statusText = 'Pending';
    } else if (exec.status === 'discovered') {
      statusClass = 'exec-pending';
      statusIcon = '🔍';
      statusText = 'Discovered';
    } else if (exec.status === 'dry_run') {
      statusClass = 'exec-dryrun';
      statusIcon = '🔄';
      statusText = 'Dry Run';
    } else if (exec.status === 'cancelled') {
      statusClass = 'exec-failure';
      statusIcon = '⏹';
      statusText = 'Cancelled';
    } else if (exec.status === 'canceling' || (exec.status === 'running' && exec.cancel_requested)) {
      statusClass = 'exec-running';
      statusIcon = '⏹';
      statusText = 'Canceling';
    } else if (exec.status === 'running') {
      statusClass = 'exec-running';
      statusIcon = '⏳';
      statusText = 'Running';
    } else if (exec.success) {
      statusClass = 'exec-success';
      statusIcon = '✓';
      statusText = 'Success';
    } else {
      statusClass = 'exec-failure';
      statusIcon = '✗';
      statusText = 'Failed';
    }
  
    const elapsed = exec.elapsed_seconds > 0 
      ? `${Math.floor(exec.elapsed_seconds / 60)}:${(exec.elapsed_seconds % 60).toFixed(1).padStart(4, '0')}`
      : '—';
  
    // Use server-provided local time if available, otherwise parse ISO timestamp
    const startTime = exec.started_local ? exec.started_local.split(' ')[1] : (exec.started_at ? new Date(exec.started_at).toLocaleTimeString() : '—');
    const tagHtml = exec.kind === 'manual_process' ? '<span class="exec-tag">Manual</span>' : '';
    const cancelHtml = (exec.status === 'running' && !exec.cancel_requested)
      ? `<button class="exec-cancel" data-exec-id="${encodeURIComponent(exec.id)}" onclick="cancelExecutionFromEl(this, event)">Cancel</button>`
      : '';
    const jobNumberHtml = exec.job_number ? `<span class="exec-job-number">#${exec.job_number}</span>` : '<span class="exec-job-number">—</span>';
  
    return `
      <li class="exec-item ${statusClass}" data-exec-id="${encodeURIComponent(exec.id)}" onclick="showExecutionDetailFromEl(this)">
        <span class="exec-time">${startTime}</span>
        ${jobNumberHtml}
        <span class="exec-title">${escapeHtml(exec.title)}</span>
        ${tagHtml}
        <span class="exec-status-combined">
          <span class="exec-status-icon">${statusIcon}</span>
          <span class="exec-status-text">${statusText}</span>
        </span>
        <span class="exec-elapsed">${elapsed}</span>
        ${cancelHtml}
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
    
      // Format logs: use server-prepared text if available
      const logLinesRaw = (exec.logs_text && exec.logs_text.trim().length > 0)
        ? exec.logs_text
        : (exec.logs && exec.logs.length > 0
            ? exec.logs.map(l => typeof l === 'string' ? l : (l.message || '')).join('\n')
            : 'No logs captured for this execution');
      const logLines = logLinesRaw && logLinesRaw.trim().length > 0 ? logLinesRaw : 'No logs captured for this execution';
    
      const startedDisplay = exec.started_local || (exec.started_at ? new Date(exec.started_at).toLocaleString() : '—');
      const completedDisplay = exec.completed_local || (exec.completed_at ? new Date(exec.completed_at).toLocaleString() : null);
    
      body.innerHTML = `
        <div class="detail-section">
          <h3>Overview</h3>
          ${exec.kind === 'manual_process' ? '<p><strong>Type:</strong> Manual Processing</p>' : ''}
          <p><strong>Status:</strong> ${exec.status} ${exec.success !== null ? (exec.success ? '✓ Success' : '✗ Failed') : ''}</p>
          <p><strong>Started:</strong> ${escapeHtml(startedDisplay)}</p>
          ${completedDisplay ? `<p><strong>Completed:</strong> ${escapeHtml(completedDisplay)}</p>` : ''}
          <p><strong>Duration:</strong> ${exec.elapsed_seconds > 0 ? Math.floor(exec.elapsed_seconds / 60) + 'm ' + (exec.elapsed_seconds % 60).toFixed(1) + 's' : '—'}</p>
          <p><strong>Path:</strong> <code>${escapeHtml(exec.path)}</code></p>
          ${exec.error ? `<p class="error-text"><strong>Error:</strong> ${escapeHtml(exec.error)}</p>` : ''}
          ${exec.kind === 'manual_process' && exec.status === 'pending' ? `
            <div style="margin-top: 15px;">
              <button class="btn-secondary" onclick="removeFromManualProcessQueue('${escapeAttr(exec.path)}', '${escapeAttr(exec.id)}')"Remove from Queue</button>
            </div>
          ` : ''}
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

function formatJobTitle(jobId) {
  if (!jobId) return '';
  let title = jobId;
  if (jobId.includes(' @ ')) {
    title = jobId.split(' @ ')[0];
  }
  if (title.startsWith('manual_process::')) {
    title = title.replace('manual_process::', '');
  }
  return title;
}

async function clearList() {
  try {
    // First call to check pending executions
    const res = await fetch('/api/executions/clear_list', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to clear list');
    const data = await res.json();
    
    // If there are legitimate pending jobs, ask for confirmation
    if (data.pending_count > 0 && data.pending_ids && data.pending_ids.length > 0) {
      const titles = data.pending_ids.map(p => `  • ${p.title || p.path}`).join('\n');
      const msg = `This will remove failed, dry-run, and invalid pending jobs.\n\nHowever, ${data.pending_count} legitimate pending job(s) are active:\n${titles}\n\nCancel these ${data.pending_count} pending job(s)?`;
      
      if (!confirm(msg)) {
        // User declined to cancel pending jobs
        console.log('Kept', data.pending_count, 'legitimate pending jobs in queue');
        await fetchExecutions();
        return;
      }
      
      // User confirmed cancellation - make second call with cancel_pending=true
      const res2 = await fetch('/api/executions/clear_list?cancel_pending=true', { method: 'POST' });
      if (!res2.ok) throw new Error('Failed to clear list with pending cancellation');
      await res2.json();
    }
    
    await fetchExecutions();
  } catch (err) {
    alert('Clear list error: ' + err.message);
  }
}

async function clearFailedExecutions() {
  // Legacy function - redirect to clearList
  return clearList();
}

async function clearPendingExecutions() {
  try {
    if (!confirm('Clear stale pending executions from the list?')) {
      return;
    }
    const res = await fetch('/api/executions/clear_pending?max_age_minutes=60', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to clear pending executions');
    await res.json();
    fetchExecutions();
  } catch (err) {
    alert('Clear pending error: ' + err.message);
  }
}

async function clearPollingCache() {
  try {
    if (!confirm('Clear polling cache? This will allow the system to re-discover and process recordings that were previously seen.\n\nUse this if recordings are not being picked up after fixing issues.')) {
      return;
    }
    const res = await fetch('/api/polling-cache/clear', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to clear polling cache');
    const data = await res.json();
    alert(`Polling cache cleared: ${data.cleared} entries removed.\n\nRecordings will be re-evaluated on the next poll.`);
  } catch (err) {
    alert('Clear polling cache error: ' + err.message);
  }
}

  function escapeAttr(text) {
    return text.replace(/'/g, '&#39;').replace(/"/g, '&quot;');
  }

function showExecutionDetailFromEl(el) {
  const jobId = decodeURIComponent(el.dataset.execId || '');
  if (jobId) {
    showExecutionDetail(jobId);
  }
}

async function cancelExecutionFromEl(el, event) {
  event.stopPropagation();
  const jobId = decodeURIComponent(el.dataset.execId || '');
  if (!jobId) return;
  if (!confirm('Cancel this running job?')) return;
  try {
    const res = await fetch(`/api/executions/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to cancel execution');
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    fetchExecutions();
  } catch (err) {
    alert('Cancel failed: ' + err.message);
  }
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

async function showManualProcessModal() {
  const modal = document.getElementById('manual-process-modal');
  const listContainer = document.getElementById('manual-process-list');
  const verbositySelect = document.getElementById('log-verbosity');
  
  // Show modal
  modal.style.display = 'flex';
  listContainer.innerHTML = '<p class="muted">Loading recordings...</p>';
  
  try {
    const verbosityRes = await fetch('/api/logging/verbosity');
    if (verbosityRes.ok) {
      const verbosityData = await verbosityRes.json();
      if (verbosityData.verbosity) {
        verbositySelect.value = verbosityData.verbosity.toUpperCase();
      }
    }

    const res = await fetch('/api/recordings');
    if (!res.ok) throw new Error('Failed to fetch recordings');
    const data = await res.json();
    
    // Debug: see ALL fields in first recording
    if (data.recordings && data.recordings.length > 0) {
      console.log('First recording fields:', Object.keys(data.recordings[0]));
      console.log('First recording full object:', data.recordings[0]);
    }
    
    if (data.recordings && data.recordings.length > 0) {
      // Create table for recordings
      let tableHtml = `
        <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
          <thead>
            <tr style="border-bottom: 2px solid var(--border); text-align: left;">
              <th style="padding: 8px 4px; width: 30px;"></th>
              <th style="padding: 8px;">Recording</th>
              <th style="padding: 8px; width: 140px;">Date</th>
              <th style="padding: 8px; width: 80px; text-align: center;">Processed</th>
              <th style="padding: 8px; width: 80px; text-align: center;">Whitelist</th>
            </tr>
          </thead>
          <tbody>
      `;
      
      data.recordings.forEach((recording, idx) => {
        const title = recording.episode_title 
          ? `${recording.title} - ${recording.episode_title}` 
          : recording.title;
        
        // Format date - created_at is Unix timestamp in milliseconds
        let dateStr = 'Unknown';
        if (recording.created_at) {
          const date = new Date(recording.created_at);
          if (!isNaN(date.getTime())) {
            dateStr = date.toLocaleString();
          }
        }
        
        // Processed status: green checkmark if success, red X if failed, empty if not processed
        let processedIcon = '';
        if (recording.processed === 'success') {
          processedIcon = '<span style="color: #4caf50; font-size: 18px;" title="Processed successfully">✓</span>';
        } else if (recording.processed === 'failed') {
          processedIcon = '<span style="color: #ef5350; font-size: 18px;" title="Processing failed">✗</span>';
        }
        
        // Whitelist status: green checkmark if passes, empty if not
        let whitelistIcon = '';
        if (recording.passes_whitelist) {
          whitelistIcon = '<span style="color: #4caf50; font-size: 18px;" title="Passes whitelist">✓</span>';
        }
        
        tableHtml += `
          <tr style="border-bottom: 1px solid var(--border);">
            <td style="padding: 8px 4px;">
              <input type="checkbox" name="manual-process-path" value="${escapeAttr(recording.path)}" data-idx="${idx}">
            </td>
            <td style="padding: 8px;">
              <div style="font-weight: 500;">${escapeHtml(title)}</div>
            </td>
            <td style="padding: 8px; color: var(--muted); font-size: 0.85em;">${dateStr}</td>
            <td style="padding: 8px; text-align: center;">${processedIcon}</td>
            <td style="padding: 8px; text-align: center;">${whitelistIcon}</td>
          </tr>
        `;
      });
      
      tableHtml += '</tbody></table>';
      listContainer.innerHTML = tableHtml;
    } else {
      listContainer.innerHTML = '<p class="muted">No recordings available</p>';
    }
  } catch (err) {
    listContainer.innerHTML = `<p class="muted">Error loading recordings: ${escapeHtml(err.message)}</p>`;
    console.error('Recordings fetch error:', err);
  }
}

function closeManualProcessModal() {
  document.getElementById('manual-process-modal').style.display = 'none';
}

async function submitManualProcessing() {
  const checkboxes = document.querySelectorAll('input[name="manual-process-path"]:checked');
  const paths = Array.from(checkboxes).map(cb => cb.value);
  
  if (paths.length === 0) {
    alert('Please select at least one recording to process');
    return;
  }
  
  const skipCaptionGeneration = document.getElementById('manual-process-skip-caption').checked;
  const logVerbosity = document.getElementById('manual-process-log-verbosity').value;
  
  try {
    const res = await fetch('/api/manual-process/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        paths, 
        skip_caption_generation: skipCaptionGeneration,
        log_verbosity: logVerbosity
      })
    });
    
    if (!res.ok) throw new Error('Failed to add to manual process queue');
    const data = await res.json();
    
    if (data.error) {
      alert('Error: ' + data.error);
    } else {
      closeManualProcessModal();
      fetchStatus(); // Refresh to update queue count
    }
  } catch (err) {
    alert('Error adding to reprocess queue: ' + err.message);
    console.error('Reprocess submit error:', err);
  }
}

async function removeFromManualProcessQueue(path, execId) {
  if (!confirm('Remove this item from the manual process queue?')) return;
  
  try {
    const res = await fetch('/api/manual-process/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    
    if (!res.ok) throw new Error('Failed to remove from manual process queue');
    const data = await res.json();
    
    if (data.error) {
      alert('Error: ' + data.error);
    } else {
      alert('Item removed from manual process queue');
      closeModal();
      fetchStatus(); // Refresh to update queue count
      fetchExecutions(); // Refresh execution list
    }
  } catch (err) {
    alert('Error removing from manual process queue: ' + err.message);
    console.error('Remove from manual process queue error:', err);
  }
}


// --- Real-time log streaming via WebSocket ---
let logSocket = null;
let logSocketActive = false;
let logLines = [];
const MAX_LOG_LINES = 500;

function startLogWebSocket() {
  if (logSocketActive) return;
  logSocketActive = true;
  logLines = [];
  const logList = document.getElementById('log-list');
  const logCount = document.getElementById('log-count');
  logList.innerHTML = '<li class="muted">Connecting to log stream...</li>';
  logSocket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/logs');
  logSocket.onopen = () => {
    logList.innerHTML = '';
    logCount.textContent = '(streaming)';
  };
  logSocket.onmessage = (event) => {
    if (typeof event.data === 'string') {
      logLines.push(event.data);
      if (logLines.length > MAX_LOG_LINES) logLines.shift();
      logList.innerHTML = logLines.map(line => `<li><code>${escapeHtml(line)}</code></li>`).join('');
      logCount.textContent = `(${logLines.length} lines)`;
    }
  };
  logSocket.onerror = (event) => {
    logList.innerHTML = '<li class="muted">Log stream error - using polling fallback</li>';
    logCount.textContent = '(polling)';
    logSocketActive = false;
    startLogPolling();
  };
  logSocket.onclose = () => {
    logSocketActive = false;
    // If we explicitly stopped it, don't try to reconnect
    if (logSocket !== null) {
      logList.innerHTML += '<li class="muted">Log stream closed - using polling fallback</li>';
      logCount.textContent = '(polling)';
      startLogPolling();
    }
  };
}

function stopLogWebSocket() {
  if (logSocket) {
    logSocket.close();
    logSocket = null;
  }
  logSocketActive = false;
}

// --- Tab switching logic: activate WebSocket only for logs tab ---
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
  // Handle log streaming - only when logs tab is active
  if (tabName === 'logs') {
    stopLogPolling();
    startLogWebSocket();
  } else {
    stopLogWebSocket();
    stopLogPolling();  // Stop polling when NOT on logs tab
  }
}

// --- Fallback polling for logs if not using WebSocket ---
let logPollInterval = null;
function startLogPolling() {
  if (logPollInterval) return;
  fetchLogs();
  logPollInterval = setInterval(fetchLogs, 5000);
}
function stopLogPolling() {
  if (logPollInterval) {
    clearInterval(logPollInterval);
    logPollInterval = null;
  }
}


// --- Pipeline Settings UI ---
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) throw new Error('Failed to load settings');
    const data = await res.json();
    document.getElementById('discovery-mode-select').value = data.discovery_mode || 'polling';
    document.getElementById('dry-run-toggle').checked = !!data.dry_run;
    document.getElementById('keep-original-toggle').checked = !!data.keep_original;
    document.getElementById('log-verbosity-select').value = (data.log_verbosity || 'NORMAL').toUpperCase();
    document.getElementById('whisper-model-select').value = data.whisper_model || 'medium';
    document.getElementById('whitelist-editor').value = data.whitelist || '';
  } catch (err) {
    alert('Failed to load settings: ' + err.message);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    discovery_mode: document.getElementById('discovery-mode-select').value,
    dry_run: document.getElementById('dry-run-toggle').checked,
    keep_original: document.getElementById('keep-original-toggle').checked,
    log_verbosity: document.getElementById('log-verbosity-select').value,
    whisper_model: document.getElementById('whisper-model-select').value,
    whitelist: document.getElementById('whitelist-editor').value,
  };
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Failed to save settings');
    alert('Settings saved!');
    fetchStatus();
  } catch (err) {
    alert('Failed to save settings: ' + err.message);
  }
}

// Initial fetch
fetchStatus();
fetchExecutions();
loadSettings();
applyStatusPanelVisibility();
// Note: Don't start log polling on init - only when logs tab is clicked

// Poll status and executions every 5 seconds
let refreshTimer = null;
const refreshNow = () => {
  fetchStatus();
  fetchExecutions();
};

const startAutoRefresh = () => {
  if (refreshTimer) return;
  refreshTimer = setInterval(() => {
    const now = Date.now();
    if (now - lastUiUpdate > 15000) {
      refreshNow();
      return;
    }
    refreshNow();
  }, 5000);
};

startAutoRefresh();
window.addEventListener('focus', refreshNow);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    refreshNow();
  }
});

function applyStatusPanelVisibility() {
  const statusCard = document.getElementById('status-card');
  if (!statusCard) return;
  statusCard.style.display = '';
}

function openSettingsModal() {
  const modal = document.getElementById('settings-modal');
  if (modal) {
    modal.style.display = 'flex';
  }
}

function closeSettingsModal() {
  const modal = document.getElementById('settings-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// Close settings modal on background click
window.addEventListener('click', function(event) {
  const settingsModal = document.getElementById('settings-modal');
  if (event.target === settingsModal) {
    closeSettingsModal();
  }
});



