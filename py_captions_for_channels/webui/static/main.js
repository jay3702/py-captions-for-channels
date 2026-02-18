let lastUiUpdate = 0;

async function fetchStatus() {
  try {
    const res = await fetch(`/api/status?ts=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch status');
    const data = await res.json();
    lastUiUpdate = Date.now();
    
    // Update status info in settings modal
    const appName = document.getElementById('app-name');
    if (appName) appName.textContent = data.app || '—';
    
    const appVersion = document.getElementById('app-version');
    if (appVersion) {
      const versionText = data.build_number ? `${data.version}+${data.build_number}` : data.version || '—';
      appVersion.textContent = versionText;
    }
    
    const timezone = document.getElementById('timezone');
    if (timezone) timezone.textContent = data.timezone || '—';
    
    const lastProcessed = document.getElementById('last-processed');
    if (lastProcessed) {
      lastProcessed.textContent = data.last_processed 
        ? new Date(data.last_processed).toLocaleString() 
        : 'never';
    }
    
    // Update queue size in settings modal
    const modalQueueSize = document.getElementById('modal-queue-size');
    if (modalQueueSize) {
      modalQueueSize.textContent = `${data.manual_process_queue_size} items`;
    }

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
          servicesHtml += `<div class="navbar-service" title="${statusText}"><span class="${healthClass}">●</span> ${svc.name}</div>`;
        }
        servicesContainer.innerHTML = servicesHtml || '<div class="navbar-service"><span class="service-unhealthy">●</span> None</div>';
      }
    }

    // Update process indicators for Whisper/ffmpeg/misc
    if (data.services) {
      const processesContainer = document.getElementById('processes');
      if (processesContainer) {
        const processKeys = ['misc', 'whisper', 'ffmpeg'];
        let processesHtml = '';
        let activeProgress = null;
        let activeKey = null;

        // First pass: find active progress
        for (const key of processKeys) {
          if (data.progress) {
            const matches = Object.entries(data.progress)
              .filter(([, prog]) => prog.process_type === key)
              .sort((a, b) => (a[1].age_seconds ?? 999) - (b[1].age_seconds ?? 999));
            if (matches.length) {
              activeProgress = matches[0][1];
              activeKey = key;
              break; // Only one can be active
            }
          }
        }

        // Second pass: render indicators
        for (const key of processKeys) {
          const svc = data.services[key];
          if (!svc) {
            continue;
          }
          
          // Only show green if this is the active process
          const isActive = activeKey === key;
          const healthClass = isActive ? 'service-healthy' : 'service-unhealthy';
          const labelClass = isActive ? 'process-label-active' : 'process-label-inactive';
          const statusText = isActive ? 'Running' : 'Idle';

          processesHtml += `
            <div class="navbar-service" title="${statusText}">
              <span class="${healthClass}">●</span>
              <span class="${labelClass}">${svc.name}</span>
            </div>
          `;
        }

        // Add shared progress bar at the end if any process is active
        if (activeProgress) {
          const percent = Math.round(activeProgress.percent);
          const messageText = activeProgress.message || '';
          processesHtml += `
            <div class="service-progress">
              <div class="progress-bar-compact">
                <div class="progress-fill" style="width: ${activeProgress.percent}%"></div>
              </div>
              <span class="progress-text">${percent}% ${messageText}</span>
            </div>
          `;
        }

        processesContainer.innerHTML = processesHtml || '<div class="navbar-service"><span class="service-unhealthy">●</span> No processes</div>';
      }
    }

    // Update version in navbar and settings modal
    const versionText = data.build_number ? `${data.version}+${data.build_number}` : data.version || '—';
    const versionNav = document.getElementById('webui-version-nav');
    if (versionNav) {
      versionNav.textContent = `v${versionText}`;
    }
    const webuiVersion = document.getElementById('webui-version');
    if (webuiVersion) {
      webuiVersion.textContent = `v${versionText}`;
    }

    // Update heartbeat indicators with pulse animation
    if (data.heartbeat) {
      for (const [name, hb] of Object.entries(data.heartbeat)) {
        const indicator = document.getElementById(`heartbeat-${name}`);
        if (indicator) {
          if (hb.alive && hb.age_seconds < 0.5) {
            // Very recent heartbeat (< 0.5s) - bright green pulse (250ms)
            indicator.classList.remove('pulse'); // Remove first to restart animation
            void indicator.offsetWidth; // Force reflow
            indicator.classList.add('pulse');
            setTimeout(() => indicator.classList.remove('pulse'), 250);
          } else if (hb.alive && hb.age_seconds < 4) {
            // Recent (0.5-4s) - regular green, no pulse
            indicator.style.color = '#00cc00';
          } else if (hb.alive) {
            // Alive but older (4-30s) - grey
            indicator.style.color = '#666';
          } else {
            // Stale (30s+) - grey
            indicator.style.color = '#666';
          }
        }
      }
    }

    // Progress bars are now handled inline with services above
  } catch (err) {
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
        
        // Update pipeline activity indicator with first running execution
        const runningExec = activeExecutions.find(exec => exec.status === 'running');
        updatePipelineActivityFromExecution(runningExec);
    } else {
        execListActive.innerHTML = '<li class="muted">No active executions</li>';
        execListBacklog.innerHTML = '<li class="muted">No queued executions</li>';
        updatePipelineActivityFromExecution(null);
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
  const verbositySelect = document.getElementById('manual-process-log-verbosity');
  
  // Show modal
  modal.style.display = 'flex';
  listContainer.innerHTML = '<p class="muted">Loading recordings...</p>';
  
  try {
    const verbosityRes = await fetch('/api/logging/verbosity');
    if (verbosityRes.ok) {
      const verbosityData = await verbosityRes.json();
      if (verbosityData.verbosity && verbositySelect) {
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
        
        // Disable checkbox if recording is not yet completed
        const checkboxDisabled = !recording.completed ? 'disabled title="Recording in progress"' : '';
        
        tableHtml += `
          <tr style="border-bottom: 1px solid var(--border);">
            <td style="padding: 8px 4px;">
              <input type="checkbox" name="manual-process-path" value="${escapeAttr(recording.path)}" data-idx="${idx}" ${checkboxDisabled}>
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
  // Find and activate the button for this tab
  const buttons = document.querySelectorAll('.tab-btn');
  buttons.forEach((btn, index) => {
    const expectedTabs = ['executions', 'logs', 'glances'];
    if (expectedTabs[index] === tabName) {
      btn.classList.add('active');
    }
  });
  
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
  
  // Handle system monitor - only when glances tab is active
  if (tabName === 'glances') {
    startSystemMonitor();
  } else {
    stopSystemMonitor();
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
    const res = await fetch('/api/env-settings');
    if (!res.ok) throw new Error('Failed to load settings');
    const data = await res.json();
    renderSettingsUI(data);
  } catch (err) {
    console.error('Failed to load settings:', err);
    const container = document.getElementById('settings-container');
    if (container) {
      container.innerHTML = `<p style="color:red;">Failed to load settings: ${err.message}</p>`;
    }
  }
}

function renderSettingsUI(settings) {
  const container = document.getElementById('settings-container');
  if (!container) return;
  
  const categoryTitles = {
    channels_dvr: 'Channels DVR Configuration',
    channelwatch: 'ChannelWatch Configuration', 
    event_source: 'Event Source Configuration',
    polling: 'Polling Source Configuration',
    webhook: 'Webhook Server Configuration',
    pipeline: 'Caption Pipeline Configuration',
    state_logging: 'State and Logging Configuration',
    advanced: 'Advanced Configuration'
  };
  
  const booleanFields = ['USE_MOCK', 'USE_POLLING', 'USE_WEBHOOK', 'TRANSCODE_FOR_FIRETV', 
                         'KEEP_ORIGINAL', 'DRY_RUN'];
  
  // Fields to hide (replaced by other settings)
  const hiddenFields = ['USE_MOCK', 'USE_POLLING', 'USE_WEBHOOK'];  // Replaced by DISCOVERY_MODE
  
  const dropdownFields = {
    'DISCOVERY_MODE': ['polling', 'webhook', 'mock'],
    'OPTIMIZATION_MODE': ['standard', 'automatic'],
    'LOG_LEVEL': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
  };
  
  const numericFields = ['POLL_INTERVAL_SECONDS', 'POLL_LIMIT', 'WEBHOOK_PORT', 
                         'PIPELINE_TIMEOUT', 'STALE_EXECUTION_SECONDS', 'API_TIMEOUT'];
  
  // Get discovery mode to conditionally show/hide sections
  const discoveryMode = settings.event_source?.DISCOVERY_MODE?.value || 'webhook';
  
  let html = '';
  
  for (const [category, items] of Object.entries(settings)) {
    if (!items || typeof items !== 'object' || Object.keys(items).length === 0) continue;
    
    // Hide channelwatch and webhook sections when using polling
    if (discoveryMode === 'polling' && (category === 'channelwatch' || category === 'webhook')) {
      continue;
    }
    
    html += `<div class="settings-category" style="margin-bottom: 24px;">`;
    html += `<h3 style="margin: 0 0 16px 0; font-size: 16px; color: var(--text); border-bottom: 2px solid var(--panel-border); padding-bottom: 8px;">
              ${categoryTitles[category] || category}
             </h3>`;
    
    for (const [key, config] of Object.entries(items)) {
      // Skip hidden fields (replaced by other settings)
      if (hiddenFields.includes(key)) continue;
      
      const value = config.value || '';
      const desc = config.description || '';
      const defaultVal = config.default || '';
      const isOptional = config.optional || false;
      
      html += `<div class="settings-group" style="margin-bottom: 16px;">`;
      html += `<label for="env-${key}" style="font-weight: 600; display: block; margin-bottom: 4px;">
                ${key}${isOptional ? ' <span style="color: var(--muted); font-weight: normal;">(optional)</span>' : ''}
               </label>`;
      
      if (desc) {
        html += `<p style="font-size: 12px; color: var(--muted); margin: 0 0 8px 0;">${desc}</p>`;
      }
      
      // Dropdown fields
      if (dropdownFields[key]) {
        html += `<select id="env-${key}" name="${key}" data-category="${category}" style="width:100%;">`;
        for (const option of dropdownFields[key]) {
          const selected = value === option ? 'selected' : '';
          html += `<option value="${option}" ${selected}>${option}</option>`;
        }
        html += `</select>`;
      }
      // Boolean fields as checkbox
      else if (booleanFields.includes(key)) {
        const checked = value.toLowerCase() === 'true' ? 'checked' : '';
        html += `<input type="checkbox" id="env-${key}" name="${key}" data-category="${category}" ${checked}>`;
      }
      // Numeric fields
      else if (numericFields.includes(key)) {
        html += `<input type="number" id="env-${key}" name="${key}" data-category="${category}" value="${value}" placeholder="${defaultVal}" style="width:100%;">`;
      }
      // Long text fields as textarea
      else if (key.includes('COMMAND') || (key.includes('PATH') && value.length > 50)) {
        html += `<textarea id="env-${key}" name="${key}" data-category="${category}" rows="2" style="width:100%; font-family: monospace; font-size: 12px;">${value}</textarea>`;
      }
      // Regular text input
      else {
        html += `<input type="text" id="env-${key}" name="${key}" data-category="${category}" value="${value}" placeholder="${defaultVal}" style="width:100%;">`;
      }
      
      html += `</div>`;
    }
    
    html += `</div>`;
  }
  
  if (html.length === 0) {
    container.innerHTML = '<p style="color: orange;">No settings found in response.</p>';
  } else {
    container.innerHTML = html;
  }
}

async function saveEnvSettings(event) {
  event.preventDefault();
  
  // Collect all settings grouped by category
  const form = document.getElementById('settings-form');
  const inputs = form.querySelectorAll('input, textarea, select');
  const settings = {};
  
  inputs.forEach(input => {
    const category = input.dataset.category;
    const name = input.name;
    
    if (!category || !name) return;
    
    if (!settings[category]) {
      settings[category] = {};
    }
    
    let value;
    if (input.type === 'checkbox') {
      value = input.checked ? 'true' : 'false';
    } else {
      value = input.value;
    }
    
    settings[category][name] = { value };
  });
  
  try {
    const res = await fetch('/api/env-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    const data = await res.json();
    
    if (!res.ok || data.error) {
      throw new Error(data.error || 'Failed to save settings');
    }
    
    alert('✓ Settings saved to .env file!\n\nPlease restart the application for changes to take effect.');
    closeSettingsModal();
  } catch (err) {
    alert('✗ Failed to save settings: ' + err.message);
  }
}

async function saveSettings(event) {
  // Legacy function - kept for compatibility
  event.preventDefault();
  const payload = {
    discovery_mode: document.getElementById('discovery-mode-select')?.value,
    dry_run: document.getElementById('dry-run-toggle')?.checked,
    keep_original: document.getElementById('keep-original-toggle')?.checked,
    log_verbosity: document.getElementById('log-verbosity-select')?.value,
    whisper_model: document.getElementById('whisper-model-select')?.value,
    whitelist: document.getElementById('whitelist-editor')?.value,
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
// Settings now loaded on-demand when settings modal opens
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
    // Load settings when modal opens
    loadSettings();
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

// =========================
// System Monitor
// =========================

let monitorCharts = null;
let monitorInterval = null;
const MONITOR_WINDOW_SEC = 300; // 5 minutes
const MONITOR_MAX_POINTS = 300; // 5 minutes at 1Hz

// Track maximum values seen for persistent scaling
const chartMaxValues = {
  cpu: 10,      // Start with 10% minimum
  disk: 1,      // Start with 1 MB/s minimum
  network: 1,   // Start with 1 Mbps minimum
  gpu: 10       // Start with 10% minimum
};

// Helper function to calculate chart width from container
function getChartWidth(chartEl) {
  if (!chartEl) return 600;
  // Go up to chart-container level to get true available width
  const container = chartEl.closest('.chart-container');
  if (!container) return 600;
  
  // Subtract padding (15px left + 15px right) + title width (80px) + gap (10px)
  const containerWidth = container.clientWidth;
  return Math.max(200, containerWidth - 120);
}

function initSystemMonitor() {
  if (monitorCharts) return; // Already initialized
  
  // Check if uPlot is available
  if (typeof uPlot === 'undefined') {
    console.error('uPlot library not loaded');
    return;
  }
  
  const cpuEl = document.getElementById('chart-cpu');
  const diskEl = document.getElementById('chart-disk');
  const networkEl = document.getElementById('chart-network');
  const gpuEl = document.getElementById('chart-gpu');
  
  if (!cpuEl || !diskEl || !networkEl) {
    console.error('Chart elements not found');
    return;
  }
  
  console.log('Initializing system monitor charts...');
  
  // Calculate initial chart width
  const chartWidth = getChartWidth(cpuEl);
  console.log('Chart width:', chartWidth);
  
  // Common options for all charts
  const commonOpts = {
    width: chartWidth,
    height: 130,
    class: 'monitor-chart',
    cursor: {
      show: true,
      drag: {
        x: false,
        y: false
      }
    },
    legend: {
      show: true,
      live: true
    },
    scales: {
      x: { time: true },
      y: { 
        auto: false,
        range: (u, dataMin, dataMax) => {
          // Use tracked max or a minimum value
          const chartId = u.root.parentElement.id.replace('chart-', '');
          const max = chartMaxValues[chartId] || 10;
          return [0, Math.max(max, 10)];
        }
      }
    },
    axes: [
      { 
        show: true,
        scale: 'x', 
        space: 80, 
        incrs: [10, 30, 60, 120, 300], 
        values: (u, vals) => vals.map(v => new Date(v * 1000).toLocaleTimeString()),
        stroke: '#ffffff',
        grid: { stroke: '#333', width: 1 }
      },
      { 
        show: true,
        scale: 'y', 
        space: 40,
        stroke: '#ffffff',
        grid: { stroke: '#333', width: 1 }
      }
    ]
  };
  
  try {
    // CPU Chart
    console.log('Creating CPU chart...');
    monitorCharts = {
      cpu: new uPlot({
        ...commonOpts,
        series: [
          {},
          { label: 'CPU %', stroke: '#5ce1e6', width: 2, fill: 'rgba(92, 225, 230, 0.1)', points: {show: false} }
        ]
      }, [[], []], cpuEl),
      
      // Disk Chart
      disk: new uPlot({
        ...commonOpts,
        series: [
          {},
          { label: 'Read MB/s', stroke: '#5ce1e6', width: 2, fill: 'rgba(92, 225, 230, 0.1)', points: {show: false} },
          { label: 'Write MB/s', stroke: '#ffb347', width: 2, fill: 'rgba(255, 179, 71, 0.1)', points: {show: false} }
        ]
      }, [[], [], []], diskEl),
      
      // Network Chart
      network: new uPlot({
        ...commonOpts,
        series: [
          {},
          { label: 'RX Mbps', stroke: '#5ce1e6', width: 2, fill: 'rgba(92, 225, 230, 0.1)', points: {show: false} },
          { label: 'TX Mbps', stroke: '#ffb347', width: 2, fill: 'rgba(255, 179, 71, 0.1)', points: {show: false} }
        ]
      }, [[], [], []], networkEl)
    };
    
    // Don't create GPU chart yet - will be created when first needed
    monitorCharts.gpu = null;
    
    console.log('Charts created. CPU chart:', monitorCharts.cpu);
    console.log('CPU chart has legend?', monitorCharts.cpu.root.querySelector('.u-legend') !== null);
    console.log('CPU chart has axes?', monitorCharts.cpu.root.querySelectorAll('.u-axis').length);
    console.log('GPU chart deferred - will be created when GPU becomes available');
    
    console.log('Charts initialized successfully');
    
    // Load historical data to populate charts immediately
    loadHistoricalData().then(() => {
      console.log('Historical data loaded');
    }).catch(err => {
      console.error('Failed to load historical data:', err);
    });
    
    // Add resize handler
    let resizeTimeout;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        if (monitorCharts) {
          // Calculate width for each chart from its container (not wrapper)
          const cpuWidth = getChartWidth(cpuEl);
          const diskWidth = getChartWidth(diskEl);
          const networkWidth = getChartWidth(networkEl);
          
          console.log('Window resized. Container width:', cpuEl.closest('.chart-container').clientWidth);
          console.log('Calculated chart width:', cpuWidth);
          console.log('Current CPU chart width:', monitorCharts.cpu.width);
          
          // Force canvas elements to update their width attribute before setSize
          if (monitorCharts.cpu.root) {
            const cpuCanvas = monitorCharts.cpu.root.querySelector('canvas');
            if (cpuCanvas) cpuCanvas.style.width = cpuWidth + 'px';
          }
          if (monitorCharts.disk.root) {
            const diskCanvas = monitorCharts.disk.root.querySelector('canvas');
            if (diskCanvas) diskCanvas.style.width = diskWidth + 'px';
          }
          if (monitorCharts.network.root) {
            const networkCanvas = monitorCharts.network.root.querySelector('canvas');
            if (networkCanvas) networkCanvas.style.width = networkWidth + 'px';
          }
          
          monitorCharts.cpu.setSize({ width: cpuWidth, height: 130 });
          monitorCharts.disk.setSize({ width: diskWidth, height: 130 });
          monitorCharts.network.setSize({ width: networkWidth, height: 130 });
          
          if (monitorCharts.gpu && gpuEl) {
            const gpuWidth = getChartWidth(gpuEl);
            if (monitorCharts.gpu.root) {
              const gpuCanvas = monitorCharts.gpu.root.querySelector('canvas');
              if (gpuCanvas) gpuCanvas.style.width = gpuWidth + 'px';
            }
            monitorCharts.gpu.setSize({ width: gpuWidth, height: 130 });
          }
          
          console.log('Charts resized. New CPU width:', monitorCharts.cpu.width);
        }
      }, 250); // Debounce resize events
    });
  } catch (error) {
    console.error('Failed to create charts:', error);
    monitorCharts = null;
  }
}

function updateSystemMonitor() {
  fetch('/api/monitor/latest')
    .then(res => {
      if (!res.ok) {
        console.error('Monitor API returned status:', res.status);
        throw new Error('API request failed');
      }
      return res.json();
    })
    .then(data => {
      if (!monitorCharts) {
        console.error('Monitor charts not initialized');
        return;
      }
      
      const metrics = data.metrics;
      const pipeline = data.pipeline;
      const gpuProvider = data.gpu_provider;
      
      if (!metrics) {
        console.error('No metrics data received');
        return;
      }
      
      const timestamp = metrics.timestamp;
      
      // Update CPU chart
      appendChartData(monitorCharts.cpu, timestamp, [metrics.cpu_percent]);
      
      // Update Disk chart
      appendChartData(monitorCharts.disk, timestamp, [
        metrics.disk_read_mbps,
        metrics.disk_write_mbps
      ]);
      
      // Update Network chart
      appendChartData(monitorCharts.network, timestamp, [
        metrics.net_recv_mbps,
        metrics.net_sent_mbps
      ]);
      
      // Update GPU chart if available
      const gpuContainer = document.getElementById('gpu-chart-container');
      const gpuUnavailable = document.getElementById('gpu-unavailable');
      
      if (gpuProvider.available && metrics.gpu_util_percent !== null) {
        const wasHidden = gpuContainer && gpuContainer.style.display === 'none';
        if (gpuContainer) gpuContainer.style.display = 'flex';
        if (gpuUnavailable) gpuUnavailable.style.display = 'none';
        
        // Create GPU chart on first use (when container is already visible)
        if (!monitorCharts.gpu && gpuEl) {
          const gpuWidth = getChartWidth(gpuEl);
          console.log('Creating GPU chart with width:', gpuWidth);
          
          const gpuOpts = {
            width: gpuWidth,
            height: 130,
            class: 'monitor-chart',
            cursor: {
              show: true,
              drag: { x: false, y: false }
            },
            legend: {
              show: true,
              live: true
            },
            scales: {
              x: { time: true },
              y: { 
                auto: false,
                range: (u, dataMin, dataMax) => {
                  const max = chartMaxValues.gpu || 10;
                  return [0, Math.max(max, 10)];
                }
              }
            },
            axes: [
              { 
                show: true,
                scale: 'x', 
                space: 80, 
                incrs: [10, 30, 60, 120, 300], 
                values: (u, vals) => vals.map(v => new Date(v * 1000).toLocaleTimeString()),
                stroke: '#ffffff',
                grid: { stroke: '#333', width: 1 }
              },
              { 
                show: true,
                scale: 'y', 
                space: 40,
                stroke: '#ffffff',
                grid: { stroke: '#333', width: 1 }
              }
            ]
          };
          
          try {
            monitorCharts.gpu = new uPlot({
              ...gpuOpts,
              series: [
                {},
                { label: 'GPU %', stroke: '#5ce1e6', width: 2, fill: 'rgba(92, 225, 230, 0.1)', points: {show: false} },
                { label: 'VRAM %', stroke: '#ffb347', width: 2, fill: 'rgba(255, 179, 71, 0.1)', points: {show: false} }
              ]
            }, [[], [], []], gpuEl);
            
            console.log('GPU chart created successfully. Width:', monitorCharts.gpu.width);
            console.log('GPU chart element:', monitorCharts.gpu.root);
            
            // Force layout recalculation for flex centering
            gpuContainer.style.display = 'none';
            void gpuContainer.offsetHeight; // Force reflow
            gpuContainer.style.display = 'flex';
          } catch (error) {
            console.error('Failed to create GPU chart:', error);
            monitorCharts.gpu = null;
          }
        }
        
        if (monitorCharts.gpu) {
          const vramPct = metrics.gpu_mem_total_mb > 0 
            ? (metrics.gpu_mem_used_mb / metrics.gpu_mem_total_mb) * 100 
            : 0;
          console.log('Appending GPU data:', metrics.gpu_util_percent, vramPct);
          appendChartData(monitorCharts.gpu, timestamp, [
            metrics.gpu_util_percent,
            vramPct
          ]);
        }
      } else {
        if (gpuContainer) gpuContainer.style.display = 'none';
        if (gpuUnavailable) {
          gpuUnavailable.style.display = 'block';
          const reason = gpuProvider.available ? 'No GPU metrics' : gpuProvider.name;
          gpuUnavailable.innerHTML = `<div style="color: #888;">GPU monitoring not available<br><small style="font-size: 0.9em;">${reason}</small></div>`;
        }
      }
      
      // Update pipeline status
      updatePipelineStatus(pipeline);
      
      // Update pipeline activity indicator
      updatePipelineActivityIndicator(pipeline);
    })
    .catch(err => console.error('Failed to fetch monitor data:', err));
}

async function loadHistoricalData() {
  try {
    const response = await fetch('/api/monitor/window?seconds=300');
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    
    const data = await response.json();
    const metrics = data.metrics;
    const gpuProvider = data.gpu_provider;
    
    if (!metrics || metrics.length === 0) {
      console.log('No historical data available');
      return;
    }
    
    console.log(`Loading ${metrics.length} historical data points`);
    
    // Build data arrays for each chart
    const cpuData = [[], []];
    const diskData = [[], [], []];
    const networkData = [[], [], []];
    let gpuData = null;
    let hasGpuData = false;
    
    // Process historical metrics
    for (const metric of metrics) {
      const ts = metric.timestamp;
      
      // CPU
      cpuData[0].push(ts);
      cpuData[1].push(metric.cpu_percent);
      
      // Disk
      diskData[0].push(ts);
      diskData[1].push(metric.disk_read_mbps);
      diskData[2].push(metric.disk_write_mbps);
      
      // Network
      networkData[0].push(ts);
      networkData[1].push(metric.net_recv_mbps);
      networkData[2].push(metric.net_sent_mbps);
      
      // GPU (if available)
      if (metric.gpu_util_percent !== null) {
        if (!gpuData) {
          gpuData = [[], [], []];
        }
        hasGpuData = true;
        const vramPct = metric.gpu_mem_total_mb > 0
          ? (metric.gpu_mem_used_mb / metric.gpu_mem_total_mb) * 100
          : 0;
        gpuData[0].push(ts);
        gpuData[1].push(metric.gpu_util_percent);
        gpuData[2].push(vramPct);
      }
    }
    
    // Update charts with historical data
    monitorCharts.cpu.setData(cpuData);
    monitorCharts.disk.setData(diskData);
    monitorCharts.network.setData(networkData);
    
    // Calculate max values from historical data
    chartMaxValues.cpu = Math.max(...cpuData[1], 10) * 1.1;
    chartMaxValues.disk = Math.max(
      ...diskData[1],
      ...diskData[2],
      1
    ) * 1.1;
    chartMaxValues.network = Math.max(
      ...networkData[1],
      ...networkData[2],
      1
    ) * 1.1;
    
    // Create and populate GPU chart if historical data exists
    if (hasGpuData && gpuData && gpuProvider.available) {
      const gpuContainer = document.getElementById('gpu-chart-container');
      const gpuEl = document.getElementById('chart-gpu');
      const gpuUnavailable = document.getElementById('gpu-unavailable');
      
      if (gpuContainer) gpuContainer.style.display = 'block';
      if (gpuUnavailable) gpuUnavailable.style.display = 'none';
      
      if (gpuEl && !monitorCharts.gpu) {
        // Wait for layout to complete before creating chart
        requestAnimationFrame(() => {
          // Use CPU container width (already visible) instead of GPU container
          const cpuEl = document.getElementById('chart-cpu');
          const gpuWidth = cpuEl ? getChartWidth(cpuEl) : getChartWidth(gpuEl);
          console.log('Creating GPU chart from historical data with width:', gpuWidth);
          
          const gpuOpts = {
            width: gpuWidth,
            height: 130,
            class: 'monitor-chart',
            legend: { show: true, live: false },
            scales: {
              x: { time: true },
              y: {
                auto: false,
                range: (u, dataMin, dataMax) => {
                  const max = chartMaxValues.gpu || 10;
                  return [0, Math.max(max, 10)];
                }
              }
            },
            axes: [
              {
                show: true,
                scale: 'x',
                space: 80,
                incrs: [10, 30, 60, 120, 300],
                values: (u, vals) => vals.map(v => new Date(v * 1000).toLocaleTimeString()),
                stroke: '#ffffff',
                grid: { stroke: '#333', width: 1 }
              },
              {
                show: true,
                scale: 'y',
                space: 40,
                stroke: '#ffffff',
                grid: { stroke: '#333', width: 1 }
              }
            ]
          };
          
          monitorCharts.gpu = new uPlot({
            ...gpuOpts,
            series: [
              {},
              { label: 'GPU %', stroke: '#5ce1e6', width: 2, fill: 'rgba(92, 225, 230, 0.1)', points: {show: false} },
              { label: 'VRAM %', stroke: '#ffb347', width: 2, fill: 'rgba(255, 179, 71, 0.1)', points: {show: false} }
            ]
          }, gpuData, gpuEl);
          
          // Calculate max from GPU data
          chartMaxValues.gpu = Math.max(
            ...gpuData[1],
            ...gpuData[2],
            10
          ) * 1.1;
          
          console.log('GPU chart created from historical data. Width:', monitorCharts.gpu.width);
          
          // Force layout recalculation for flex centering
          const gpuChartContainer = document.getElementById('gpu-chart-container');
          if (gpuChartContainer) {
            gpuChartContainer.style.display = 'none';
            void gpuChartContainer.offsetHeight; // Force reflow
            gpuChartContainer.style.display = 'flex';
          }
        });
      }
    }
    
    console.log('Historical data loaded. Max values:', chartMaxValues);
    
  } catch (error) {
    console.error('Error loading historical data:', error);
  }
}

function appendChartData(chart, timestamp, values) {
  const data = chart.data;
  const maxPoints = MONITOR_MAX_POINTS;
  
  // Track maximum value encountered (for persistent scaling)
  const chartId = chart.root.parentElement.id.replace('chart-', '');
  let maxVal = 0;
  values.forEach(v => {
    if (v !== null && v !== undefined) {
      maxVal = Math.max(maxVal, v);
    }
  });
  
  // Update tracked max if we've seen a higher value
  if (maxVal > chartMaxValues[chartId]) {
    chartMaxValues[chartId] = maxVal * 1.1; // Add 10% headroom
    // Update the scale range
    chart.scales.y.range = () => [0, Math.max(chartMaxValues[chartId], 10)];
  }
  
  // Append new data
  data[0].push(timestamp);
  for (let i = 0; i < values.length; i++) {
    data[i + 1].push(values[i]);
  }
  
  // Trim old data if exceeds max points
  if (data[0].length > maxPoints) {
    data.forEach(series => series.shift());
  }
  
  chart.setData(data);
}

function updatePipelineStatus(pipeline) {
  const pipelineInfo = document.getElementById('pipeline-info');
  if (!pipelineInfo) return;
  
  if (!pipeline.active) {
    pipelineInfo.innerHTML = '<div class="pipeline-idle">No active pipeline</div>';
    return;
  }
  
  const stage = pipeline.current_stage;
  const stages = pipeline.stages || [];
  
  let html = '<div class="pipeline-active">';
  
  if (stage) {
    html += `
      <div class="pipeline-row">
        <div class="pipeline-label">Current Stage</div>
        <div class="pipeline-value pipeline-stage">
          ${stage.stage}
          ${stage.gpu_engaged ? '<span class="gpu-engaged-badge">GPU Active</span>' : ''}
        </div>
      </div>
      <div class="pipeline-row">
        <div class="pipeline-label">File</div>
        <div class="pipeline-value">${stage.filename}</div>
      </div>
      <div class="pipeline-row">
        <div class="pipeline-label">Elapsed</div>
        <div class="pipeline-value">${stage.elapsed.toFixed(1)}s</div>
      </div>
    `;
  }
  
  if (stages.length > 0) {
    html += `
      <div class="pipeline-row">
        <div class="pipeline-label">Completed Stages</div>
        <div class="pipeline-value">${stages.length}</div>
      </div>
    `;
    
    stages.forEach(s => {
      html += `
        <div class="pipeline-row">
          <div class="pipeline-label">${s.stage}</div>
          <div class="pipeline-value">
            ${s.duration ? s.duration.toFixed(1) + 's' : 'pending'}
            ${s.gpu_engaged ? '<span class="gpu-engaged-badge">GPU</span>' : ''}
          </div>
        </div>
      `;
    });
  }
  
  html += '</div>';
  pipelineInfo.innerHTML = html;
}

function updatePipelineActivityFromExecution(execution) {
  const indicator = document.getElementById('pipeline-activity-indicator');
  if (!indicator) return;
  
  if (execution && execution.input_path) {
    // Show full file path
    const displayPath = execution.input_path;
    indicator.innerHTML = `Pipeline Activity: <strong style="color: var(--text);">${displayPath}</strong>`;
  } else {
    indicator.textContent = 'Real-time system and pipeline monitoring';
  }
}

function updatePipelineActivityIndicator(pipeline) {
  // Legacy function - kept for backward compatibility
  // Now handled by updatePipelineActivityFromExecution
}

function startSystemMonitor() {
  if (monitorInterval) return; // Already running
  
  console.log('Starting system monitor...');
  initSystemMonitor();
  if (!monitorCharts) {
    console.error('Failed to initialize monitor charts');
    return;
  }
  updateSystemMonitor();
  monitorInterval = setInterval(updateSystemMonitor, 1000); // 1Hz
  console.log('System monitor started');
}

function stopSystemMonitor() {
  if (monitorInterval) {
    clearInterval(monitorInterval);
    monitorInterval = null;
  }
}

// Auto-start if System Monitor tab is default
window.addEventListener('DOMContentLoaded', () => {
  const activeTab = document.querySelector('.tab-content.active');
  if (activeTab && activeTab.id === 'glances-tab') {
    startSystemMonitor();
  }
});




