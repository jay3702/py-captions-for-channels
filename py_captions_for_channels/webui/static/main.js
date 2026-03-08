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

    // Show a monitoring-only banner when PROCESSING_ENABLED=false
    let banner = document.getElementById('processing-disabled-banner');
    if (data.processing_enabled === false) {
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'processing-disabled-banner';
        banner.style.cssText = [
          'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:9999',
          'background:#b45309', 'color:#fff', 'text-align:center',
          'padding:6px 12px', 'font-size:13px', 'font-weight:600',
          'letter-spacing:0.02em'
        ].join(';');
        banner.textContent =
          '⚠️  MONITORING ONLY — PROCESSING_ENABLED=false: no caption jobs will run';
        document.body.prepend(banner);
      }
    } else if (banner) {
      banner.remove();
    }

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
        // Priority order: API polling > manual queue
        let mostRecentPriority = null;
        let mostRecentAge = Infinity;
        
        // Check all heartbeats and determine which one to show
        // Use 6-second window to reliably catch updates (frontend polls every 5s)
        for (const [name, hb] of Object.entries(data.heartbeat)) {
          if (hb.alive && hb.age_seconds < 6) {
            const priority = name === 'polling' ? 1 : (name === 'manual' ? 2 : 999);
            if (priority < (mostRecentPriority || 999)) {
              mostRecentPriority = priority;
              mostRecentAge = hb.age_seconds;
            }
          }
        }
        
        // Apply appropriate pulse animation based on poll type
        if (mostRecentPriority === 1) {
          // API polling (less frequent) - blue pulse (500ms) to match service indicator
          pollingIndicator.classList.remove('pulse-blue', 'pulse-green', 'pulse-yellow');
          void pollingIndicator.offsetWidth; // Force reflow
          pollingIndicator.classList.add('pulse-blue');
          setTimeout(() => pollingIndicator.classList.remove('pulse-blue'), 500);
        } else if (mostRecentPriority === 2) {
          // Manual queue (more frequent) - green pulse (250ms)
          pollingIndicator.classList.remove('pulse-blue', 'pulse-green', 'pulse-yellow');
          void pollingIndicator.offsetWidth; // Force reflow
          pollingIndicator.classList.add('pulse-green');
          setTimeout(() => pollingIndicator.classList.remove('pulse-green'), 250);
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
      // Fetch both executions and active recordings
      const [execRes, recordingsRes] = await Promise.all([
        fetch(`/api/executions?limit=50&ts=${Date.now()}`, { cache: 'no-store' }),
        fetch('/api/recordings')
      ]);
      
      if (!execRes.ok) throw new Error('Failed to fetch executions');
      const execData = await execRes.json();
      
      const execListQueue = document.getElementById('exec-list-queue');
      const execListHistory = document.getElementById('exec-list-history');
      const execCount = document.getElementById('exec-count');
    
      const executions = execData.executions || [];
      
      // Get active (not completed) recordings that pass whitelist
      let activeRecordings = [];
      if (recordingsRes.ok) {
        const recordingsData = await recordingsRes.json();
        const now = Date.now();
        activeRecordings = (recordingsData.recordings || [])
          .filter(rec => {
            // Only show recordings that are:
            // 1. Not completed
            // 2. Pass whitelist
            // 3. Plausibly still recording (created_at + duration + 30min buffer > now)
            const notCompleted = !rec.completed;
            // When whitelist is disabled, all recordings pass; otherwise check the flag
            const passesWhitelist = !recordingsData.whitelist_enabled || rec.passes_whitelist === true;
            
            if (!notCompleted || !passesWhitelist) return false;
            
            // Time-based guard: if the recording should have ended by now
            // (with a generous 30-minute buffer), it's stale, not active.
            const createdAt = rec.created_at || 0;  // ms timestamp
            const duration = (rec.duration || 0) * 1000;  // seconds -> ms
            if (createdAt && duration) {
              const expectedEnd = createdAt + duration + 30 * 60 * 1000;
              if (expectedEnd < now) return false;
            }
            
            return true;
          })
          .slice(0, 20); // Limit to avoid overwhelming UI
      }
      
      // Queue: active recordings + running/pending/discovered executions
      const queueStatuses = new Set(['running', 'pending', 'discovered']);
      const queueExecutions = executions.filter(exec => queueStatuses.has(exec.status));
      
      // History: completed, failed, cancelled executions
      const historyStatuses = new Set(['completed', 'failed', 'cancelled']);
      const historyExecutions = executions.filter(exec => historyStatuses.has(exec.status));
      
      // Sort queue items (recordings first, then by status/time)
      const sortedQueue = [...queueExecutions].sort(compareQueueExecutions);
      const sortedHistory = [...historyExecutions].sort(compareHistoryExecutions);
      
      // Update count to include recordings
      const totalQueueItems = activeRecordings.length + queueExecutions.length;
      execCount.textContent = `(${totalQueueItems} queue, ${historyExecutions.length} history)`;
      
      // Render Queue section
      let queueHtml = '';
      
      // Add active recordings first
      if (activeRecordings.length > 0) {
        queueHtml += activeRecordings.map(rec => renderRecording(rec)).join('');
      }
      
      // Then add execution items
      if (sortedQueue.length > 0) {
        queueHtml += sortedQueue.map(exec => renderExecution(exec)).join('');
      }
      
      execListQueue.innerHTML = queueHtml || '<li class="muted">No active items</li>';
      
      // Render History section
      execListHistory.innerHTML = sortedHistory.length
        ? sortedHistory.map(exec => renderExecution(exec)).join('')
        : '<li class="muted">No completed jobs</li>';
      
      // Update pipeline activity indicator with first running execution
      const runningExec = queueExecutions.find(exec => exec.status === 'running');
      updatePipelineActivityFromExecution(runningExec);
      
  } catch (err) {
      document.getElementById('exec-list-queue').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
      document.getElementById('exec-list-history').innerHTML = `<li class="muted">Error: ${escapeHtml(err.message)}</li>`;
      console.error('Executions fetch error:', err);
  }
}

function renderRecording(recording) {
  const title = recording.episode_title 
    ? `${recording.title} - ${recording.episode_title}` 
    : recording.title;
  
  // Format date
  let timeStr = '';
  if (recording.created_at) {
    const date = new Date(recording.created_at);
    if (!isNaN(date.getTime())) {
      timeStr = date.toLocaleTimeString();
    }
  }
  
  // Recording in progress indicator
  return `
    <li class="exec-item exec-status-recording">
      <span class="exec-time">${timeStr}</span>
      <span class="exec-job-number">—</span>
      <span class="exec-title">${escapeHtml(title)}</span>
      <span class="exec-status-combined">
        <span class="exec-status-icon">⏺</span>
        <span class="exec-status-text">Recording</span>
      </span>
      <span class="exec-elapsed">—</span>
    </li>
  `;
}

function compareQueueExecutions(a, b) {
  const statusRank = {
    running: 0,
    pending: 1,
    discovered: 2,
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

function compareHistoryExecutions(a, b) {
  // Sort history by completion time descending (most recent first)
  const completedA = a.completed_at ? Date.parse(a.completed_at) : 0;
  const completedB = b.completed_at ? Date.parse(b.completed_at) : 0;
  if (completedA !== completedB) {
    return completedB - completedA;
  }
  
  // Fallback to start time
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

  function filterJobLogs(logText, jobNumber) {
    if (!logText) return logText;
    
    // Build regex patterns for START and END markers
    // Format: "START Job #123:" or "START Job abc12345:" (for jobs without number)
    const jobMarker = jobNumber ? `Job #${jobNumber}` : `Job [a-zA-Z0-9]{8}`;
    const startPattern = new RegExp(`={80}\\s*START ${jobMarker}[^\\n]*\\n={80}`, 'i');
    const endPattern = new RegExp(`={80}\\s*END ${jobMarker}[^\\n]*\\n={80}`, 'i');
    
    const startMatch = logText.match(startPattern);
    const endMatch = logText.match(endPattern);
    
    // If we found both markers, extract content between them
    if (startMatch && endMatch) {
      const startIdx = startMatch.index + startMatch[0].length;
      const endIdx = endMatch.index;
      
      if (endIdx > startIdx) {
        // Include the START and END markers themselves for visual clarity
        return logText.substring(startMatch.index, endMatch.index + endMatch[0].length);
      }
    }
    
    // If we only found START marker but not END (job still running or crashed)
    if (startMatch && !endMatch) {
      return logText.substring(startMatch.index);
    }
    
    // No markers found, return full log (backward compatibility for old logs)
    return logText;
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
      let logLinesRaw = (exec.logs_text && exec.logs_text.trim().length > 0)
        ? exec.logs_text
        : (exec.logs && exec.logs.length > 0
            ? exec.logs.map(l => typeof l === 'string' ? l : (l.message || '')).join('\n')
            : 'No logs captured for this execution');
      
      // Filter logs to show only content between START and END job markers
      logLinesRaw = filterJobLogs(logLinesRaw, exec.job_number);
      
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
        
        // Whitelist checkbox: interactive toggle
        // Only show as checked when whitelist is actively enabled AND this title matches a rule.
        // When whitelist is disabled, is_allowed() returns true for everything, which would
        // incorrectly make every checkbox appear checked.
        const whitelistChecked = (data.whitelist_enabled && recording.passes_whitelist) ? 'checked' : '';
        const whitelistCheckbox = `<input type="checkbox" ${whitelistChecked} onchange="toggleWhitelist(this, '${escapeAttr(recording.title)}')" title="Toggle whitelist for ${escapeAttr(recording.title)}">`;
        
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
            <td style="padding: 8px; text-align: center;">${whitelistCheckbox}</td>
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

async function toggleWhitelist(checkbox, title) {
  const add = checkbox.checked;
  try {
    const response = await fetch('/api/whitelist/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, add: add })
    });
    const result = await response.json();
    if (result.error) {
      alert('Failed to update whitelist: ' + result.error);
      checkbox.checked = !add; // revert
    } else {
      const action = add ? 'added to' : 'removed from';
      alert(`"${title}" ${action} whitelist.`);
    }
  } catch (error) {
    console.error('Whitelist toggle failed:', error);
    alert('Failed to update whitelist: ' + error.message);
    checkbox.checked = !add; // revert
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
  // Update tab buttons — match by onclick attribute for dynamic tab support
  document.querySelectorAll('.tab-btn').forEach(btn => {
    const onclick = btn.getAttribute('onclick') || '';
    const match = onclick.match(/switchTab\(['"]([^'"]+)['"]\)/);
    if (match && match[1] === tabName) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
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
  
  // Handle quarantine - load when tab is active
  if (tabName === 'quarantine') {
    loadQuarantineFiles();
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
    // Load both env settings and whitelist from database
    const [envRes, settingsRes] = await Promise.all([
      fetch('/api/env-settings'),
      fetch('/api/settings')
    ]);
    
    if (!envRes.ok) throw new Error('Failed to load env settings');
    const envData = await envRes.json();
    
    let whitelist = '';
    const dbOverrides = {};
    if (settingsRes.ok) {
      const settingsData = await settingsRes.json();
      whitelist = settingsData.whitelist || '';
      if (settingsData.whisper_model) dbOverrides.WHISPER_MODEL = settingsData.whisper_model;
    }
    
    renderSettingsUI(envData, whitelist, dbOverrides);
  } catch (err) {
    console.error('Failed to load settings:', err);
    const container = document.getElementById('settings-container');
    if (container) {
      container.innerHTML = `<p style="color:red;">Failed to load settings: ${err.message}</p>`;
    }
  }
}

function renderSettingsUI(settings, whitelist, dbOverrides = {}) {
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
  // LOCAL_PATH_PREFIX is always kept in sync with DVR_MEDIA_MOUNT automatically on save
  const hiddenFields = ['USE_MOCK', 'USE_POLLING', 'USE_WEBHOOK', 'CAPTION_COMMAND', 'LOCAL_PATH_PREFIX'];  // DISCOVERY_MODE replaces first 3, CAPTION_COMMAND is auto-detected, LOCAL_PATH_PREFIX mirrors DVR_MEDIA_MOUNT
  
  const dropdownFields = {
    'DISCOVERY_MODE': ['polling', 'webhook', 'mock'],
    'WHISPER_MODEL': ['tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'medium.en', 'large-v2', 'large-v3', 'large-v3-turbo', 'distil-large-v3', 'distil-large-v2'],
    'OPTIMIZATION_MODE': ['standard', 'automatic'],
    'WHISPER_DEVICE': ['auto', 'nvidia', 'amd', 'intel', 'none'],
    'LOG_LEVEL': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
  };
  
  // Custom display names for settings (overrides environment variable name)
  const displayNames = {
    'WHISPER_DEVICE': 'GPU',
    'DVR_PATH_PREFIX': 'DVR Media Folder Path',
    'DVR_MEDIA_MOUNT': 'Container Mount Path',
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
      
      const value = dbOverrides[key] !== undefined ? dbOverrides[key] : (config.value || '');
      const desc = config.description || '';
      const defaultVal = config.default || '';
      const isOptional = config.optional || false;
      
      html += `<div class="settings-group" style="margin-bottom: 16px;">`;
      html += `<label for="env-${key}" style="font-weight: 600; display: block; margin-bottom: 4px;">
                ${displayNames[key] || key}${isOptional ? ' <span style="color: var(--muted); font-weight: normal;">(optional)</span>' : ''}
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
  
  // Add whitelist editor section after all env categories
  html += `<div class="settings-category" style="margin-bottom: 24px;">`;
  html += `<h3 style="margin: 0 0 16px 0; font-size: 16px; color: var(--text); border-bottom: 2px solid var(--panel-border); padding-bottom: 8px;">
            Recording Whitelist
           </h3>`;
  html += `<div class="settings-group" style="margin-bottom: 16px;">`;
  html += `<label for="whitelist-editor" style="font-weight: 600; display: block; margin-bottom: 4px;">Whitelist Rules</label>`;
  html += `<p style="font-size: 12px; color: var(--muted); margin: 0 0 8px 0;">One rule per line. Supports wildcards (* and ?) and regex patterns. Empty = process all recordings.</p>`;
  html += `<textarea id="whitelist-editor" rows="10" style="width:100%; font-family: monospace; font-size: 12px;">${whitelist || ''}</textarea>`;
  html += `</div>`;
  html += `</div>`;

  // Store original whitelist value for change detection
  window._originalWhitelist = whitelist || '';
  
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
  
  // LOCAL_PATH_PREFIX is hidden from the UI but must always equal DVR_MEDIA_MOUNT.
  // Mirror it automatically so the saved .env stays consistent.
  for (const [cat, fields] of Object.entries(settings)) {
    if (fields['DVR_MEDIA_MOUNT'] !== undefined) {
      settings[cat]['LOCAL_PATH_PREFIX'] = { value: fields['DVR_MEDIA_MOUNT'].value };
    }
  }
  
  try {
    // Save env settings to .env file
    const envRes = await fetch('/api/env-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    const envData = await envRes.json();
    
    if (!envRes.ok || envData.error) {
      throw new Error(envData.error || 'Failed to save settings');
    }
    
    // Save whisper_model and whitelist to database (take effect without restart)
    const whitelistEditor = document.getElementById('whitelist-editor');
    const whisperModelSelect = form.querySelector('select[name="WHISPER_MODEL"]');
    const dbPayload = {};
    if (whitelistEditor) dbPayload.whitelist = whitelistEditor.value;
    if (whisperModelSelect) dbPayload.whisper_model = whisperModelSelect.value;
    if (Object.keys(dbPayload).length > 0) {
      const dbRes = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dbPayload)
      });
      if (!dbRes.ok) {
        const dbData = await dbRes.json();
        throw new Error(dbData.error || 'Failed to save settings');
      }
    }
    
    const whitelistChanged = whitelistEditor
      && whitelistEditor.value !== (window._originalWhitelist || '');
    let msg;
    if (whitelistChanged) {
      msg = '✓ Settings saved!\n\nWhitelist and Whisper model changes take effect within 30 seconds.\nOther settings require a restart.';
    } else {
      msg = '✓ Settings saved!\n\nWhisper model changes take effect on the next job.\nOther settings require a restart.';
    }
    alert(msg);
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
    // If system monitor was running and data is stale, reset charts
    if (monitorCharts && isMonitorStale()) {
      resetSystemMonitor();
    }
    // ResizeObserver handles chart sizing automatically on restore
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

async function restartSystem() {
  if (!confirm('Restart the system?\n\nThe current job (if any) will finish first, then the application will restart.')) {
    return;
  }
  _triggerRestart();
}

async function _triggerRestart() {
  try {
    // Best-effort call — the server may close the connection before responding
    await Promise.race([
      fetch('/api/shutdown/graceful', { method: 'POST' }),
      new Promise(resolve => setTimeout(resolve, 2000)),
    ]);
  } catch (_) {
    // Expected: server shut down before sending the full HTTP response
  }
  closeSettingsModal();
  // Poll until the server comes back, then reload
  _waitForRestart();
}

function _waitForRestart() {
  const banner = document.createElement('div');
  banner.id = 'restart-banner';
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:12px 20px;background:#856404;color:#fff3cd;'
    + 'font-weight:600;text-align:center;z-index:10000;font-size:14px;';
  banner.textContent = '⟳ Restarting… the page will reload automatically.';
  document.body.appendChild(banner);
  const poll = setInterval(async () => {
    try {
      const r = await fetch('/api/status', { signal: AbortSignal.timeout(2000) });
      if (r.ok) {
        clearInterval(poll);
        window.location.reload();
      }
    } catch (_) { /* still restarting */ }
  }, 2000);
}

// ─── Setup Wizard ──────────────────────────────────────────────────────────
let wizardState = {
  step: 1,
  dvrUrl: '',
  probedPrefix: null,
  samplePath: null,
  deploymentType: null,
};

function openSetupWizard() {
  closeSettingsModal();
  wizardState = { step: 1, dvrUrl: '', probedPrefix: null, samplePath: null, deploymentType: null };
  const dvrInput = document.getElementById('wizard-dvr-url');
  const envUrlInput = document.querySelector('input[name="CHANNELS_API_URL"]') ||
    document.querySelector('input[name="CHANNELS_DVR_URL"]');
  if (dvrInput && envUrlInput && envUrlInput.value) dvrInput.value = envUrlInput.value;
  const probeResult = document.getElementById('wizard-probe-result');
  if (probeResult) probeResult.style.display = 'none';
  document.querySelectorAll('input[name="wizard-deploy"]').forEach(r => r.checked = false);
  const sameLabel = document.getElementById('wizard-deploy-same-label');
  const remoteLabel = document.getElementById('wizard-deploy-remote-label');
  if (sameLabel) sameLabel.style.borderColor = 'var(--panel-border)';
  if (remoteLabel) remoteLabel.style.borderColor = 'var(--panel-border)';
  wizardGoToStep(1);
  const modal = document.getElementById('setup-wizard-modal');
  if (modal) modal.style.display = 'flex';
}

function closeSetupWizard() {
  const modal = document.getElementById('setup-wizard-modal');
  if (modal) modal.style.display = 'none';
}

function wizardGoToStep(step) {
  wizardState.step = step;
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`wizard-step-${i}`);
    if (el) el.style.display = i === step ? 'block' : 'none';
  }
  if (step === 3) {
    const isSame = wizardState.deploymentType === 'same-host';
    const sameEl = document.getElementById('wizard-step-3-same');
    const remoteEl = document.getElementById('wizard-step-3-remote');
    if (sameEl) sameEl.style.display = isSame ? 'block' : 'none';
    if (remoteEl) remoteEl.style.display = !isSame ? 'block' : 'none';
    if (isSame) {
      const localPath = document.getElementById('wizard-local-path');
      if (localPath && !localPath.value && wizardState.probedPrefix) localPath.value = wizardState.probedPrefix;
    } else {
      const shareUrl = document.getElementById('wizard-share-url');
      if (shareUrl && !shareUrl.value) {
        const ipMatch = wizardState.dvrUrl.match(/(?:https?:\/\/)?([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|[^:/]+)/);
        if (ipMatch) {
          const lastSeg = (wizardState.probedPrefix || '').split('/').filter(Boolean).pop() || 'Channels';
          shareUrl.value = `//${ipMatch[1]}/${lastSeg}`;
        }
      }
    }
  }
  if (step === 4) wizardBuildReview();
  for (let i = 1; i <= 4; i++) {
    const dot = document.getElementById(`wdot-${i}`);
    if (dot) {
      const active = i === step;
      const done = i < step;
      dot.style.background = (done || active) ? 'var(--accent)' : 'var(--panel-border)';
      dot.style.color = (done || active) ? 'white' : 'var(--muted)';
      dot.style.outline = active ? '3px solid color-mix(in srgb, var(--accent) 40%, transparent)' : 'none';
    }
    if (i < 4) {
      const line = document.getElementById(`wline-${i}`);
      if (line) line.style.background = i < step ? 'var(--accent)' : 'var(--panel-border)';
    }
  }
  const stepLabels = ['Connect to DVR', 'Deployment Type', 'Mount Configuration', 'Review & Apply'];
  const labelEl = document.getElementById('wizard-step-label');
  if (labelEl) labelEl.textContent = `Step ${step} of 4: ${stepLabels[step - 1]}`;
  const backBtn = document.getElementById('wizard-btn-back');
  const nextBtn = document.getElementById('wizard-btn-next');
  const applyBtn = document.getElementById('wizard-btn-apply');
  if (backBtn) backBtn.style.display = step > 1 ? 'inline-block' : 'none';
  if (applyBtn) applyBtn.style.display = step === 4 ? 'inline-block' : 'none';
  if (nextBtn) nextBtn.textContent = step === 4 ? 'Apply & Restart' : 'Next →';
  if (nextBtn) nextBtn.onclick = step === 4 ? () => wizardApply(true) : wizardNext;
}

async function wizardProbe() {
  const urlInput = document.getElementById('wizard-dvr-url');
  const resultDiv = document.getElementById('wizard-probe-result');
  const btn = document.getElementById('wizard-probe-btn');
  const url = urlInput?.value?.trim();
  if (!url) { alert('Please enter the Channels DVR URL.'); return; }
  btn.textContent = 'Testing...';
  btn.disabled = true;
  resultDiv.style.display = 'none';
  try {
    const res = await fetch(`/api/setup/probe-dvr?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    btn.textContent = 'Test & Detect';
    btn.disabled = false;
    resultDiv.style.display = 'block';
    if (data.connected) {
      wizardState.dvrUrl = url;
      wizardState.probedPrefix = data.inferred_prefix || null;
      wizardState.samplePath = data.sample_path || null;
      let html = `<div style="background:#d4edda;border:1px solid #28a745;padding:12px;border-radius:6px;font-size:13px;color:#1a3c2e;"><strong style="color:#0d2618;">✓ Connected — ${data.recording_count} recording(s) found</strong>`;
      if (data.sample_path) html += `<br><br><strong>Sample path:</strong><br><code style="font-size:11px;">${data.sample_path}</code>`;
      if (data.inferred_prefix) {
        html += `<br><br><strong>DVR media folder (auto-detected):</strong><br><code style="font-size:11px;background:#b8ddc8;color:#0d2618;">${data.inferred_prefix}</code><br><span style="font-size:11px;color:#0d5a2e;">→ Will be used as DVR_PATH_PREFIX</span>`;
      } else if (data.recording_count === 0) {
        html += `<br><br><span style="color:#856404;">⚠ No recordings found — path detection requires at least one recording. You can still continue.</span>`;
      } else {
        html += `<br><br><span style="color:#856404;">⚠ Could not auto-detect media folder. Set DVR_PATH_PREFIX manually after the wizard.</span>`;
      }
      html += `</div>`;
      resultDiv.innerHTML = html;
    } else {
      resultDiv.innerHTML = `<div style="background:#f8d7da;border:1px solid #dc3545;padding:12px;border-radius:6px;font-size:13px;color:#721c24;"><strong>✗ Connection failed</strong><br>${data.error || 'Unknown error'}</div>`;
    }
  } catch (e) {
    btn.textContent = 'Test & Detect';
    btn.disabled = false;
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = `<div style="background:#f8d7da;border:1px solid #dc3545;padding:12px;border-radius:6px;font-size:13px;color:#721c24;"><strong>✗ Error:</strong> ${e.message}</div>`;
  }
}

function wizardDeployChanged(radio) {
  wizardState.deploymentType = radio.value;
  document.getElementById('wizard-deploy-same-label').style.borderColor =
    radio.value === 'same-host' ? 'var(--accent)' : 'var(--panel-border)';
  document.getElementById('wizard-deploy-remote-label').style.borderColor =
    radio.value === 'remote' ? 'var(--accent)' : 'var(--panel-border)';
}

function wizardMountTypeChanged(select) {
  document.getElementById('wizard-cifs-opts').style.display = select.value === 'cifs' ? 'block' : 'none';
  document.getElementById('wizard-nfs-opts').style.display = select.value === 'nfs' ? 'block' : 'none';
}

function wizardCollectSettings() {
  const s = {};
  s.CHANNELS_API_URL = wizardState.dvrUrl;
  if (wizardState.deploymentType === 'same-host') {
    const localPath = document.getElementById('wizard-local-path')?.value?.trim() || '/recordings';
    s.DVR_PATH_PREFIX = '';
    s.LOCAL_PATH_PREFIX = '';
    s.DVR_MEDIA_TYPE = 'none';
    s.DVR_MEDIA_DEVICE = localPath;
    s.DVR_MEDIA_OPTS = 'bind';
    s.DVR_MEDIA_MOUNT = localPath;
    s.DVR_RECORDINGS_PATH = localPath;
  } else {
    const mountType = document.getElementById('wizard-mount-type')?.value || 'cifs';
    const containerPath = document.getElementById('wizard-container-path')?.value?.trim() || '/mnt/channels';
    s.DVR_PATH_PREFIX = wizardState.probedPrefix || '';
    s.LOCAL_PATH_PREFIX = containerPath;
    s.DVR_MEDIA_MOUNT = containerPath;
    s.DVR_MEDIA_TYPE = mountType;
    s.DVR_RECORDINGS_PATH = containerPath;
    if (mountType === 'cifs') {
      const shareUrl = document.getElementById('wizard-share-url')?.value?.trim() || '';
      const user = document.getElementById('wizard-cifs-user')?.value?.trim() || '';
      const pass = document.getElementById('wizard-cifs-pass')?.value?.trim() || '';
      const ipMatch = shareUrl.match(/^\/\/([^/]+)/);
      const addr = ipMatch ? ipMatch[1] : '';
      s.DVR_MEDIA_DEVICE = shareUrl;
      s.DVR_MEDIA_OPTS = `addr=${addr},username=${user},password=${pass},uid=0,gid=0,vers=3.0`;
    } else if (mountType === 'nfs') {
      const nfsShare = document.getElementById('wizard-nfs-share')?.value?.trim() || '';
      s.DVR_MEDIA_DEVICE = nfsShare;
      s.DVR_MEDIA_OPTS = 'nfsvers=4,soft';
    }
  }
  return s;
}

function wizardBuildReview() {
  const s = wizardCollectSettings();
  const el = document.getElementById('wizard-review-content');
  const expEl = document.getElementById('wizard-review-explanations');
  if (!el) return;

  // Plain-English explanation of the key path settings
  const isSame = wizardState.deploymentType === 'same-host';
  if (expEl) {
    let exp = '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
    const row = (name, val, desc) =>
      `<tr><td style="padding:6px 8px;font-family:monospace;font-weight:600;white-space:nowrap;vertical-align:top;color:var(--text);">${name}</td>`+
      `<td style="padding:6px 8px;font-family:monospace;color:var(--accent);vertical-align:top;">${val || '<em style="color:var(--muted);">empty</em>'}</td>`+
      `<td style="padding:6px 8px;font-size:11px;color:var(--muted);vertical-align:top;">${desc}</td></tr>`;
    exp += row('CHANNELS_API_URL', s.CHANNELS_API_URL, 'URL of your Channels DVR server.');
    if (!isSame) {
      exp += row('DVR_PATH_PREFIX', s.DVR_PATH_PREFIX,
        s.DVR_PATH_PREFIX
          ? 'Root path that Channels DVR uses for its recordings (auto-detected from the sample path above). Every file path the DVR API returns will start with this.'
          : 'Could not be auto-detected. The wizard will leave this empty — you can set it manually in Settings after verifying with a real recording path.');
      exp += row('DVR_MEDIA_DEVICE', s.DVR_MEDIA_DEVICE, 'The network share Docker will mount (CIFS UNC path or NFS export).');
      exp += row('DVR_MEDIA_MOUNT', s.DVR_MEDIA_MOUNT, 'Path inside the container where recordings appear. The app looks for files here after translating the DVR API path.');
    } else {
      exp += row('DVR_MEDIA_DEVICE', s.DVR_MEDIA_DEVICE, 'Local path Docker bind-mounts into the container.');
      exp += row('DVR_MEDIA_MOUNT', s.DVR_MEDIA_MOUNT, 'Container path where recordings appear (same as local path for a bind mount).');
    }
    exp += '</table>';
    expEl.innerHTML = exp;
    expEl.style.display = 'block';
  }

  const lines = [
    '# Channels DVR connection',
    `CHANNELS_API_URL=${s.CHANNELS_API_URL}`,
    '',
    '# Path translation (empty = same-host, no translation needed)',
    `DVR_PATH_PREFIX=${s.DVR_PATH_PREFIX}`,
    `LOCAL_PATH_PREFIX=${s.LOCAL_PATH_PREFIX}`,
    '',
    '# Docker volume mount',
    `DVR_MEDIA_TYPE=${s.DVR_MEDIA_TYPE}`,
    `DVR_MEDIA_DEVICE=${s.DVR_MEDIA_DEVICE}`,
    `DVR_MEDIA_OPTS=${s.DVR_MEDIA_OPTS || 'bind'}`,
    `DVR_MEDIA_MOUNT=${s.DVR_MEDIA_MOUNT}`,
    '',
    '# Recordings path (host path for Docker volume)',
    `DVR_RECORDINGS_PATH=${s.DVR_RECORDINGS_PATH}`,
  ];
  el.textContent = lines.join('\n');
}

async function wizardApply(andRestart) {
  const settings = wizardCollectSettings();
  try {
    const res = await fetch('/api/setup/apply-wizard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Failed to save');
    if (andRestart) {
      closeSetupWizard();
      _triggerRestart();
    } else {
      alert('✓ Settings applied!\n\nRun docker compose down && docker compose up -d to apply the new configuration.');
      closeSetupWizard();
      loadSettings();
    }
  } catch (e) {
    alert('✗ Failed to apply settings: ' + e.message);
  }
}

function wizardNext() {
  const step = wizardState.step;
  if (step === 1) {
    if (!wizardState.dvrUrl) { alert('Please test the connection first.'); return; }
    wizardGoToStep(2);
  } else if (step === 2) {
    if (!wizardState.deploymentType) { alert('Please select a deployment type.'); return; }
    wizardGoToStep(3);
  } else if (step === 3) {
    if (wizardState.deploymentType === 'same-host') {
      if (!document.getElementById('wizard-local-path')?.value?.trim()) { alert('Please enter the recordings path.'); return; }
    } else {
      const mountType = document.getElementById('wizard-mount-type')?.value;
      if (mountType === 'cifs' && !document.getElementById('wizard-share-url')?.value?.trim()) { alert('Please enter the share URL.'); return; }
      if (mountType === 'nfs' && !document.getElementById('wizard-nfs-share')?.value?.trim()) { alert('Please enter the NFS share.'); return; }
      if (!document.getElementById('wizard-container-path')?.value?.trim()) { alert('Please enter the container mount path.'); return; }
    }
    wizardGoToStep(4);
  } else if (step === 4) {
    wizardApply(false);
  }
}

function wizardBack() {
  if (wizardState.step > 1) wizardGoToStep(wizardState.step - 1);
}

// ─── End Setup Wizard ───────────────────────────────────────────────────────

// Close modals on background click
window.addEventListener('click', function(event) {
  const settingsModal = document.getElementById('settings-modal');
  if (event.target === settingsModal) {
    closeSettingsModal();
  }
  const wizardModal = document.getElementById('setup-wizard-modal');
  if (event.target === wizardModal) {
    closeSetupWizard();
  }
});

// =========================
// System Monitor
// =========================

let monitorCharts = null;
let monitorInterval = null;
let lastMonitorTimestamp = 0; // Wall-clock ms of last successful data point
let monitorResizeObserver = null; // ResizeObserver for chart containers
const MONITOR_STALE_MS = 10000; // 10 s gap → charts are stale
const MONITOR_WINDOW_SEC = 300; // 5 minutes
const MONITOR_MAX_POINTS = 300; // 5 minutes at 1Hz

// Track which charts are being hovered
const chartHovering = new Set();

// Resize all monitor charts to fit their containers
function resizeMonitorCharts() {
  if (!monitorCharts) return;
  const cpuEl = document.getElementById('chart-cpu');
  const diskEl = document.getElementById('chart-disk');
  const networkEl = document.getElementById('chart-network');
  const gpuEl = document.getElementById('chart-gpu');
  if (!cpuEl) return;

  const cpuWidth = getChartWidth(cpuEl);
  const diskWidth = getChartWidth(diskEl);
  const networkWidth = getChartWidth(networkEl);

  const forceCanvas = (chart, w) => {
    if (chart && chart.root) {
      const c = chart.root.querySelector('canvas');
      if (c) c.style.width = w + 'px';
    }
  };

  forceCanvas(monitorCharts.cpu, cpuWidth);
  forceCanvas(monitorCharts.disk, diskWidth);
  forceCanvas(monitorCharts.network, networkWidth);

  monitorCharts.cpu.setSize({ width: cpuWidth, height: 130 });
  monitorCharts.disk.setSize({ width: diskWidth, height: 130 });
  monitorCharts.network.setSize({ width: networkWidth, height: 130 });

  if (monitorCharts.gpu && gpuEl) {
    const gpuWidth = getChartWidth(gpuEl);
    forceCanvas(monitorCharts.gpu, gpuWidth);
    monitorCharts.gpu.setSize({ width: gpuWidth, height: 130 });
  }
}

// Snap a chart's cursor to the latest data point (shows current values in legend)
function snapToLatest(chart) {
  if (!chart || !chart.data || chart.data[0].length === 0) return;
  const lastIdx = chart.data[0].length - 1;
  const left = chart.valToPos(chart.data[0][lastIdx], 'x');
  chart.setCursor({ left, top: -1 });
}

// Attach hover tracking + snap-to-latest behavior to a chart
function attachChartHoverTracking(chart) {
  if (!chart || !chart.root) return;
  const el = chart.root;
  el.addEventListener('mouseenter', () => chartHovering.add(chart));
  el.addEventListener('mouseleave', () => {
    chartHovering.delete(chart);
    snapToLatest(chart);
  });
  // Show current values immediately
  snapToLatest(chart);
}

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
    
    // Attach hover tracking so legend shows current values when not hovering
    attachChartHoverTracking(monitorCharts.cpu);
    attachChartHoverTracking(monitorCharts.disk);
    attachChartHoverTracking(monitorCharts.network);
    
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
      resizeTimeout = setTimeout(() => resizeMonitorCharts(), 250);
    });

    // Use ResizeObserver for reliable resize after restore / tab-switch
    if (!monitorResizeObserver) {
      let roTimeout;
      monitorResizeObserver = new ResizeObserver(() => {
        clearTimeout(roTimeout);
        roTimeout = setTimeout(() => resizeMonitorCharts(), 80);
      });
    }
    const cpuContainer = cpuEl.closest('.chart-container');
    if (cpuContainer) monitorResizeObserver.observe(cpuContainer);
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
      lastMonitorTimestamp = Date.now();
      
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
                { label: 'VRAM %', stroke: '#ffb347', width: 2, fill: 'rgba(255, 179, 71, 0.1)', points: {show: false} },
                { label: 'Encode %', stroke: '#77dd77', width: 2, points: {show: false} },
                { label: 'Decode %', stroke: '#ff6961', width: 2, points: {show: false} }
              ]
            }, [[], [], [], [], []], gpuEl);
            
            console.log('GPU chart created successfully. Width:', monitorCharts.gpu.width);
            console.log('GPU chart element:', monitorCharts.gpu.root);
            
            // Attach hover tracking for GPU chart
            attachChartHoverTracking(monitorCharts.gpu);
            
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
            vramPct,
            metrics.gpu_enc_percent != null ? metrics.gpu_enc_percent : 0,
            metrics.gpu_dec_percent != null ? metrics.gpu_dec_percent : 0
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
          gpuData = [[], [], [], [], []];
        }
        hasGpuData = true;
        const vramPct = metric.gpu_mem_total_mb > 0
          ? (metric.gpu_mem_used_mb / metric.gpu_mem_total_mb) * 100
          : 0;
        gpuData[0].push(ts);
        gpuData[1].push(metric.gpu_util_percent);
        gpuData[2].push(vramPct);
        gpuData[3].push(metric.gpu_enc_percent != null ? metric.gpu_enc_percent : 0);
        gpuData[4].push(metric.gpu_dec_percent != null ? metric.gpu_dec_percent : 0);
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
              { label: 'VRAM %', stroke: '#ffb347', width: 2, fill: 'rgba(255, 179, 71, 0.1)', points: {show: false} },
              { label: 'Encode %', stroke: '#77dd77', width: 2, points: {show: false} },
              { label: 'Decode %', stroke: '#ff6961', width: 2, points: {show: false} }
            ]
          }, gpuData, gpuEl);
          
          // Calculate max from GPU data
          chartMaxValues.gpu = Math.max(
            ...gpuData[1],
            ...gpuData[2],
            ...gpuData[3],
            ...gpuData[4],
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
  
  // If user isn't hovering, snap legend to latest value
  if (!chartHovering.has(chart)) {
    snapToLatest(chart);
  }
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
    indicator.innerHTML = `Job Activity: <strong style="color: var(--text);">${displayPath}</strong>`;
  } else {
    indicator.textContent = 'Real-time system and pipeline monitoring';
  }
}

function updatePipelineActivityIndicator(pipeline) {
  // Legacy function - kept for backward compatibility
  // Now handled by updatePipelineActivityFromExecution
}

function startSystemMonitor() {
  if (monitorInterval) {
    // Already running — but check for stale data (e.g. tab switch after long idle)
    if (isMonitorStale()) {
      resetSystemMonitor();
    }
    return;
  }
  
  console.log('Starting system monitor...');
  initSystemMonitor();
  if (!monitorCharts) {
    console.error('Failed to initialize monitor charts');
    return;
  }
  // Charts may have been created while container was hidden; fix sizing
  // (ResizeObserver will also fire when container becomes visible)
  requestAnimationFrame(() => resizeMonitorCharts());
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

// Destroy and recreate charts to clear stale / gapped data
function resetSystemMonitor() {
  console.log('Resetting system monitor charts (stale data detected)');
  stopSystemMonitor();
  if (monitorCharts) {
    // Destroy uPlot instances
    ['cpu', 'disk', 'network', 'gpu'].forEach(key => {
      if (monitorCharts[key]) {
        monitorCharts[key].destroy();
      }
    });
    monitorCharts = null;
  }
  chartHovering.clear();
  // Disconnect observer (will be re-created in initSystemMonitor)
  if (monitorResizeObserver) {
    monitorResizeObserver.disconnect();
  }
  // Reset max values
  chartMaxValues.cpu = 10;
  chartMaxValues.disk = 1;
  chartMaxValues.network = 1;
  chartMaxValues.gpu = 10;
  // Clear container DOM so initSystemMonitor can rebuild
  ['chart-cpu', 'chart-disk', 'chart-network', 'chart-gpu'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  });
  startSystemMonitor();
}

// Check if monitor data is stale (browser was hidden / throttled)
function isMonitorStale() {
  if (lastMonitorTimestamp === 0) return false;
  return (Date.now() - lastMonitorTimestamp) > MONITOR_STALE_MS;
}

// Auto-start if System Monitor tab is default
window.addEventListener('DOMContentLoaded', () => {
  const activeTab = document.querySelector('.tab-content.active');
  if (activeTab && activeTab.id === 'glances-tab') {
    startSystemMonitor();
  }
  // Check if Channels Files experimental feature is enabled
  checkChannelsFilesEnabled();
});

// =========================================
// Quarantine Management
// =========================================

async function loadQuarantineFiles() {
  try {
    const response = await fetch('/api/quarantine');
    const data = await response.json();
    
    const tbody = document.getElementById('quarantine-list');
    const statsEl = document.getElementById('quarantine-stats');
    
    if (data.error) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #f55;">Error: ${data.error}</td></tr>`;
      return;
    }
    
    // Update stats
    const stats = data.stats || {};
    const itemCount = data.items ? data.items.length : 0;
    statsEl.innerHTML = `<strong>${itemCount} file${itemCount !== 1 ? 's' : ''}</strong> (${stats.total_size_mb || 0} MB) | ${stats.total_expired || 0} expired`;
    
    // Load and update scan status
    updateQuarantineScanStatus();
    
    // Load scan paths if manager is visible
    if (document.getElementById('scan-paths-manager')?.style.display !== 'none') {
      loadScanPaths();
    }
    
    // Render table
    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #888;">No quarantined files</td></tr>';
      return;
    }
    
    tbody.innerHTML = data.items.map(item => {
      const filename = item.original_path.split('/').pop();
      const sizeKB = item.file_size_bytes ? (item.file_size_bytes / 1024).toFixed(1) : '?';
      const createdDate = new Date(item.created_at).toLocaleString();
      const expiresDate = new Date(item.expires_at).toLocaleString();
      const isExpired = item.is_expired;
      const statusClass = isExpired ? 'status-expired' : 'status-active';
      const statusText = isExpired ? 'Expired' : 'Active';
      
      return `
        <tr>
          <td>
            <input type="checkbox" class="quarantine-checkbox" value="${item.id}">
          </td>
          <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${item.original_path}">
            ${filename}
          </td>
          <td>${item.file_type}</td>
          <td>${sizeKB} KB</td>
          <td>${createdDate}</td>
          <td>${expiresDate}</td>
          <td><span class="${statusClass}">${statusText}</span></td>
        </tr>
      `;
    }).join('');
    
  } catch (error) {
    console.error('Failed to load quarantine files:', error);
    document.getElementById('quarantine-list').innerHTML = 
      `<tr><td colspan="7" style="text-align: center; color: #f55;">Failed to load: ${error.message}</td></tr>`;
  }
}

async function updateQuarantineScanStatus() {
  try {
    const response = await fetch('/api/orphan-cleanup/status');
    const data = await response.json();
    const statusEl = document.getElementById('quarantine-scan-status');
    
    if (!statusEl) return;
    
    if (data.enabled) {
      const lastScan = data.last_cleanup_time ? new Date(data.last_cleanup_time).toLocaleString() : 'never';
      statusEl.textContent = `Auto-scan enabled (every ${data.check_interval_hours}h when idle). Last scan: ${lastScan}`;
    } else {
      statusEl.textContent = 'Click "Scan for Orphans" to detect orphaned .orig and .srt files from your processing history.';
    }
  } catch (error) {
    console.error('Failed to load scan status:', error);
  }
}

async function scanForOrphans() {
  const statusEl = document.getElementById('quarantine-scan-status');
  const originalText = statusEl ? statusEl.textContent : '';
  
  try {
    if (statusEl) {
      statusEl.textContent = '🔍 Scanning for orphaned files...';
      statusEl.style.color = '#4a9eff';
    }
    
    const response = await fetch('/api/orphan-cleanup/run', { method: 'POST' });
    const data = await response.json();
    
    if (data.success) {
      const origCount = data.orig_quarantined || 0;
      const srtCount = data.srt_quarantined || 0;
      const totalCount = origCount + srtCount;
      
      if (totalCount > 0) {
        alert(`✓ Scan complete!\n\nQuarantined ${totalCount} orphaned file(s):\n• ${origCount} .orig file(s)\n• ${srtCount} .srt file(s)\n\nFiles have been moved to quarantine and can be restored if needed.`);
        // Reload quarantine list to show new items
        await loadQuarantineFiles();
      } else {
        alert('✓ Scan complete!\n\nNo orphaned files found. Your recordings directory is clean.');
      }
      
      if (statusEl) {
        statusEl.textContent = `Last scan: just now — Found ${totalCount} orphaned file(s)`;
        statusEl.style.color = '#6c6';
      }
    } else {
      throw new Error(data.error || 'Scan failed');
    }
  } catch (error) {
    console.error('Orphan scan failed:', error);
    alert('Failed to scan for orphans: ' + error.message);
    if (statusEl) {
      statusEl.textContent = originalText;
      statusEl.style.color = '#666';
    }
  }
}

async function deepScanForOrphans() {
  const statusEl = document.getElementById('quarantine-scan-status');
  const originalText = statusEl ? statusEl.textContent : '';
  
  // Progress UI elements
  const progressEl = document.getElementById('deep-scan-progress');
  const statusLabelEl = document.getElementById('deep-scan-status');
  const counterEl = document.getElementById('deep-scan-counter');
  const barEl = document.getElementById('deep-scan-bar');
  const folderEl = document.getElementById('deep-scan-folder');
  const orphansEl = document.getElementById('deep-scan-orphans');
  
  try {
    if (statusEl) {
      statusEl.innerHTML = '<strong>🔍 Deep scanning filesystem paths...</strong>';
      statusEl.style.color = '#4a9eff';
    }
    
    // Show progress panel and cancel button
    const scanCancelBtn = document.getElementById('scan-cancel-btn');
    if (progressEl) {
      progressEl.style.display = 'block';
      statusLabelEl.textContent = 'Enumerating folders...';
      counterEl.textContent = '0 / 0';
      barEl.style.width = '0%';
      barEl.parentElement.style.display = '';
      folderEl.style.display = '';
      folderEl.textContent = '—';
      folderEl.title = '';
      orphansEl.textContent = 'Orphans found: 0';
      if (scanCancelBtn) { scanCancelBtn.style.display = 'inline-block'; scanCancelBtn.textContent = 'Cancel Scan'; }
    }
    
    const response = await fetch('/api/orphan-cleanup/scan-filesystem/stream');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResult = null;
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      
      // Parse SSE events from buffer
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';  // keep incomplete line
      
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        
        try {
          const data = JSON.parse(line.slice(6));
          
          if (data.phase === 'enumerating') {
            if (statusLabelEl) statusLabelEl.textContent = data.message;
            if (counterEl) counterEl.textContent = `0 / ${data.total}`;
          } else if (data.phase === 'scanning') {
            const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
            if (statusLabelEl) statusLabelEl.textContent = `Scanning: ${data.scan_path_label || data.scan_path}`;
            if (counterEl) counterEl.textContent = `${data.current} / ${data.total}`;
            if (barEl) barEl.style.width = `${pct.toFixed(1)}%`;
            if (folderEl) {
              folderEl.textContent = data.folder;
              folderEl.title = data.folder;
            }
            if (orphansEl) orphansEl.textContent = `Orphans found: ${data.orphans_found}`;
          } else if (data.phase === 'complete') {
            if (statusLabelEl) statusLabelEl.textContent = 'Quarantining orphaned files...';
            if (barEl) barEl.style.width = '100%';
          } else if (data.phase === 'quarantining') {
            // Real-time quarantine progress (file moves in progress)
            const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
            if (statusLabelEl) statusLabelEl.textContent = `Quarantining: ${data.current} / ${data.total}`;
            if (barEl) barEl.style.width = `${pct.toFixed(1)}%`;
            if (orphansEl) orphansEl.textContent = `Moved: ${data.quarantined} | Skipped: ${data.skipped} | Failed: ${data.failed}`;
            if (folderEl) {
              // Show abbreviated filename
              const parts = (data.file || '').split('/');
              folderEl.textContent = parts.length > 1 ? parts.slice(-2).join('/') : data.file;
              folderEl.title = data.file || '';
            }
          } else if (data.phase === 'done') {
            finalResult = data;
          } else if (data.phase === 'error') {
            throw new Error(data.message || 'Deep scan failed');
          }
        } catch (parseErr) {
          if (parseErr.message && !parseErr.message.includes('JSON')) {
            throw parseErr;
          }
          console.warn('SSE parse error:', parseErr);
        }
      }
    }
    
    // When done: hide progress bar details, keep summary visible
    if (progressEl) {
      if (barEl) barEl.parentElement.style.display = 'none';
      if (folderEl) folderEl.style.display = 'none';
      if (scanCancelBtn) scanCancelBtn.style.display = 'none';
      const wasCancelled = finalResult && finalResult.cancelled;
      if (statusLabelEl) statusLabelEl.textContent = wasCancelled ? 'Scan cancelled' : 'Scan complete';
      if (statusLabelEl) statusLabelEl.style.color = wasCancelled ? '#f90' : '#6c6';
      // Keep orphansEl and counterEl visible with final counts
      // Hide the whole panel after a delay
      setTimeout(() => {
        if (progressEl) progressEl.style.display = 'none';
      }, 10000);
    }
    
    if (finalResult && finalResult.success) {
      const origCount = finalResult.orig_quarantined || 0;
      const srtCount = finalResult.srt_quarantined || 0;
      const totalCount = origCount + srtCount;
      const totalFound = finalResult.total_found || totalCount;
      const pathsScanned = finalResult.scanned_paths || 0;
      const skippedCount = finalResult.skipped || 0;
      const failedCount = totalFound - totalCount - skippedCount;
      const wasCancelled = finalResult.cancelled || false;
      
      if (wasCancelled) {
        let msg = `⚠ Deep scan cancelled.\n\nScanned ${pathsScanned} path(s)\nFound ${totalFound} orphaned file(s) before cancellation`;
        if (totalCount > 0) {
          msg += `\n\nQuarantined ${totalCount} file(s) before stopping:\n• ${origCount} .orig file(s)\n• ${srtCount} .srt file(s)`;
        }
        alert(msg);
        if (totalCount > 0) await loadQuarantineFiles();
      } else if (totalFound > 0) {
        let msg = `✓ Deep scan complete!\n\nScanned ${pathsScanned} path(s)\nFound ${totalFound} orphaned file(s)\n\nQuarantined ${totalCount} file(s):\n• ${origCount} .orig file(s)\n• ${srtCount} .srt file(s)`;
        if (skippedCount > 0) {
          msg += `\n\n${skippedCount} file(s) already quarantined or no longer on disk`;
        }
        if (failedCount > 0) {
          msg += `\n\n⚠ ${failedCount} file(s) could not be quarantined (check logs for details)`;
        }
        if (totalCount > 0) {
          msg += `\n\nFiles have been moved to quarantine and can be restored if needed.`;
        }
        alert(msg);
        await loadQuarantineFiles();
      } else {
        alert(`✓ Deep scan complete!\n\nScanned ${pathsScanned} path(s)\n\nNo orphaned files found. Your media libraries are clean.`);
      }
      
      if (statusEl) {
        const label = wasCancelled ? 'cancelled' : 'complete';
        statusEl.innerHTML = `<strong>Scan (History):</strong> Detects orphans from recordings you processed. <strong>Deep Scan:</strong> Last scan ${label} — found ${totalFound}, quarantined ${totalCount} file(s)`;
        statusEl.style.color = wasCancelled ? '#f90' : '#6c6';
      }
    } else if (!finalResult) {
      throw new Error('Stream ended without results');
    } else {
      throw new Error(finalResult.error || 'Deep scan failed');
    }
  } catch (error) {
    console.error('Deep scan failed:', error);
    alert('Failed to perform deep scan: ' + error.message);
    if (progressEl) progressEl.style.display = 'none';
    if (statusEl) {
      statusEl.innerHTML = originalText;
      statusEl.style.color = '#666';
    }
  }
}

async function loadScanPaths() {
  try {
    const response = await fetch('/api/scan-paths');
    const data = await response.json();
    
    const listEl = document.getElementById('scan-paths-list');
    if (!listEl) return;
    
    if (data.error || !data.paths || data.paths.length === 0) {
      listEl.innerHTML = '<p style="color: #888; font-size: 0.85em; margin: 0;">No scan paths configured. Add a path above to enable deep scanning.</p>';
      return;
    }
    
    listEl.innerHTML = data.paths.map(path => {
      const label = path.label ? `${path.label}` : '';
      const lastScanned = path.last_scanned_at ? new Date(path.last_scanned_at).toLocaleString() : 'never';
      const statusIcon = path.enabled ? '✓' : '✗';
      const statusColor = path.enabled ? '#6c6' : '#c66';
      
      return `
        <div style="padding: 8px; margin-bottom: 6px; background: #1a1a1a; border-radius: 3px; display: flex; align-items: center; gap: 10px;">
          <span style="color: ${statusColor}; font-size: 1.2em;">${statusIcon}</span>
          <div style="flex: 1; overflow: hidden;">
            <div style="color: #fff; font-size: 0.9em; font-weight: 500; margin-bottom: 2px;">
              ${label ? `${escapeHtml(label)} <span style="color: #666;">—</span> ` : ''}
              <span style="color: #aaa;">${escapeHtml(path.path)}</span>
            </div>
            <div style="color: #666; font-size: 0.75em;">
              Last scanned: ${lastScanned}
            </div>
          </div>
          <button class="btn-small" onclick="toggleScanPath(${path.id}, ${!path.enabled})" style="min-width: 60px;">
            ${path.enabled ? 'Disable' : 'Enable'}
          </button>
          <button class="btn-small" onclick="editScanPath(${path.id}, '${escapeAttr(path.path)}', '${escapeAttr(path.label || '')}')">Edit</button>
          <button class="btn-small btn-danger" onclick="deleteScanPath(${path.id}, '${escapeAttr(path.path)}')">Delete</button>
        </div>
      `;
    }).join('');
    
  } catch (error) {
    console.error('Failed to load scan paths:', error);
    document.getElementById('scan-paths-list').innerHTML = 
      `<p style="color: #f55; font-size: 0.85em;">Error loading scan paths: ${escapeHtml(error.message)}</p>`;
  }
}

function toggleScanPathsManager() {
  const manager = document.getElementById('scan-paths-manager');
  const btn = document.getElementById('toggle-scan-paths-btn');
  
  if (manager.style.display === 'none') {
    manager.style.display = 'block';
    btn.textContent = 'Hide';
    loadScanPaths();
    loadFilesystemAnalysis();
  } else {
    manager.style.display = 'none';
    btn.textContent = 'Configure';
  }
}

function _humanBytes(n) {
  if (n == null) return 'unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}

async function loadFilesystemAnalysis() {
  const el = document.getElementById('fs-analysis-content');
  if (!el) return;
  el.innerHTML = '<p style="margin:0;color:#888;">Analysing...</p>';

  try {
    const resp = await fetch('/api/config/filesystem-analysis');
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'Unknown error');

    let html = '';

    // Per-filesystem cards
    if (data.filesystems && data.filesystems.length > 0) {
      html += `<div style="margin-bottom:6px;color:#aaa;">
        <strong>${data.total_filesystems}</strong> filesystem(s) detected across
        <strong>${data.total_scan_paths}</strong> scan path(s)
      </div>`;
      for (const fs of data.filesystems) {
        const freePct = fs.free_pct != null ? `${fs.free_pct}%` : '?';
        const freeColor = (fs.free_pct != null && fs.free_pct < 10) ? '#f55' : '#6c6';
        html += `<div style="padding:6px;margin-bottom:4px;background:#222;border-radius:3px;border-left:3px solid ${freeColor};">
          <div style="color:#ccc;font-size:0.85em;margin-bottom:2px;">
            <strong>Filesystem</strong> (st_dev=${fs.st_dev})
            &nbsp;—&nbsp; <span style="color:${freeColor};">${freePct} free</span>
            (${_humanBytes(fs.free_bytes)} of ${_humanBytes(fs.total_bytes)})
          </div>
          <div style="color:#888;font-size:0.8em;margin-bottom:2px;">
            Quarantine: <span style="color:#4a9eff;">${escapeHtml(fs.quarantine_dir)}</span>
          </div>
          <div style="color:#666;font-size:0.75em;">
            Scan paths: ${fs.scan_paths.map(p => escapeHtml(p)).join(', ')}
          </div>
        </div>`;
      }
    } else {
      html += '<p style="margin:0;color:#888;">No scan paths configured.</p>';
    }

    // Fallback dir
    html += `<div style="margin-top:6px;color:#666;font-size:0.8em;">
      Fallback quarantine: <span style="color:#888;">${escapeHtml(data.fallback_quarantine_dir)}</span>
      (st_dev=${data.fallback_st_dev || '?'})
    </div>`;

    // Warnings
    if (data.warnings && data.warnings.length > 0) {
      for (const w of data.warnings) {
        html += `<div style="margin-top:6px;padding:6px;background:#3a2a00;border:1px solid #664;border-radius:3px;color:#fa0;font-size:0.8em;">
          ⚠ ${escapeHtml(w)}
        </div>`;
      }
    } else if (data.filesystems && data.filesystems.length > 0) {
      html += `<div style="margin-top:6px;color:#6c6;font-size:0.8em;">
        ✓ All scan paths have same-filesystem quarantine directories. Moves will be instant.
      </div>`;
    }

    el.innerHTML = html;
  } catch (err) {
    el.innerHTML = `<p style="margin:0;color:#f55;">Error: ${escapeHtml(err.message)}</p>`;
  }
}

async function addScanPath() {
  const pathInput = document.getElementById('new-scan-path');
  const labelInput = document.getElementById('new-scan-label');
  
  const path = pathInput.value.trim();
  const label = labelInput.value.trim();
  
  if (!path) {
    alert('Please enter a folder path');
    return;
  }
  
  try {
    const response = await fetch('/api/scan-paths', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, label: label || null })
    });
    
    const data = await response.json();
    
    if (data.success) {
      pathInput.value = '';
      labelInput.value = '';
      await loadScanPaths();
    } else {
      alert('Failed to add scan path: ' + (data.error || 'Unknown error'));
    }
  } catch (error) {
    console.error('Failed to add scan path:', error);
    alert('Failed to add scan path: ' + error.message);
  }
}

async function editScanPath(pathId, currentPath, currentLabel) {
  const newPath = prompt('Edit folder path:', currentPath);
  if (newPath === null) return; // User cancelled
  
  const newLabel = prompt('Edit label (optional):', currentLabel);
  if (newLabel === null) return; // User cancelled
  
  try {
    const response = await fetch(`/api/scan-paths/${pathId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        path: newPath.trim() || currentPath,
        label: newLabel.trim() || null
      })
    });
    
    const data = await response.json();
    
    if (data.success) {
      await loadScanPaths();
    } else {
      alert('Failed to update scan path: ' + (data.error || 'Unknown error'));
    }
  } catch (error) {
    console.error('Failed to update scan path:', error);
    alert('Failed to update scan path: ' + error.message);
  }
}

async function toggleScanPath(pathId, enabled) {
  try {
    const response = await fetch(`/api/scan-paths/${pathId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    
    const data = await response.json();
    
    if (data.success) {
      await loadScanPaths();
    } else {
      alert('Failed to toggle scan path: ' + (data.error || 'Unknown error'));
    }
  } catch (error) {
    console.error('Failed to toggle scan path:', error);
    alert('Failed to toggle scan path: ' + error.message);
  }
}

async function deleteScanPath(pathId, pathStr) {
  if (!confirm(`Delete scan path:\\n${pathStr}\\n\\nThis will not delete any files.`)) {
    return;
  }
  
  try {
    const response = await fetch(`/api/scan-paths/${pathId}`, {
      method: 'DELETE'
    });
    
    const data = await response.json();
    
    if (data.success) {
      await loadScanPaths();
    } else {
      alert('Failed to delete scan path: ' + (data.error || 'Unknown error'));
    }
  } catch (error) {
    console.error('Failed to delete scan path:', error);
    alert('Failed to delete scan path: ' + error.message);
  }
}

function toggleSelectAll(checkbox) {
  const checkboxes = document.querySelectorAll('.quarantine-checkbox');
  checkboxes.forEach(cb => {
    cb.checked = checkbox.checked;
  });
}

async function restoreSelected() {
  const checkboxes = document.querySelectorAll('.quarantine-checkbox:checked');
  const itemIds = Array.from(checkboxes).map(cb => parseInt(cb.value));
  
  if (itemIds.length === 0) {
    alert('No items selected');
    return;
  }
  
  if (!confirm(`Restore ${itemIds.length} file(s) to their original locations?`)) {
    return;
  }
  
  try {
    const response = await fetch('/api/quarantine/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(itemIds)
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(`Restored: ${result.restored}, Failed: ${result.failed}`);
      loadQuarantineFiles(); // Reload list
    } else {
      alert(`Error: ${result.error}`);
    }
  } catch (error) {
    console.error('Failed to restore files:', error);
    alert(`Failed to restore: ${error.message}`);
  }
}

async function deleteSelected() {
  const checkboxes = document.querySelectorAll('.quarantine-checkbox:checked');
  const itemIds = Array.from(checkboxes).map(cb => parseInt(cb.value));
  
  if (itemIds.length === 0) {
    alert('No items selected');
    return;
  }
  
  if (!confirm(`Permanently delete ${itemIds.length} file(s)? This cannot be undone!`)) {
    return;
  }

  // Show delete progress UI
  const progressEl = document.getElementById('delete-progress');
  const statusEl = document.getElementById('delete-status');
  const counterEl = document.getElementById('delete-counter');
  const barEl = document.getElementById('delete-bar');
  const cancelBtn = document.getElementById('delete-cancel-btn');

  if (progressEl) {
    progressEl.style.display = 'block';
    statusEl.textContent = 'Deleting files...';
    counterEl.textContent = `0 / ${itemIds.length}`;
    barEl.style.width = '0%';
    cancelBtn.style.display = 'inline-block';
  }

  // Disable action buttons during delete
  const actionBtns = document.querySelectorAll('.tab-header .btn-small, .tab-header .btn-danger');
  actionBtns.forEach(btn => { btn.disabled = true; });

  try {
    const response = await fetch('/api/quarantine/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(itemIds)
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResult = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));

          if (data.phase === 'deleting') {
            const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
            if (statusEl) statusEl.textContent = data.cancelled ? 'Cancelling...' : 'Deleting files...';
            if (counterEl) counterEl.textContent = `${data.current} / ${data.total} (${data.deleted} deleted)`;
            if (barEl) barEl.style.width = `${pct.toFixed(1)}%`;
          } else if (data.phase === 'done') {
            finalResult = data;
          } else if (data.phase === 'error') {
            throw new Error(data.message || 'Delete failed');
          }
        } catch (parseErr) {
          if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr;
        }
      }
    }

    // Hide progress
    if (progressEl) {
      progressEl.style.display = 'none';
      cancelBtn.style.display = 'none';
    }

    if (finalResult) {
      let msg = `Deleted: ${finalResult.deleted}, Failed: ${finalResult.failed}`;
      if (finalResult.cancelled) {
        msg += `\n\nOperation was cancelled after ${finalResult.deleted} deletion(s).`;
      }
      alert(msg);
      loadQuarantineFiles();
    }
  } catch (error) {
    console.error('Failed to delete files:', error);
    alert(`Failed to delete: ${error.message}`);
    if (progressEl) {
      progressEl.style.display = 'none';
      cancelBtn.style.display = 'none';
    }
  } finally {
    actionBtns.forEach(btn => { btn.disabled = false; });
  }
}

async function cancelDelete() {
  try {
    await fetch('/api/quarantine/delete/cancel', { method: 'POST' });
    const cancelBtn = document.getElementById('delete-cancel-btn');
    if (cancelBtn) cancelBtn.textContent = 'Cancelling...';
  } catch (e) {
    console.error('Failed to cancel delete:', e);
  }
}

async function cancelDeepScan() {
  try {
    await fetch('/api/orphan-cleanup/scan-filesystem/cancel', { method: 'POST' });
    const cancelBtn = document.getElementById('scan-cancel-btn');
    if (cancelBtn) cancelBtn.textContent = 'Cancelling...';
  } catch (e) {
    console.error('Failed to cancel deep scan:', e);
  }
}

async function dedupQuarantine() {
  try {
    const response = await fetch('/api/quarantine/dedup', { method: 'POST' });
    const result = await response.json();
    if (result.success) {
      if (result.duplicates_removed > 0) {
        alert(`Removed ${result.duplicates_removed} duplicate entries from ${result.duplicate_paths} path(s).`);
        loadQuarantineFiles();
      } else {
        alert('No duplicates found.');
      }
    } else {
      alert('Dedup failed: ' + (result.error || 'Unknown error'));
    }
  } catch (error) {
    console.error('Dedup failed:', error);
    alert('Dedup failed: ' + error.message);
  }
}


// =========================================
// Channels Files Audit (Experimental)
// =========================================

async function checkChannelsFilesEnabled() {
  try {
    const res = await fetch('/api/channels-files/enabled');
    const data = await res.json();
    if (data.enabled) {
      const btn = document.getElementById('channels-files-tab-btn');
      if (btn) btn.style.display = '';
    }
  } catch (e) {
    console.log('Channels Files feature check failed:', e);
  }
}

let _auditEventSource = null;

function runChannelsFilesAudit() {
  // Show progress, hide placeholder and previous results
  const progressEl = document.getElementById('audit-progress');
  const resultsEl = document.getElementById('audit-results');
  const placeholderEl = document.getElementById('audit-placeholder');
  const runBtn = document.getElementById('audit-run-btn');
  const cancelBtn = document.getElementById('audit-cancel-btn');

  if (progressEl) progressEl.style.display = '';
  if (resultsEl) resultsEl.style.display = 'none';
  if (placeholderEl) placeholderEl.style.display = 'none';
  if (runBtn) runBtn.disabled = true;
  if (cancelBtn) cancelBtn.style.display = '';

  const statusEl = document.getElementById('audit-progress-status');
  const counterEl = document.getElementById('audit-progress-counter');
  const barEl = document.getElementById('audit-progress-bar');
  const detailEl = document.getElementById('audit-progress-detail');

  if (statusEl) statusEl.textContent = 'Connecting...';
  if (counterEl) counterEl.textContent = '';
  if (barEl) barEl.style.width = '0%';
  if (detailEl) detailEl.textContent = '—';

  _auditEventSource = new EventSource('/api/channels-files/audit/stream');

  _auditEventSource.onmessage = function(event) {
    let data;
    try { data = JSON.parse(event.data); } catch (e) { return; }

    if (data.phase === 'error') {
      if (statusEl) { statusEl.textContent = 'Error'; statusEl.style.color = '#f55'; }
      if (detailEl) detailEl.textContent = data.message || 'Unknown error';
      _closeAuditStream();
      return;
    }

    if (data.phase === 'fetching') {
      if (statusEl) statusEl.textContent = 'Fetching API data...';
      if (detailEl) detailEl.textContent = data.message || '';
      return;
    }

    if (data.phase === 'indexing') {
      if (statusEl) statusEl.textContent = 'Indexing API records';
      if (data.total > 0) {
        const pct = Math.round((data.current / data.total) * 100);
        if (barEl) barEl.style.width = pct + '%';
        if (counterEl) counterEl.textContent = `${data.current} / ${data.total}`;
      }
      if (detailEl) detailEl.textContent = data.message || '';
      return;
    }

    if (data.phase === 'checking_missing') {
      if (statusEl) statusEl.textContent = 'Checking for missing files';
      if (data.total > 0) {
        const pct = Math.round((data.current / data.total) * 100);
        if (barEl) barEl.style.width = pct + '%';
        if (counterEl) counterEl.textContent = `${data.current} / ${data.total}`;
      }
      if (detailEl) detailEl.textContent = data.message || '';
      return;
    }

    if (data.phase === 'checking_orphans') {
      if (statusEl) statusEl.textContent = 'Scanning for orphaned files';
      if (data.total > 0) {
        const pct = Math.round((data.current / data.total) * 100);
        if (barEl) barEl.style.width = pct + '%';
        if (counterEl) counterEl.textContent = `${data.current} / ${data.total}`;
      }
      if (detailEl) detailEl.textContent = data.message || '';
      return;
    }

    if (data.phase === 'done') {
      _closeAuditStream();
      if (data.cancelled) {
        if (statusEl) { statusEl.textContent = 'Cancelled'; statusEl.style.color = '#f90'; }
        if (detailEl) detailEl.textContent = 'Audit was cancelled.';
      } else {
        if (statusEl) { statusEl.textContent = 'Complete'; statusEl.style.color = '#4f4'; }
        if (barEl) barEl.style.width = '100%';
      }
      if (data.summary) {
        renderAuditResults(data);
      }
      return;
    }
  };

  _auditEventSource.onerror = function() {
    _closeAuditStream();
    if (statusEl) { statusEl.textContent = 'Connection lost'; statusEl.style.color = '#f55'; }
  };
}

function _closeAuditStream() {
  if (_auditEventSource) {
    _auditEventSource.close();
    _auditEventSource = null;
  }
  const runBtn = document.getElementById('audit-run-btn');
  const cancelBtn = document.getElementById('audit-cancel-btn');
  if (runBtn) runBtn.disabled = false;
  if (cancelBtn) cancelBtn.style.display = 'none';
}

async function cancelChannelsFilesAudit() {
  try {
    await fetch('/api/channels-files/audit/cancel', { method: 'POST' });
    const cancelBtn = document.getElementById('audit-cancel-btn');
    if (cancelBtn) cancelBtn.textContent = 'Cancelling...';
  } catch (e) {
    console.error('Failed to cancel audit:', e);
  }
}

function renderAuditResults(data) {
  const resultsEl = document.getElementById('audit-results');
  if (!resultsEl) return;
  resultsEl.style.display = '';

  const s = data.summary || {};

  // Summary cards
  const summaryEl = document.getElementById('audit-summary');
  if (summaryEl) {
    summaryEl.innerHTML = `
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: #4a9eff;">${s.api_file_count || 0}</div>
        <div style="font-size: 0.8em; color: #888;">API Files</div>
      </div>
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: #4a9eff;">${s.api_folder_count || 0}</div>
        <div style="font-size: 0.8em; color: #888;">Folders</div>
      </div>
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: #888;">${s.deleted_file_count || 0}</div>
        <div style="font-size: 0.8em; color: #888;">Deleted (Trash)</div>
      </div>
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: ${s.missing_count ? '#f55' : '#4f4'};">${s.missing_count || 0}</div>
        <div style="font-size: 0.8em; color: #888;">Missing</div>
      </div>
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: ${s.orphaned_count ? '#f90' : '#4f4'};">${s.orphaned_count || 0}${s.trashed_count ? ' <span style="font-size:0.55em;color:#888;">(' + s.trashed_count + ' trashed)</span>' : ''}</div>
        <div style="font-size: 0.8em; color: #888;">Orphaned</div>
      </div>
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: #888;">${_formatBytes(s.orphaned_total_bytes || 0)}</div>
        <div style="font-size: 0.8em; color: #888;">Orphan Size</div>
      </div>
      <div style="background: #2a2a2a; padding: 12px; border-radius: 6px; text-align: center;">
        <div style="font-size: 1.6em; font-weight: 700; color: #888;">${s.empty_folder_count || 0}</div>
        <div style="font-size: 0.8em; color: #888;">Empty Folders</div>
      </div>
    `;
  }

  // Missing files table
  const missingSection = document.getElementById('audit-missing-section');
  const missingCount = document.getElementById('audit-missing-count');
  const missingList = document.getElementById('audit-missing-list');
  if (data.missing_files && data.missing_files.length > 0) {
    if (missingSection) missingSection.style.display = '';
    if (missingCount) missingCount.textContent = data.missing_files.length;
    if (missingList) {
      missingList.innerHTML = data.missing_files.map(f => `
        <tr>
          <td style="white-space: nowrap;">${_esc(f.id || '—')}</td>
          <td>${_esc(f.title || '—')}</td>
          <td style="word-break: break-all; font-size: 0.85em; color: #aaa;">${_esc(f.path || f.abs_path || '—')}</td>
          <td style="white-space: nowrap;">${f.created_at ? new Date(f.created_at * 1000).toLocaleDateString() : '—'}</td>
        </tr>
      `).join('');
    }
  } else {
    if (missingSection) missingSection.style.display = 'none';
  }

  // Orphaned files table
  const orphanedSection = document.getElementById('audit-orphaned-section');
  const orphanedCount = document.getElementById('audit-orphaned-count');
  const orphanedList = document.getElementById('audit-orphaned-list');
  // Stash raw data for filtering
  window._auditOrphanedFiles = data.orphaned_files || [];
  if (data.orphaned_files && data.orphaned_files.length > 0) {
    if (orphanedSection) orphanedSection.style.display = '';
    if (orphanedCount) orphanedCount.textContent = data.orphaned_files.length;
    _renderOrphanRows(data.orphaned_files);
  } else {
    if (orphanedSection) orphanedSection.style.display = 'none';
  }

  // Empty folders table
  const emptySection = document.getElementById('audit-empty-section');
  const emptyCount = document.getElementById('audit-empty-count');
  const emptyList = document.getElementById('audit-empty-list');
  if (data.empty_folders && data.empty_folders.length > 0) {
    if (emptySection) emptySection.style.display = '';
    if (emptyCount) emptyCount.textContent = data.empty_folders.length;
    if (emptyList) {
      emptyList.innerHTML = data.empty_folders.map(f => `
        <tr><td style="word-break: break-all; font-size: 0.85em; color: #aaa;">${_esc(f)}</td></tr>
      `).join('');
    }
  } else {
    if (emptySection) emptySection.style.display = 'none';
  }
}

function _formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function _esc(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function _renderOrphanRows(files) {
  const tbody = document.getElementById('audit-orphaned-list');
  if (!tbody) return;
  tbody.innerHTML = files.map(f => {
    const trashIcon = f.trash
      ? '<span title="In DVR trash" style="color: #f90; font-size: 1.1em;">\uD83D\uDDD1</span>'
      : '<span style="color: #555;">&mdash;</span>';
    const rowStyle = f.trash ? 'opacity: 0.6;' : '';
    return `
      <tr data-trash="${f.trash ? '1' : '0'}" style="${rowStyle}">
        <td style="text-align: center;">${trashIcon}</td>
        <td>${_esc(f.filename || '\u2014')}</td>
        <td style="word-break: break-all; font-size: 0.85em; color: #aaa;">${_esc(f.rel_path || f.path || '\u2014')}</td>
        <td style="white-space: nowrap;">${f.size_bytes != null ? _formatBytes(f.size_bytes) : '\u2014'}</td>
      </tr>
    `;
  }).join('');
}

function filterAuditOrphans() {
  const showTrash = document.getElementById('audit-show-trash');
  const files = window._auditOrphanedFiles || [];
  if (!showTrash || showTrash.checked) {
    _renderOrphanRows(files);
  } else {
    _renderOrphanRows(files.filter(f => !f.trash));
  }
  // Update displayed count
  const countEl = document.getElementById('audit-orphaned-count');
  const tbody = document.getElementById('audit-orphaned-list');
  if (countEl && tbody) {
    countEl.textContent = tbody.children.length;
  }
}




