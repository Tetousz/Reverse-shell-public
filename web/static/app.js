// RSC web dashboard — client-side wiring.
// 6e-1: status, sessions, SSE log stream. Command + export land in 6e-2.

'use strict';

// ─── Element refs ────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const el = {
  serverToggle:      $('server-toggle'),
  serverToggleLabel: $('server-toggle-label'),
  statusDot:         $('status-dot'),
  statusText:        $('status-text'),
  tokenValue:        $('token-value'),
  tokenCountdown:    $('token-countdown'),
  tokenCopy:         $('token-copy'),
  sessionList:       $('sessions'),
  sessionCount:      $('session-count'),
  terminal:          $('terminal'),
  commandInput:      $('command-input'),
  commandSend:       $('command-send'),
};

// ─── State ───────────────────────────────────────────────────────
const state = {
  sessions: [],          // {id, address, active, ...}
  selectedSessionId: null,
  serverRunning: false,
};

// ─── Utilities ───────────────────────────────────────────────────
function fmtTime(ts) {
  const d = ts ? new Date(ts * 1000) : new Date();
  return d.toTimeString().slice(0, 8);
}

function logLine(msg, tag) {
  const line = document.createElement('div');
  line.className = 'log-line';
  const ts = document.createElement('span');
  ts.className = 'ts';
  ts.textContent = '[' + fmtTime() + ']';
  const body = document.createElement('span');
  body.className = 'log-' + (tag || 'info');
  body.textContent = msg;
  line.appendChild(ts);
  line.appendChild(body);
  el.terminal.appendChild(line);
  el.terminal.scrollTop = el.terminal.scrollHeight;
}

function escapeText(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

// ─── Server status ───────────────────────────────────────────────
async function refreshStatus() {
  try {
    const r = await fetch('/api/server/status');
    const d = await r.json();
    applyStatus(d);
  } catch (e) {
    console.warn('status fetch failed', e);
  }
}

function applyStatus(d) {
  state.serverRunning = !!d.running;
  if (d.running) {
    el.serverToggleLabel.textContent = 'stop server';
    el.statusDot.classList.add('running');
    el.statusText.textContent = 'running';
    el.tokenValue.textContent = d.token || '—';
    if (d.expires_in !== undefined) {
      el.tokenCountdown.textContent = 'rotates in ' + d.expires_in + 's';
    }
  } else {
    el.serverToggleLabel.textContent = 'start server';
    el.statusDot.classList.remove('running');
    el.statusText.textContent = 'stopped';
    el.tokenValue.textContent = '—';
    el.tokenCountdown.textContent = '';
  }
}

async function toggleServer() {
  el.serverToggle.disabled = true;
  try {
    const r = await fetch('/api/server/toggle', { method: 'POST' });
    const d = await r.json();
    applyStatus(d);
    // Refresh token immediately after start
    if (d.running) setTimeout(refreshStatus, 100);
  } catch (e) {
    logLine('toggle failed: ' + e, 'error');
  } finally {
    el.serverToggle.disabled = false;
  }
}

// ─── Sessions ────────────────────────────────────────────────────
async function refreshSessions() {
  try {
    const r = await fetch('/api/sessions');
    state.sessions = await r.json();
    renderSessions();
  } catch (e) {
    console.warn('sessions fetch failed', e);
  }
}

function renderSessions() {
  el.sessionList.innerHTML = '';
  el.sessionCount.textContent = state.sessions.length;

  if (state.sessions.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'no active sessions';
    el.sessionList.appendChild(empty);
    if (state.selectedSessionId !== null) {
      state.selectedSessionId = null;
      updateCommandBar();
    }
    return;
  }

  for (const s of state.sessions) {
    const item = document.createElement('div');
    item.className = 'session-item';
    if (s.id === state.selectedSessionId) item.classList.add('selected');
    item.dataset.id = s.id;

    const dot = document.createElement('span');
    dot.className = 'dot' + (s.active ? '' : ' inactive');

    const idSpan = document.createElement('span');
    idSpan.className = 'id';
    idSpan.textContent = '#' + String(s.id).padStart(4, '0');

    const addr = document.createElement('span');
    addr.className = 'addr';
    addr.textContent = s.address;

    item.appendChild(dot);
    item.appendChild(idSpan);
    item.appendChild(addr);

    // Revoke button (only when the session has a payload_uuid)
    if (s.payload_uuid) {
      const revokeBtn = document.createElement('button');
      revokeBtn.className = 'session-revoke';
      revokeBtn.title = 'Revoke payload ' + s.payload_uuid.slice(0, 8) + '...';
      revokeBtn.textContent = '×';
      revokeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        revokeSession(s.id);
      });
      item.appendChild(revokeBtn);
    }

    item.addEventListener('click', () => selectSession(s.id));
    el.sessionList.appendChild(item);
  }
}

function selectSession(id) {
  state.selectedSessionId = id;
  renderSessions();
  updateCommandBar();
}

function updateCommandBar() {
  const has = state.selectedSessionId !== null;
  el.commandInput.disabled = !has;
  el.commandSend.disabled = !has;
  el.commandInput.placeholder = has
    ? 'command for session #' + String(state.selectedSessionId).padStart(4, '0')
    : 'select a session first';
}

// ─── Copy button ─────────────────────────────────────────────────
async function copyToken() {
  const token = el.tokenValue.textContent;
  if (!token || token === '—') return;
  try {
    await navigator.clipboard.writeText(token);
    const original = el.tokenCopy.textContent;
    el.tokenCopy.textContent = 'copied';
    setTimeout(() => { el.tokenCopy.textContent = original; }, 1200);
  } catch (e) {
    logLine('copy failed: ' + e, 'error');
  }
}

// ─── SSE stream ──────────────────────────────────────────────────
function connectStream() {
  const es = new EventSource('/api/logs/stream');

  es.onopen = () => {
    // Silent — connected event arrives as first message.
  };

  es.onerror = () => {
    // EventSource auto-reconnects. Log once, quietly.
    logLine('stream disconnected — reconnecting…', 'warning');
  };

  es.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch (e) { return; }
    handleEvent(msg);
  };
}

function handleEvent(msg) {
  const { type, data, ts } = msg;

  switch (type) {
    case 'connected':
      logLine('stream connected', 'highlight');
      break;

    case 'log':
      logLine(data.msg, data.tag);
      break;

    case 'session_add':
      // Refresh from source of truth — simplest and race-free.
      refreshSessions();
      break;

    case 'session_remove':
      if (data.id === state.selectedSessionId) {
        state.selectedSessionId = null;
        updateCommandBar();
      }
      refreshSessions();
      break;

    case 'token_rotated':
      el.tokenValue.textContent = data.token;
      break;

    default:
      // Unknown event — ignore silently.
      break;
  }
}

// ─── Init ────────────────────────────────────────────────────────
function init() {
  logLine('dashboard loaded', 'info');

  el.serverToggle.addEventListener('click', toggleServer);
  el.tokenCopy.addEventListener('click', copyToken);

  refreshStatus();
  refreshSessions();
  connectStream();

  // Periodic status refresh (token countdown).
  setInterval(refreshStatus, 5000);
}

document.addEventListener('DOMContentLoaded', init);

// ─── Command send (6e-2) ─────────────────────────────────────────
async function sendCommand() {
  const cmd = el.commandInput.value.trim();
  if (!cmd || state.selectedSessionId === null) return;

  const sid = state.selectedSessionId;

  // Echo command immediately (optimistic UI)
  const echoLine = document.createElement('div');
  echoLine.className = 'log-line';
  const ts = document.createElement('span');
  ts.className = 'ts';
  ts.textContent = '[' + fmtTime() + ']';
  const body = document.createElement('span');
  body.className = 'log-cmd';
  body.textContent = cmd;
  echoLine.appendChild(ts);
  echoLine.appendChild(body);
  el.terminal.appendChild(echoLine);
  el.terminal.scrollTop = el.terminal.scrollHeight;

  el.commandInput.value = '';
  el.commandInput.disabled = true;
  el.commandSend.disabled = true;

  try {
    const r = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, command: cmd }),
    });
    const d = await r.json();
    if (d.ok) {
      logLine(d.output || '(no output)', 'info');
    } else {
      logLine(d.error || d.output || 'command failed', 'error');
    }
  } catch (e) {
    logLine('send failed: ' + e, 'error');
  } finally {
    updateCommandBar();
    el.commandInput.focus();
  }
}

// ─── Revoke (8e-5) ───────────────────────────────────────────────
async function revokeSession(sessionId) {
  if (!confirm('Revoke payload for session #' + String(sessionId).padStart(4, '0') + '?\nThis disconnects the client and marks the payload unusable.')) {
    return;
  }
  try {
    const r = await fetch('/api/sessions/' + sessionId + '/revoke', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      logLine('revoked payload ' + (d.payload_uuid || '').slice(0, 8) + '... (session #' + String(sessionId).padStart(4, '0') + ')', 'success');
    } else {
      logLine('revoke failed: ' + (d.reason || d.error || 'unknown'), 'error');
    }
  } catch (e) {
    logLine('revoke failed: ' + e, 'error');
  }
}

// ─── Export (6e-2) ───────────────────────────────────────────────
async function exportPayload(fmt) {
  logLine('exporting ' + fmt + '…', 'info');
  try {
    const r = await fetch('/api/export/' + fmt, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      const line = document.createElement('div');
      line.className = 'log-line';
      const ts = document.createElement('span');
      ts.className = 'ts';
      ts.textContent = '[' + fmtTime() + ']';
      const body = document.createElement('span');
      body.className = 'log-success';
      body.textContent = 'exported ' + fmt + ' → ' + d.name + ' (' + d.size + ' bytes) ';
      const link = document.createElement('a');
      link.href = '/api/download/' + encodeURIComponent(d.name);
      link.textContent = '[download]';
      link.style.color = 'var(--accent)';
      link.style.marginLeft = '4px';
      body.appendChild(link);
      line.appendChild(ts);
      line.appendChild(body);
      el.terminal.appendChild(line);
      el.terminal.scrollTop = el.terminal.scrollHeight;
    } else {
      logLine('export failed: ' + (d.error || 'unknown'), 'error');
    }
  } catch (e) {
    logLine('export failed: ' + e, 'error');
  }
}

// ─── Wire up extra listeners (6e-2) ──────────────────────────────
el.commandSend.addEventListener('click', sendCommand);
el.commandInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendCommand();
});

document.querySelectorAll('#export-menu a[data-format], .dropdown-menu a[data-format]').forEach((a) => {
  a.addEventListener('click', (e) => {
    e.preventDefault();
    const fmt = a.dataset.format;
    // Close the <details> dropdown after click.
    const details = a.closest('details');
    if (details) details.removeAttribute('open');
    exportPayload(fmt);
  });
});
