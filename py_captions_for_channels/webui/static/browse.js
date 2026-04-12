/* browse.js — Browse UI for py-captions-for-channels
 * Tabs: Recent | TV Shows | Movies | Library
 * Each item opens /player/{id} in the same tab.
 */

// ── State ───────────────────────────────────────────────────────────────────
const _loaded = {};        // cache: tab key → data
let _searchQuery = '';
let _activeTab = 'recent';
let _selectedShow = null;  // { id, name, episode_count }

// ── Init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Tab buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Episode pane back button
  document.getElementById('ep-back').addEventListener('click', closeEpisodePane);

  // Search
  document.getElementById('search').addEventListener('input', e => {
    _searchQuery = e.target.value.toLowerCase();
    renderCurrentTab();
  });

  // Load first tab
  loadTab('recent');
});

// ── Tab management ───────────────────────────────────────────────────────────
function switchTab(tab) {
  if (tab === _activeTab) return;
  _activeTab = tab;
  _searchQuery = '';
  document.getElementById('search').value = '';

  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tab}`);
  });

  if (!_loaded[tab]) {
    loadTab(tab);
  } else {
    renderCurrentTab();
  }
}

function renderCurrentTab() {
  if (_activeTab === 'recent') renderRecent(_loaded.recent || []);
  else if (_activeTab === 'tv') renderShows(_loaded.tv || []);
  else if (_activeTab === 'movies') renderMovies(_loaded.movies || []);
  else if (_activeTab === 'library') renderLibrary(_loaded.library || []);
}

// ── Data loading ─────────────────────────────────────────────────────────────
async function loadTab(tab) {
  const urls = {
    recent:  '/api/browse/recent',
    tv:      '/api/browse/shows',
    movies:  '/api/browse/movies',
    library: '/api/browse/library',
  };
  try {
    const res = await fetch(urls[tab]);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _loaded[tab] = Array.isArray(data) ? data : (data.recordings || data.items || []);
    renderCurrentTab();
  } catch (err) {
    setGridHtml(gridIdFor(tab), `<div class="state-msg">⚠ ${h(err.message)}</div>`);
  }
}

function gridIdFor(tab) {
  return { recent: 'recent-grid', tv: 'tv-grid', movies: 'movies-grid', library: 'library-grid' }[tab];
}

// ── Recent ───────────────────────────────────────────────────────────────────
function renderRecent(items) {
  const q = _searchQuery;
  const filtered = q
    ? items.filter(r => (r.title + ' ' + (r.episode_title || '')).toLowerCase().includes(q))
    : items;

  if (!filtered.length) {
    setGridHtml('recent-grid', '<div class="state-msg">No recordings found.</div>');
    return;
  }

  const html = filtered.map(r => {
    const label = r.episode_title ? `${r.title} — ${r.episode_title}` : r.title;
    const dateStr = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';
    const thumb = r.thumbnail_url || '';
    const imgHtml = thumb
      ? `<img class="rec-thumb" src="${thumb}" alt="" loading="lazy" onerror="this.replaceWith(placeholder16x9())">`
      : `<div class="rec-thumb-placeholder">📺</div>`;
    return `<a class="rec-card" href="/player/${encodeURIComponent(r.id)}" title="${h(label)}">
      ${imgHtml}
      <div class="rec-info">
        <div class="rec-title">${h(label)}</div>
        <div class="rec-meta">${h(dateStr)}${r.duration ? ' · ' + fmtDur(r.duration) : ''}</div>
      </div>
    </a>`;
  }).join('');

  setGridHtml('recent-grid', html);
}

// ── TV Shows ─────────────────────────────────────────────────────────────────
function renderShows(shows) {
  const q = _searchQuery;
  const filtered = q ? shows.filter(s => s.name.toLowerCase().includes(q)) : shows;

  if (!filtered.length) {
    setGridHtml('tv-grid', '<div class="state-msg">No shows found.</div>');
    return;
  }

  const html = filtered.map(s => {
    const imgHtml = s.image_url
      ? `<img class="poster-img" src="${s.image_url}" alt="" loading="lazy" onerror="this.replaceWith(placeholderPoster())">`
      : `<div class="poster-img-placeholder">📺</div>`;
    const epCount = s.episode_count ? `${s.episode_count} episode${s.episode_count !== 1 ? 's' : ''}` : '';
    return `<div class="poster-card" onclick="openShow(${JSON.stringify(s.id)}, ${JSON.stringify(s.name)}, ${JSON.stringify(epCount)})">
      ${imgHtml}
      <div class="poster-info">
        <div class="poster-title">${h(s.name)}</div>
        ${epCount ? `<div class="poster-meta">${h(epCount)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  setGridHtml('tv-grid', html);

  // If a show was previously selected, re-open its pane
  if (_selectedShow) openShow(_selectedShow.id, _selectedShow.name, _selectedShow.epCount);
}

async function openShow(id, name, epCount) {
  _selectedShow = { id, name, epCount };

  const pane = document.getElementById('episode-pane');
  pane.classList.add('open');
  document.getElementById('ep-show-title').textContent = name;
  document.getElementById('ep-show-meta').textContent = epCount || '';
  document.getElementById('ep-list').innerHTML = '<div class="state-msg"><span class="spinner"></span>Loading episodes…</div>';

  try {
    const res = await fetch(`/api/browse/shows/${encodeURIComponent(id)}/episodes`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const episodes = await res.json();

    // Sort: newest season/episode first
    episodes.sort((a, b) =>
      (b.season_number - a.season_number) || (b.episode_number - a.episode_number)
    );

    if (!episodes.length) {
      document.getElementById('ep-list').innerHTML = '<div class="state-msg">No episodes.</div>';
      return;
    }

    const html = episodes.map(ep => {
      const label = ep.episode_title || ep.title;
      const epNum = (ep.season_number && ep.episode_number)
        ? `S${String(ep.season_number).padStart(2,'0')}E${String(ep.episode_number).padStart(2,'0')}`
        : ep.original_air_date || '';
      const thumbHtml = ep.thumbnail_url
        ? `<img class="ep-thumb" src="${ep.thumbnail_url}" alt="" loading="lazy" onerror="this.replaceWith(thumbPlaceholder())">`
        : `<div class="ep-thumb-placeholder">📺</div>`;
      return `<a class="ep-item" href="/player/${encodeURIComponent(ep.id)}">
        ${thumbHtml}
        <div class="ep-info">
          <div class="ep-label">${h(epNum)}</div>
          <div class="ep-title">${h(label)}</div>
          ${ep.summary ? `<div class="ep-desc">${h(ep.summary)}</div>` : ''}
        </div>
      </a>`;
    }).join('');

    document.getElementById('ep-list').innerHTML = html;
  } catch (err) {
    document.getElementById('ep-list').innerHTML = `<div class="state-msg">⚠ ${h(err.message)}</div>`;
  }
}

function closeEpisodePane() {
  _selectedShow = null;
  document.getElementById('episode-pane').classList.remove('open');
}

// ── Movies ───────────────────────────────────────────────────────────────────
function renderMovies(movies) {
  const q = _searchQuery;
  const filtered = q ? movies.filter(m => m.title.toLowerCase().includes(q)) : movies;

  if (!filtered.length) {
    setGridHtml('movies-grid', '<div class="state-msg">No movies found.</div>');
    return;
  }

  const html = filtered.map(m => {
    const imgHtml = m.image_url
      ? `<img class="poster-img" src="${m.image_url}" alt="" loading="lazy" onerror="this.replaceWith(placeholderPoster())">`
      : `<div class="poster-img-placeholder">🎬</div>`;
    const year = m.release_year || (m.release_date ? m.release_date.slice(0,4) : '');
    return `<a class="poster-card" href="/player/${encodeURIComponent(m.id)}">
      ${imgHtml}
      <div class="poster-info">
        <div class="poster-title">${h(m.title)}</div>
        ${year ? `<div class="poster-meta">${h(year)}${m.duration ? ' · ' + fmtDur(m.duration) : ''}</div>` : ''}
      </div>
    </a>`;
  }).join('');

  setGridHtml('movies-grid', html);
}

// ── Library ───────────────────────────────────────────────────────────────────
function renderLibrary(groups) {
  const q = _searchQuery;
  const filtered = q ? groups.filter(g => g.name.toLowerCase().includes(q)) : groups;

  if (!filtered.length) {
    setGridHtml('library-grid', '<div class="state-msg">No library groups found.</div>');
    return;
  }

  const html = filtered.map(g => {
    const imgHtml = g.image_url
      ? `<img class="poster-img" src="${g.image_url}" alt="" loading="lazy" onerror="this.replaceWith(placeholderPoster())">`
      : `<div class="poster-img-placeholder">🎞</div>`;
    const count = g.video_count ? `${g.video_count} video${g.video_count !== 1 ? 's' : ''}` : '';
    return `<div class="poster-card" onclick="openLibraryGroup(${JSON.stringify(g.id)}, ${JSON.stringify(g.name)})">
      ${imgHtml}
      <div class="poster-info">
        <div class="poster-title">${h(g.name)}</div>
        ${count ? `<div class="poster-meta">${h(count)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  setGridHtml('library-grid', html);
}

async function openLibraryGroup(groupId, groupName) {
  document.getElementById('library-heading').textContent = `← ${groupName}`;
  document.getElementById('library-heading').style.cursor = 'pointer';
  document.getElementById('library-heading').onclick = () => {
    document.getElementById('library-heading').textContent = 'Personal Library';
    document.getElementById('library-heading').style.cursor = '';
    document.getElementById('library-heading').onclick = null;
    renderLibrary(_loaded.library || []);
  };

  setGridHtml('library-grid', '<div class="state-msg"><span class="spinner"></span>Loading…</div>');
  try {
    const res = await fetch(`/api/browse/library/${encodeURIComponent(groupId)}/videos`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const videos = await res.json();

    if (!videos.length) {
      setGridHtml('library-grid', '<div class="state-msg">No videos in this group.</div>');
      return;
    }

    const html = videos.map(v => {
      const imgHtml = v.image_url
        ? `<img class="poster-img" src="${v.image_url}" alt="" loading="lazy" onerror="this.replaceWith(placeholderPoster())">`
        : `<div class="poster-img-placeholder">🎞</div>`;
      return `<a class="poster-card" href="/player/${encodeURIComponent(v.id)}">
        ${imgHtml}
        <div class="poster-info">
          <div class="poster-title">${h(v.title || v.name || '')}</div>
          ${v.duration ? `<div class="poster-meta">${fmtDur(v.duration)}</div>` : ''}
        </div>
      </a>`;
    }).join('');

    setGridHtml('library-grid', html);
  } catch (err) {
    setGridHtml('library-grid', `<div class="state-msg">⚠ ${h(err.message)}</div>`);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setGridHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function h(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtDur(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function placeholder16x9() {
  const d = document.createElement('div');
  d.className = 'rec-thumb-placeholder';
  d.textContent = '📺';
  return d;
}

function placeholderPoster() {
  const d = document.createElement('div');
  d.className = 'poster-img-placeholder';
  d.textContent = '🎬';
  return d;
}

function thumbPlaceholder() {
  const d = document.createElement('div');
  d.className = 'ep-thumb-placeholder';
  d.textContent = '📺';
  return d;
}
