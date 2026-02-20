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
          // Use blue color for Channels DVR, green for others
          const healthClass = svc.healthy 
            ? (svc.name === 'Channels DVR' ? 'service-healthy-blue' : 'service-healthy')
            : 'service-unhealthy';
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

    // Update consolidated heartbeat indicator with priority-based pulse animation
    if (data.heartbeat) {
      const pollingIndicator = document.getElementById('heartbeat-polling');
      if (pollingIndicator) {
        // Priority order: API polling > manual queue > other
        let mostRecentPriority = null;
        let mostRecentAge = Infinity;
        
        // Check all heartbeats and determine which one to show
        for (const [name, hb] of Object.entries(data.heartbeat)) {
          if (hb.alive && hb.age_seconds < 0.5) {
            const priority = name === 'polling' ? 1 : (name === 'manual' ? 2 : 3);
            if (priority < (mostRecentPriority || 999)) {
              mostRecentPriority = priority;
              mostRecentAge = hb.age_seconds;
            }
          }
        }
        
        // Apply appropriate pulse animation based on priority
        if (mostRecentPriority === 1) {
          // API polling - blue pulse (500ms)
          pollingIndicator.classList.remove('pulse-blue', 'pulse-green', 'pulse-yellow');
          void pollingIndicator.offsetWidth; // Force reflow
          pollingIndicator.classList.add('pulse-blue');
          setTimeout(() => pollingIndicator.classList.remove('pulse-blue'), 500);
        } else if (mostRecentPriority === 2) {
          // Manual queue - green pulse (500ms)
          pollingIndicator.classList.remove('pulse-blue', 'pulse-green', 'pulse-yellow');
          void pollingIndicator.offsetWidth; // Force reflow
          pollingIndicator.classList.add('pulse-green');
          setTimeout(() => pollingIndicator.classList.remove('pulse-green'), 500);
        } else if (mostRecentPriority === 3) {
          // Other polling - yellow pulse (250ms)
          pollingIndicator.classList.remove('pulse-blue', 'pulse-green', 'pulse-yellow');
          void pollingIndicator.offsetWidth; // Force reflow
          pollingIndicator.classList.add('pulse-yellow');
          setTimeout(() => pollingIndicator.classList.remove('pulse-yellow'), 250);
        } else if (!mostRecentPriority) {
          // No recent activity - check if any are alive
          let anyAlive = false;
          for (const [name, hb] of Object.entries(data.heartbeat)) {
            if (hb.alive && hb.age_seconds < 4) {
              anyAlive = true;
              break;
            }
          }
          pollingIndicator.style.color = anyAlive ? '#666' : '#666';
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
  
  // Fields to hide (replaced by other settings or not user-configurable)
  const hiddenFields = ['USE_MOCK', 'USE_POLLING', 'USE_WEBHOOK', 'CAPTION_COMMAND'];  // DISCOVERY_MODE replaces first 3, CAPTION_COMMAND is auto-detected
  
  const dropdownFields = {
    'DISCOVERY_MODE': ['polling', 'webhook', 'mock'],
    'OPTIMIZATION_MODE': ['standard', 'automatic'],
    'WHISPER_DEVICE': ['auto', 'nvidia', 'amd', 'intel', 'none'],
    'LOG_LEVEL': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
  };
  
  // Common IANA timezones grouped by region
  const timezones = [
    '(System Default)',
    '--- Americas ---',
    'America/New_York',
    'America/Chicago', 
    'America/Denver',
    'America/Phoenix',
    'America/Los_Angeles',
    'America/Anchorage',
    'America/Honolulu',
    'America/Toronto',
    'America/Vancouver',
    'America/Mexico_City',
    'America/Sao_Paulo',
    'America/Buenos_Aires',
    '--- Europe ---',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Europe/Rome',
    'Europe/Amsterdam',
    'Europe/Brussels',
    'Europe/Vienna',
    'Europe/Stockholm',
    'Europe/Moscow',
    '--- Asia ---',
    'Asia/Dubai',
    'Asia/Kolkata',
    'Asia/Bangkok',
    'Asia/Singapore',
    'Asia/Hong_Kong',
    'Asia/Shanghai',
    'Asia/Tokyo',
    'Asia/Seoul',
    '--- Pacific ---',
    'Australia/Sydney',
    'Australia/Melbourne',
    'Australia/Brisbane',
    'Australia/Perth',
    'Pacific/Auckland',
    '--- Other ---',
    'UTC'
  ];
  
  // Get client's local timezone
  const clientTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  
  const numericFields = ['POLL_INTERVAL_SECONDS', 'POLL_LIMIT', 'WEBHOOK_PORT', 
                         'PIPELINE_TIMEOUT', 'STALE_EXECUTION_SECONDS', 'API_TIMEOUT', 'CAPTION_DELAY_MS'];
  
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
      // SERVER_TZ timezone dropdown with client timezone preselected
      else if (key === 'SERVER_TZ') {
        html += `<select id="env-${key}" name="${key}" data-category="${category}" style="width:100%;">`;
        
        // Determine which timezone should be selected
        // If value is empty or default, use client timezone
        const effectiveValue = (value && value !== 'System timezone') ? value : clientTimezone;
        
        for (const tz of timezones) {
          // Skip section headers (start with ---)
          if (tz.startsWith('---')) {
            html += `<option disabled>────────────────</option>`;
            continue;
          }
          
          // System default option
          if (tz === '(System Default)') {
            const selected = (!value || value === 'System timezone') ? 'selected' : '';
            html += `<option value="" ${selected}>${tz}</option>`;
            continue;
          }
          
          // Regular timezone
          const selected = effectiveValue === tz ? 'selected' : '';
          html += `<option value="${tz}" ${selected}>${tz}</option>`;
        }
        
        html += `</select>`;
        html += `<p style="font-size: 11px; color: var(--muted); margin: 4px 0 0 0;">
                  Your browser timezone: ${clientTimezone}
                 </p>`;
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
    height: 117,
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
            height: 117,
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
            height: 117,
            class: 'monitor-chart',
            cursor: {
              show: true,
              drag: { x: false, y: false }
            },
            legend: { show: true, live: true },
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

// Pipeline stage definitions with metadata
const PIPELINE_STAGES = {
  'file_stability': { display: 'File Stability', group: 'validation', weight: 5, description: 'Waiting for recording to complete' },
  'whisper': { display: 'Transcription', group: 'whisper', weight: 25, description: 'Faster-Whisper AI transcription to SRT' },
  'file_copy': { display: 'Backup', group: 'encoding', weight: 5, description: 'Preserving original as .orig' },
  'ffmpeg_encode': { display: 'A/V Encode', group: 'encoding', weight: 45, description: 'Encoding audio/video streams to temp file' },
  'probe_av': { display: 'Probe', group: 'verification', weight: 3, description: 'Probing encoded media duration' },
  'shift_srt': { display: 'Caption Delay', group: 'verification', weight: 3, description: 'Shifting caption timestamps (accessibility delay)' },
  'clamp_srt': { display: 'Clamp SRT', group: 'verification', weight: 3, description: 'Clamping subtitle timestamps to media duration' },
  'ffmpeg_mux': { display: 'Mux Captions', group: 'encoding', weight: 4, description: 'Muxing subtitles into video container' },
  'verify_mux': { display: 'Verify', group: 'verification', weight: 3, description: 'Verifying output compatibility' },
  'replace_output': { display: 'Finalize', group: 'finalization', weight: 3, description: 'Replacing original with captioned version' },
  'cleanup': { display: 'Cleanup', group: 'finalization', weight: 3, description: 'Removing temporary files' }
};

const STAGE_GROUPS = {
  'validation': { label: 'Validation', color: 'stage-validation' },
  'whisper': { label: 'Whisper AI', color: 'stage-whisper' },
  'encoding': { label: 'Encoding', color: 'stage-encoding' },
  'verification': { label: 'Verification', color: 'stage-verification' },
  'finalization': { label: 'Finalization', color: 'stage-finalization' }
};

const COMPLETION_DISPLAY_DURATION = 30; // 30 seconds

function updatePipelineStatus(pipeline) {
  const pipelineInfo = document.getElementById('pipeline-info');
  if (!pipelineInfo) return;
  
  const completedStages = pipeline.stages || [];
  const currentStage = pipeline.current_stage;
  
  // Check if job is completed
  const allCompleted = !currentStage && (completedStages.some(s => s.stage === 'cleanup') || completedStages.some(s => s.stage === 'replace_output'));
  
  // If completed, calculate how long ago based on last stage end time
  if (allCompleted && completedStages.length > 0) {
    // Find the last stage (cleanup or replace_output)
    const lastStage = completedStages[completedStages.length - 1];
    if (lastStage.ended_at) {
      const completionAge = Date.now() / 1000 - lastStage.ended_at; // Age in seconds
      if (completionAge > COMPLETION_DISPLAY_DURATION) {
        // Completed more than 30 seconds ago, clear it
        pipelineInfo.innerHTML = '<div class="pipeline-info-text">No active transcription pipeline</div>';
        return;
      }
    }
  }
  
  // Show "No active pipeline" only if nothing is active AND no completed stages
  if (!pipeline.active && completedStages.length === 0) {
    pipelineInfo.innerHTML = '<div class="pipeline-info-text">No active transcription pipeline</div>';
    return;
  }
  
  // Calculate total elapsed time
  let totalElapsed = 0;
  completedStages.forEach(s => {
    if (s.duration) totalElapsed += s.duration;
  });
  if (currentStage && currentStage.elapsed) {
    totalElapsed += currentStage.elapsed;
  }
  
  // Build list of all stages with status
  const allStageNames = Object.keys(PIPELINE_STAGES);
  const completedStageNames = new Set(completedStages.map(s => s.stage));
  const currentStageName = currentStage ? currentStage.stage : null;
  
  const stageStatuses = allStageNames.map(stageName => {
    const meta = PIPELINE_STAGES[stageName];
    let status = 'pending';
    let duration = null;
    let gpuEngaged = false;
    
    if (completedStageNames.has(stageName)) {
      status = 'completed';
      const completed = completedStages.find(s => s.stage === stageName);
      duration = completed ? completed.duration : null;
      gpuEngaged = completed ? completed.gpu_engaged : false;
    } else if (stageName === currentStageName) {
      status = 'active';
      duration = currentStage.elapsed;
      gpuEngaged = currentStage.gpu_engaged || false;
    }
    
    return { stageName, meta, status, duration, gpuEngaged };
  });
  
  // Calculate progress percentage (weighted by stage importance)
  const totalWeight = allStageNames.reduce((sum, name) => sum + PIPELINE_STAGES[name].weight, 0);
  let completedWeight = 0;
  stageStatuses.forEach(s => {
    if (s.status === 'completed') {
      completedWeight += s.meta.weight;
    } else if (s.status === 'active') {
      completedWeight += s.meta.weight * 0.5; // 50% credit for active stage
    }
  });
  let progressPercent = Math.round((completedWeight / totalWeight) * 100);
  
  // Force 100% when job is complete (allCompleted was detected earlier)
  if (allCompleted) {
    progressPercent = 100;
  }
  
  // Calculate precise pointer position within active segment
  let pointerPercent = progressPercent;
  if (currentStage) {
    // Find the active segment's position
    let leftEdgePercent = 0;
    for (let i = 0; i < stageStatuses.length; i++) {
      const s = stageStatuses[i];
      const segmentWidth = (s.meta.weight / totalWeight) * 100;
      
      if (s.status === 'active') {
        // Use asymptotic progress: approaches 90% of segment but never reaches end until complete
        // This creates a "loading bar" effect that slows down as it progresses
        const elapsed = currentStage.elapsed;
        
        // Stage-specific time estimates (very conservative to avoid overshooting)
        let expectedDuration;
        if (s.meta.weight >= 40) {
          // Heavy stages (ffmpeg_encode): 15 seconds per weight unit
          expectedDuration = s.meta.weight * 15;
        } else if (s.meta.weight >= 20) {
          // Medium-heavy stages (whisper): 10 seconds per weight unit
          expectedDuration = s.meta.weight * 10;
        } else if (s.meta.weight >= 5) {
          // Light stages (file_copy, etc): 5 seconds per weight unit
          expectedDuration = s.meta.weight * 5;
        } else {
          // Very light stages: 3 seconds per weight unit
          expectedDuration = s.meta.weight * 3;
        }
        
        // Asymptotic progress: 1 - e^(-elapsed/timeConstant)
        // This naturally slows down as it approaches the target
        const timeConstant = expectedDuration / 3; // Controls how fast it ramps up
        const rawProgress = 1 - Math.exp(-elapsed / timeConstant);
        
        // Cap at 90% of segment width until stage actually completes
        const maxProgress = 0.90;
        const internalProgress = Math.min(rawProgress, maxProgress);
        
        pointerPercent = leftEdgePercent + (segmentWidth * internalProgress);
        break;
      } else if (s.status === 'completed') {
        leftEdgePercent += segmentWidth;
      } else {
        // Pending segment, stop here
        break;
      }
    }
  }
  
  // Render progress bar UI
  let html = `
    <div class="pipeline-progress-container">
      <div class="pipeline-header">
        <div class="pipeline-file-name" title="${currentStage ? currentStage.filename : ''}">${currentStage ? currentStage.filename : 'Processing...'}</div>
        <div class="pipeline-stats">
          <span class="pipeline-percent">${progressPercent}%</span>
          <span class="pipeline-elapsed">${totalElapsed.toFixed(1)}s</span>
        </div>
      </div>
      
      <div class="pipeline-bar-wrapper">
        <div class="pipeline-bar">
  `;
  
  // Render progress segments
  stageStatuses.forEach(s => {
    const widthPercent = (s.meta.weight / totalWeight) * 100;
    const groupColor = STAGE_GROUPS[s.meta.group].color;
    const gpuIndicator = s.gpuEngaged ? ' ⚡ GPU' : '';
    const tooltipText = `${s.meta.display}: ${s.meta.description}${gpuIndicator}`;
    html += `
      <div class="pipeline-segment ${groupColor} ${s.status}" 
           style="width: ${widthPercent}%;"
           title="${tooltipText}">
        ${s.meta.display}
      </div>
    `;
  });
  
  html += `
        </div>
        <div class="pipeline-progress-pointer" style="left: ${pointerPercent}%;"></div>
      </div>
  `;
  
  // Render legend grouped by stage type
  html += '<div class="pipeline-legend">';
  const groupStats = {};
  stageStatuses.forEach(s => {
    const group = s.meta.group;
    if (!groupStats[group]) {
      groupStats[group] = { totalTime: 0, stages: [] };
    }
    if (s.duration) {
      groupStats[group].totalTime += s.duration;
    }
    groupStats[group].stages.push(s);
  });
  
  Object.entries(STAGE_GROUPS).forEach(([groupKey, groupMeta]) => {
    const stats = groupStats[groupKey];
    if (stats) {
      const timeStr = stats.totalTime > 0 ? `${stats.totalTime.toFixed(1)}s` : '—';
      html += `
        <div class="legend-item">
          <div class="legend-color ${groupMeta.color}"></div>
          <div class="legend-label">${groupMeta.label}</div>
          <div class="legend-time">${timeStr}</div>
        </div>
      `;
    }
  });
  html += '</div>';
  
  // Show current stage details or completion message
  if (currentStage) {
    const meta = PIPELINE_STAGES[currentStageName] || { display: currentStageName, description: 'Processing...' };
    html += `
      <div class="pipeline-current-step">
        <strong>Current:</strong> ${meta.display} — ${meta.description}
        ${currentStage.gpu_engaged ? '<strong style="color: var(--accent); margin-left: 8px;">⚡ GPU Active</strong>' : ''}
      </div>
    `;
  } else if (allCompleted) {
    // Calculate seconds remaining until auto-clear
    let secondsRemaining = COMPLETION_DISPLAY_DURATION;
    const lastStage = completedStages[completedStages.length - 1];
    if (lastStage && lastStage.ended_at) {
      const completionAge = Date.now() / 1000 - lastStage.ended_at;
      secondsRemaining = Math.max(0, Math.ceil(COMPLETION_DISPLAY_DURATION - completionAge));
    }
    html += `
      <div class="pipeline-current-step" style="border-left-color: #43e97b;">
        <strong style="color: #43e97b;">✓ Complete!</strong> All stages finished successfully.
        <span style="color: var(--muted); margin-left: 8px; font-size: 12px;">(clearing in ${secondsRemaining}s)</span>
      </div>
    `;
  }
  
  html += '</div>';
  pipelineInfo.innerHTML = html;
}

function updatePipelineActivityFromExecution(execution) {
  const indicator = document.getElementById('pipeline-activity-indicator');
  if (!indicator) return;
  
  if (execution && execution.path) {
    // Show full file path
    const displayPath = execution.path;
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




