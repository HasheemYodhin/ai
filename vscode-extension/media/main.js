/* Dabba — Claude Code-style agent panel */
(function () {
  const vscode = acquireVsCodeApi();
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('message-input');
  const sendBtn = document.getElementById('sendBtn');
  const stopBtn = document.getElementById('stopBtn');
  const regenRow = document.getElementById('regen-row');
  const regenBtn = document.getElementById('regenBtn');
  const settingsBtn = document.getElementById('settingsBtn');
  const newSessionBtn = document.getElementById('newSessionBtn');
  const deleteHistoryBtn = document.getElementById('deleteHistoryBtn');
  const statusBar = document.getElementById('status-bar');
  const statusText = document.getElementById('status-text');
  const tokenCounter = document.getElementById('token-counter');
  const modelBtn = document.getElementById('modelBtn');
  const modelPicker = document.getElementById('model-picker');
  const effortBtn = document.getElementById('effortBtn');
  const effortPicker = document.getElementById('effort-picker');
  const slashPicker = document.getElementById('slash-picker');
  const atPicker = document.getElementById('at-picker');
  const attachBtn = document.getElementById('attachBtn');
  const attachmentsContainer = document.getElementById('attachments-container');
  const mentionsContainer = document.getElementById('mentions-container');
  const pinnedFilesContainer = document.getElementById('pinned-files-container');
  const sessionTabs = document.getElementById('session-tabs');
  const changedFilesBar = document.getElementById('changed-files-bar');
  const tokenIn = document.getElementById('token-in');
  const tokenOut = document.getElementById('token-out');
  const sessionTokenTotal = document.getElementById('session-token-total');
  const micBtn = document.getElementById('micBtn');
  const diffModeBtn = document.getElementById('diffModeBtn');
  const composerSpinner = document.getElementById('composer-spinner');
  const permissionModeBtn = document.getElementById('permissionModeBtn');
  const contextChip = document.getElementById('context-chip');
  const moreBtn = document.getElementById('moreBtn');
  const headerMenu = document.getElementById('header-menu');
  const activeSessionLabel = document.getElementById('active-session-label');
  const connectionBadge = document.getElementById('connection-badge');
  const statusPhase = document.getElementById('status-phase');
  const statusElapsed = document.getElementById('status-elapsed');
  const optionsBtn = document.getElementById('optionsBtn');

  // Settings overlay elements
  const settingsOverlay = document.getElementById('settings-overlay');
  const settingsCloseBtn = document.getElementById('settingsCloseBtn');
  const settingsSaveBtn = document.getElementById('settings-save');
  const settingsAdvancedBtn = document.getElementById('settings-advanced');
  const settingsKeySaveBtn = document.getElementById('settings-key-save');
  const settingsKeyStatus = document.getElementById('settings-key-status');

  // History dropdown elements
  const historyBtn = document.getElementById('historyBtn');
  const historyDropdown = document.getElementById('history-dropdown');

  // MCP overlay elements
  const mcpBtn = document.getElementById('mcpBtn');
  const mcpOverlay = document.getElementById('mcp-overlay');
  const mcpCloseBtn = document.getElementById('mcpCloseBtn');
  const mcpServerList = document.getElementById('mcp-server-list');
  const mcpHint = document.getElementById('mcp-hint');
  const mcpAddSaveBtn = document.getElementById('mcp-add-save');
  const mcpRefreshBtn = document.getElementById('mcp-refresh');

  let running = false;
  let currentTools = {};
  let currentEffort = 'medium';
  let slashSelectedIdx = 0;
  let matchingCommands = [];
  let atSelectedIdx = 0;
  let matchingFiles = [];
  let allFiles = [];
  let attachedFiles = [];
  let mentionedFiles = []; // {relativePath, content}
  let sessions = [];
  let activeSessionId = '1';
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let changedFiles = [];
  let statusTimer = null;
  let statusStartedAt = 0;
  let startupEnvironment = null;

  const SLASH_COMMANDS = [
    { cmd: '/explain', desc: 'Explain the selected code' },
    { cmd: '/fix', desc: 'Fix bugs in the selected code' },
    { cmd: '/test', desc: 'Generate unit tests for the active file' },
    { cmd: '/review', desc: 'Review the active file for issues' },
    // Web & Search
    { cmd: '/search', desc: '🔍 Search the web and inject results as context' },
    { cmd: '/read', desc: '🌐 Fetch a URL and inject its content as context' },
    { cmd: '/find', desc: '📂 Search workspace files for a keyword' },
    // Memory
    { cmd: '/remember', desc: '🧠 Save a fact to persistent memory' },
    { cmd: '/memories', desc: '🧠 View all saved memories' },
    { cmd: '/forget', desc: '🗑 Delete a saved memory' },
    // Session & Config
    { cmd: '/effort', desc: 'Set reasoning effort: low medium high xhigh max' },
    { cmd: '/keys', desc: 'Show which providers have API keys set' },
    { cmd: '/git', desc: 'Run git status / diff / log / commit' },
    { cmd: '/usage', desc: 'Show session usage and config' },
    { cmd: '/memory', desc: 'Show context & attached files' },
    { cmd: '/new-session', desc: 'Clear conversation & reset agent' },
    { cmd: '/model', desc: 'Set/change the default model' },
    { cmd: '/plan', desc: 'Ask agent to plan before executing' },
    { cmd: '/compact', desc: 'Summarize conversation to save context' },
    { cmd: '/diff', desc: 'Show last file diff' },
    { cmd: '/tools', desc: 'List available agent tools' },
    { cmd: '/help', desc: 'List all slash commands' }
  ];

  // ── Helpers ──────────────────────────────────────────────────────────────

  function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function setConnectionState(state, label) {
    connectionBadge.className = 'connection-badge ' + state;
    connectionBadge.querySelector('.connection-label').textContent = label;
  }

  function startStatusTimer() {
    clearInterval(statusTimer); statusStartedAt = Date.now(); statusElapsed.textContent = '0s';
    statusTimer = setInterval(() => {
      const seconds = Math.floor((Date.now() - statusStartedAt) / 1000);
      statusElapsed.textContent = seconds + 's';
      if (seconds >= 20 && Object.keys(currentTools).length === 0) {
        statusPhase.textContent = 'Waiting for provider';
        statusText.textContent = 'No model token received yet';
        setConnectionState('waiting', 'Provider wait');
      }
    }, 1000);
  }

  function stopStatusTimer() { clearInterval(statusTimer); statusTimer = null; }

  function removeWelcome() {
    document.getElementById('welcome-state')?.remove();
  }

  function renderWelcomeIfEmpty() {
    if (messagesEl.querySelector('.msg,.tool-card,.todo-card,.plan-card,.permission-card')) return;
    if (document.getElementById('welcome-state')) return;
    const welcome = el('div', 'welcome-state');
    welcome.id = 'welcome-state';
    welcome.innerHTML = '<div class="welcome-mark" aria-hidden="true">◇</div>' +
      '<h2>Build with Dabba</h2><p>Ask about your workspace, make a change, or start with a common task.</p>' +
      '<div class="welcome-actions">' +
      '<button data-prompt="Explain the selected code clearly">Explain selection</button>' +
      '<button data-prompt="Review the active file and identify bugs or risks">Review active file</button>' +
      '<button data-prompt="Fix the current problem and verify the result">Fix a problem</button>' +
      '<button data-prompt="Generate useful tests for the active file">Generate tests</button></div>' +
      '<div class="welcome-hint"><span>Tip:</span> use <kbd>@</kbd> for files and <kbd>/</kbd> for commands</div>';
    messagesEl.appendChild(welcome);
    bindWelcomeActions(welcome);
    updateWelcomeEnvironment();
  }

  function updateWelcomeEnvironment() {
    const welcome = document.getElementById('welcome-state');
    if (!welcome || !startupEnvironment) return;
    welcome.querySelector('.welcome-environment')?.remove();
    const env = el('button', 'welcome-environment');
    if (!startupEnvironment.backendReachable) {
      env.classList.add('problem'); env.textContent = 'Backend offline — open settings';
      env.addEventListener('click', () => vscode.postMessage({ type: 'openSettings' }));
    } else if (!startupEnvironment.hasApiKey) {
      env.classList.add('warning'); env.textContent = 'No extension API key — configure access';
      env.addEventListener('click', () => vscode.postMessage({ type: 'openSettings' }));
    } else {
      env.textContent = 'Ready in ' + startupEnvironment.workspaceName;
      env.disabled = true;
    }
    welcome.insertBefore(env, welcome.querySelector('.welcome-hint'));
  }

  function bindWelcomeActions(scope) {
    scope.querySelectorAll('[data-prompt]').forEach(btn => btn.addEventListener('click', () => {
      inputEl.value = btn.dataset.prompt || '';
      autoResize(); inputEl.focus();
    }));
  }

  bindWelcomeActions(document);

  function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/&lt;thinking&gt;([\s\S]*?)&lt;\/thinking&gt;/g, (_m, inner) =>
      '<div class="thinking-card"><div class="thinking-head"><span>Thinking Process</span><span class="thinking-chevron">▸</span></div><div class="thinking-body collapsed">' + inner.trim() + '</div></div>'
    );
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) =>
      '<div class="code-block"><div class="code-head"><span>' + (lang||'code') + '</span><button class="copy-btn">copy</button><button class="insert-btn">insert</button></div><pre>' + code + '</pre></div>'
    );
    html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\n/g, '<br>');
    html = html.replace(/<pre>([\s\S]*?)<\/pre>/g, (_m, inner) => '<pre>' + inner.replace(/<br>/g,'\n') + '</pre>');
    html = html.replace(/<div class="thinking-body collapsed">([\s\S]*?)<\/div>/g, (_m, inner) =>
      '<div class="thinking-body collapsed">' + inner.replace(/<br>/g,'\n') + '</div>'
    );
    return html;
  }

  // ── Session tabs ─────────────────────────────────────────────────────────

  /**
   * Two-step confirm for destructive actions: first click arms the button
   * (shows confirm state for 3s), second click within that window fires.
   * Avoids native confirm()/alert(), which VSCode webviews block.
   */
  function armConfirm(btn, armedText, onConfirm, opts) {
    opts = opts || {};
    if (btn.dataset.armed === '1') {
      clearTimeout(btn._armTimer);
      delete btn.dataset.armed;
      onConfirm();
      return;
    }
    const original = btn.textContent;
    btn.dataset.armed = '1';
    btn.textContent = armedText;
    if (opts.armedClass) btn.classList.add(opts.armedClass);
    btn._armTimer = setTimeout(() => {
      delete btn.dataset.armed;
      btn.textContent = original;
      if (opts.armedClass) btn.classList.remove(opts.armedClass);
    }, 3000);
  }

  function renderSessionTabs() {
    sessionTabs.innerHTML = '';
    sessions.forEach(s => {
      const tab = el('div', 'session-tab' + (s.id === activeSessionId ? ' active' : ''));
      tab.dataset.id = s.id;
      const label = el('span', 'session-tab-label', s.label);
      label.addEventListener('click', () => switchSession(s.id));
      tab.appendChild(label);

      const closeBtn = el('span', 'session-tab-close', '×');
      closeBtn.title = 'Delete this session';
      closeBtn.addEventListener('click', e => {
        e.stopPropagation();
        armConfirm(closeBtn, '✓', () => {
          vscode.postMessage({ type: 'deleteSession', id: s.id });
        }, { armedClass: 'confirm-armed' });
      });
      tab.appendChild(closeBtn);

      sessionTabs.appendChild(tab);
    });
    const active = sessions.find(s => s.id === activeSessionId);
    activeSessionLabel.textContent = active ? active.label : 'Current session';
  }

  function switchSession(id) {
    activeSessionId = id;
    renderSessionTabs();
    vscode.postMessage({ type: 'switchSession', id });
    messagesEl.innerHTML = '';
    todoCard = null; lastUserMessageEl = null; regenRow.classList.add('hidden');
    renderPinnedFilesForActiveSession();
    renderWelcomeIfEmpty();
  }

  // ── Chat history dropdown ───────────────────────────────────────────────

  function sessionPreview(s) {
    const firstUserMsg = (s.messages || []).find(m => m.type === 'addMessage' && m.role === 'user');
    if (!firstUserMsg || !firstUserMsg.content) { return '(empty conversation)'; }
    const text = String(firstUserMsg.content).replace(/\s+/g, ' ').trim();
    return text.length > 64 ? text.slice(0, 64) + '…' : text;
  }

  function relativeTime(ts) {
    if (!ts) { return ''; }
    const diffMs = Date.now() - ts;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) { return 'just now'; }
    if (mins < 60) { return mins + 'm ago'; }
    const hours = Math.floor(mins / 60);
    if (hours < 24) { return hours + 'h ago'; }
    const days = Math.floor(hours / 24);
    if (days < 7) { return days + 'd ago'; }
    return new Date(ts).toLocaleDateString();
  }

  function renderHistoryDropdown() {
    historyDropdown.innerHTML = '';
    const toolbar = el('div', 'history-toolbar');
    const search = el('input', 'history-search');
    search.type = 'search'; search.placeholder = 'Search sessions…'; search.setAttribute('aria-label', 'Search sessions');
    const create = el('button', 'history-new', '+ New');
    create.addEventListener('click', () => { vscode.postMessage({ type: 'newSession' }); closeHistoryDropdown(); });
    toolbar.appendChild(search); toolbar.appendChild(create); historyDropdown.appendChild(toolbar);
    const list = el('div', 'history-list'); historyDropdown.appendChild(list);
    const sorted = sessions.slice().sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
    if (sorted.length === 0) {
      list.appendChild(el('div', 'history-empty', 'No sessions yet'));
      return;
    }
    const renderRows = query => {
      list.innerHTML = '';
      const filtered = sorted.filter(s => (s.label + ' ' + sessionPreview(s)).toLowerCase().includes(query.toLowerCase()));
      if (!filtered.length) { list.appendChild(el('div', 'history-empty', 'No matching sessions')); return; }
      filtered.forEach(s => {
      const row = el('div', 'history-row' + (s.id === activeSessionId ? ' active' : ''));
      row.setAttribute('role', 'option'); row.tabIndex = 0;
      row.addEventListener('click', () => { switchSession(s.id); closeHistoryDropdown(); });
      row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); } });

      const top = el('div', 'history-row-top');
      top.appendChild(el('span', 'history-row-label', s.label));
      top.appendChild(el('span', 'history-row-time', relativeTime(s.createdAt)));
      row.appendChild(top);
      row.appendChild(el('div', 'history-row-preview', sessionPreview(s)));

      const closeBtn = el('span', 'history-row-close', '×');
      closeBtn.title = 'Delete this session';
      closeBtn.addEventListener('click', e => {
        e.stopPropagation();
        armConfirm(closeBtn, '✓', () => {
          vscode.postMessage({ type: 'deleteSession', id: s.id });
        }, { armedClass: 'confirm-armed' });
      });
      row.appendChild(closeBtn);

      list.appendChild(row);
      });
    };
    renderRows('');
    search.addEventListener('input', () => renderRows(search.value));
    requestAnimationFrame(() => search.focus());
  }

  function openHistoryDropdown() { renderHistoryDropdown(); historyDropdown.classList.remove('hidden'); historyBtn.setAttribute('aria-expanded', 'true'); }
  function closeHistoryDropdown() { historyDropdown.classList.add('hidden'); historyBtn.setAttribute('aria-expanded', 'false'); }

  historyBtn.addEventListener('click', () => {
    if (historyDropdown.classList.contains('hidden')) { openHistoryDropdown(); } else { closeHistoryDropdown(); }
  });
  document.addEventListener('click', e => {
    if (!historyDropdown.classList.contains('hidden') && !historyDropdown.contains(e.target) && e.target !== historyBtn) {
      closeHistoryDropdown();
    }
  });

  newSessionBtn.addEventListener('click', () => vscode.postMessage({ type: 'newSession' }));

  deleteHistoryBtn.addEventListener('click', () => {
    armConfirm(deleteHistoryBtn, '✓ confirm', () => {
      vscode.postMessage({ type: 'deleteAllHistory' });
    }, { armedClass: 'confirm-armed' });
  });

  // ── Message rendering ────────────────────────────────────────────────────

  // Marks where the most recent user turn starts in the DOM, so
  // "Regenerate" can wipe that turn (user bubble + everything the agent did
  // after it) before the same request is re-sent.
  let lastUserMessageEl = null;

  function removeLastTurn() {
    if (!lastUserMessageEl || !lastUserMessageEl.parentNode) { lastUserMessageEl = null; return; }
    let node = lastUserMessageEl;
    while (node) {
      const next = node.nextSibling;
      node.remove();
      node = next;
    }
    lastUserMessageEl = null;
    todoCard = null;
  }

  function addUserMessage(text, attachments, mentions) {
    removeWelcome();
    const wrap = el('div', 'msg msg-user');
    const bubble = el('div', 'msg-bubble');
    if (mentions && mentions.length > 0) {
      const md = el('div', 'message-mentions');
      mentions.forEach(m => {
        const chip = el('span', 'mention-chip-display', '@' + m.relativePath.split('/').pop());
        md.appendChild(chip);
      });
      bubble.appendChild(md);
    }
    if (attachments && attachments.length > 0) {
      const ad = el('div', 'message-attachments');
      attachments.forEach(f => {
        const chip = el('div', 'attachment-chip display-only');
        if (f.isImage && f.base64Data) { const img=el('img','attachment-thumb'); img.src=f.base64Data; chip.appendChild(img); }
        else chip.appendChild(el('span','attachment-icon','📄'));
        chip.appendChild(el('span','attachment-name',f.name));
        ad.appendChild(chip);
      });
      bubble.appendChild(ad);
    }
    bubble.appendChild(el('div', 'message-text', text));
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    lastUserMessageEl = wrap;
    scrollToBottom();
  }

  function addAgentText(text) {
    removeWelcome();
    const wrap = el('div', 'msg msg-agent');
    const body = el('div', 'msg-body');
    body.innerHTML = renderMarkdown(text);
    wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    bindCodeButtons(body);
    bindThinkingCards(body);
    scrollToBottom();
  }

  function addThought(seconds) {
    messagesEl.appendChild(el('div','thought-line','Thought for '+seconds+'s'));
    scrollToBottom();
  }

  function addToolCall(callId, name, args, thought, isDangerous, isEdit) {
    removeWelcome();
    if (thought && thought > 1) addThought(thought);
    const card = el('div', 'tool-card' + (isDangerous ? ' tool-dangerous' : ''));
    card.dataset.callId = callId;
    const head = el('div', 'tool-head');
    const dot = el('span', 'tool-dot pending', '●');
    const label = el('span', 'tool-name', prettyToolName(name));
    const meta = el('span', 'tool-meta', summarizeArgs(name, args));
    const chevron = el('span', 'tool-chevron', '▸');
    head.appendChild(dot); head.appendChild(label); head.appendChild(meta); head.appendChild(chevron);
    const body = el('div', 'tool-body collapsed');
    const inSec = el('div', 'tool-io');
    inSec.appendChild(el('div', 'io-label', 'IN'));
    inSec.appendChild(el('pre', 'io-content', JSON.stringify(args, null, 2)));
    body.appendChild(inSec);
    head.addEventListener('click', e => { e.stopPropagation(); body.classList.toggle('collapsed'); chevron.textContent = body.classList.contains('collapsed') ? '▸' : '▾'; });
    card.appendChild(head); card.appendChild(body);
    messagesEl.appendChild(card);
    currentTools[name] = card;
    statusText.textContent = 'running ' + prettyToolName(name) + '…';
    scrollToBottom();
    return card;
  }

  function addToolResult(name, success, output, filePath, isEdit, isArtifact) {
    const card = currentTools[name];
    delete currentTools[name];
    if (!card) return;
    const dot = card.querySelector('.tool-dot');
    dot.classList.remove('pending');
    dot.classList.add(success ? 'ok' : 'fail');
    if (success) {
      const resultSummary = summarizeResult(name, output);
      if (resultSummary) { card.querySelector('.tool-meta').textContent = resultSummary; }
    }
    const body = card.querySelector('.tool-body');
    const outSec = el('div', 'tool-io');
    outSec.appendChild(el('div', 'io-label', 'OUT'));
    const text = (output||'').length > 2000 ? output.slice(0,2000) + '\n… (truncated)' : (output||'(no output)');
    outSec.appendChild(el('pre', 'io-content', text));
    if (isEdit && filePath) {
      const diffBtn = el('button', 'diff-btn', '⇄ View Diff');
      diffBtn.addEventListener('click', e => { e.stopPropagation(); vscode.postMessage({ type: 'viewDiff', filePath, content: output }); });
      outSec.appendChild(diffBtn);
    }
    if (isArtifact && filePath) {
      // markdown_to_pdf/markdown_to_docx produce binary output — no diff
      // makes sense, but there was previously NO way to open the file at
      // all from here. Opens via the OS's own viewer (see _openFile).
      const openBtn = el('button', 'diff-btn', '📂 Open File');
      openBtn.addEventListener('click', e => { e.stopPropagation(); vscode.postMessage({ type: 'openFile', filePath }); });
      outSec.appendChild(openBtn);
    }
    body.appendChild(outSec);
    statusText.textContent = 'thinking…';
    scrollToBottom();
  }

  // ── Todo checklist widget ────────────────────────────────────────────────
  // A single card that updates in place as the agent writes/updates its task list.

  let todoCard = null;

  const TODO_ICON = { pending: '○', in_progress: '◐', completed: '●' };

  function renderTodoCard(todos) {
    removeWelcome();
    if (!todoCard) {
      todoCard = el('div', 'todo-card');
      const head = el('div', 'todo-head');
      head.appendChild(el('span', 'todo-head-icon', '☑'));
      head.appendChild(el('span', 'todo-head-title', 'Tasks'));
      head.appendChild(el('span', 'todo-head-progress'));
      todoCard.appendChild(head);
      todoCard.appendChild(el('div', 'todo-list'));
      messagesEl.appendChild(todoCard);
    }
    const done = todos.filter(t => t.status === 'completed').length;
    todoCard.querySelector('.todo-head-progress').textContent = done + ' / ' + todos.length;

    const list = todoCard.querySelector('.todo-list');
    list.innerHTML = '';
    todos.forEach(t => {
      const row = el('div', 'todo-row todo-' + t.status);
      row.appendChild(el('span', 'todo-icon', TODO_ICON[t.status] || '○'));
      row.appendChild(el('span', 'todo-content', t.content));
      list.appendChild(row);
    });
    scrollToBottom();
  }

  function addPermissionCard(callId, toolName, args, untrustedWorkspace) {
    removeWelcome();
    const card = el('div', 'permission-card');
    const title = el('div', 'permission-title');
    title.innerHTML = '⚠ dabba wants to run <code>' + escapeHtml(toolName) + '</code>';
    card.appendChild(title);
    if (untrustedWorkspace) {
      card.appendChild(el('div', 'permission-untrusted', '🔒 This workspace is not trusted — review carefully before allowing.'));
    }
    const preview = el('pre', 'permission-preview', JSON.stringify(args, null, 2).slice(0, 300));
    card.appendChild(preview);
    const btns = el('div', 'permission-btns');
    const allowBtn = el('button', 'permission-allow', '✓ Allow');
    const denyBtn = el('button', 'permission-deny', '✗ Deny');
    allowBtn.addEventListener('click', () => { card.remove(); vscode.postMessage({ type: 'approveToolCall', callId }); });
    denyBtn.addEventListener('click', () => { card.remove(); vscode.postMessage({ type: 'denyToolCall', callId }); addSystemLine('Tool denied: ' + toolName); });
    btns.appendChild(allowBtn); btns.appendChild(denyBtn);
    card.appendChild(btns);
    messagesEl.appendChild(card);
    scrollToBottom();
  }

  function addPlanCard(steps) {
    const card = el('div', 'plan-card');
    card.appendChild(el('div', 'plan-title', '📋 dabba\'s Plan'));
    const list = el('ol', 'plan-list');
    steps.forEach(s => { const li = el('li','',s); list.appendChild(li); });
    card.appendChild(list);
    const btns = el('div', 'plan-btns');
    const approveBtn = el('button', 'plan-approve', '▶ Execute Plan');
    const cancelBtn = el('button', 'plan-cancel', '✗ Cancel');
    approveBtn.addEventListener('click', () => { card.remove(); vscode.postMessage({ type: 'sendMessage', text: 'Approved. Please execute the plan.', attachments: [], mentions: [] }); });
    cancelBtn.addEventListener('click', () => { card.remove(); addSystemLine('Plan cancelled'); });
    btns.appendChild(approveBtn); btns.appendChild(cancelBtn);
    card.appendChild(btns);
    messagesEl.appendChild(card);
    scrollToBottom();
  }

  function addError(text, retryable) {
    const wrap = el('div', 'msg msg-error');
    wrap.appendChild(el('div','msg-bubble','⚠ '+text));
    if (retryable) {
      const retryBtn = el('button', 'msg-retry-btn', '↻ Retry');
      retryBtn.addEventListener('click', () => {
        retryBtn.disabled = true;
        vscode.postMessage({ type: 'retryLastMessage' });
      });
      wrap.appendChild(retryBtn);
    }
    messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  function addSystemLine(text) {
    messagesEl.appendChild(el('div','system-line',text));
    scrollToBottom();
  }

  // Must match the real tool names registered in dabba/tools/*.py — see the
  // identical warning on DANGEROUS_TOOLS above; this map previously listed
  // made-up names (read_file, run_command, shell, bash...) that matched
  // nothing, so every tool call rendered as its raw snake_case name instead
  // of a friendly label.
  function prettyToolName(name) {
    if (name.startsWith('mcp__')) {
      const parts = name.split('__');
      return parts.length >= 3 ? 'MCP: ' + parts[2] : name;
    }
    const map = {
      file_read:'Read', file_write:'Write', file_edit:'Edit', file_search:'Search', file_list:'List',
      shell_exec:'Bash', powershell_exec:'PowerShell',
      code_analyze:'Analyze', code_format:'Format', code_explain:'Explain',
      process_start:'Start Process', process_list:'List Processes', process_output:'Process Output', process_stop:'Stop Process',
      ssh_exec:'SSH', scp_copy:'SCP',
      docker_exec:'Docker Exec', docker_run:'Docker Run', docker_list_containers:'Docker List',
      markdown_to_pdf:'PDF', markdown_to_docx:'Word',
      todo_write:'Todo', todo_update:'Todo Update',
    };
    return map[name] || name.charAt(0).toUpperCase() + name.slice(1);
  }

  function summarizeArgs(name, args) {
    if (!args) return '';
    const v = args.path || args.file_path || args.command || args.source || args.host || args.container || args.image || args.query || args.pattern || '';
    return typeof v === 'string' ? v.slice(0,60) : '';
  }

  // After a tool succeeds, replace the arg-based summary with a result-based
  // one where that's more informative — mirrors how Claude Code's own
  // transcript shows "Modified" / "Written" instead of just repeating the path.
  function summarizeResult(name, output) {
    let parsed = null;
    try { parsed = JSON.parse(output); } catch { return null; }
    if (!parsed || typeof parsed !== 'object' || parsed.status !== 'success') return null;
    switch (name) {
      case 'file_write':
        return 'Written (' + parsed.size + ' bytes)';
      case 'file_edit':
        return 'Modified (' + parsed.replacements + ' replacement' + (parsed.replacements === 1 ? '' : 's') + ')';
      case 'markdown_to_pdf':
      case 'markdown_to_docx':
        return 'Created (' + parsed.size + ' bytes)';
      default:
        return null;
    }
  }

  function fmtTokens(n) {
    return n > 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
  }

  function updateTokenCounter() {
    const total = totalInputTokens + totalOutputTokens;
    if (total === 0) {
      tokenCounter.classList.add('hidden');
      sessionTokenTotal.textContent = '';
      return;
    }
    tokenCounter.classList.remove('hidden');
    tokenIn.textContent = '↑' + fmtTokens(totalInputTokens);
    tokenOut.textContent = '↓' + fmtTokens(totalOutputTokens);
    sessionTokenTotal.textContent = '~' + fmtTokens(total) + ' tok';
  }

  // ── Changed files bar ────────────────────────────────────────────────────

  function renderChangedFiles() {
    if (changedFiles.length === 0) { changedFilesBar.classList.add('hidden'); changedFilesBar.innerHTML = ''; return; }
    changedFilesBar.classList.remove('hidden');
    changedFilesBar.innerHTML = '';
    changedFilesBar.appendChild(el('span', 'changed-files-label', changedFiles.length + ' file' + (changedFiles.length === 1 ? '' : 's') + ' changed'));
    const reviewAll = el('button', 'changed-files-review', 'Review all');
    reviewAll.addEventListener('click', () => vscode.postMessage({ type: 'viewChangedFiles' }));
    changedFilesBar.appendChild(reviewAll);
    changedFiles.forEach(f => {
      const chip = el('span', 'changed-file-chip', f.split('/').pop());
      chip.title = f;
      chip.addEventListener('click', () => vscode.postMessage({ type: 'openFile', filePath: f }));
      changedFilesBar.appendChild(chip);
    });
  }

  function bindCodeButtons(scope) {
    scope.querySelectorAll('.copy-btn').forEach(btn => btn.addEventListener('click', e => {
      e.stopPropagation();
      const code = btn.closest('.code-block').querySelector('pre').textContent;
      navigator.clipboard.writeText(code);
      btn.textContent = 'copied!';
      setTimeout(() => btn.textContent = 'copy', 1500);
    }));
    scope.querySelectorAll('.insert-btn').forEach(btn => btn.addEventListener('click', e => {
      e.stopPropagation();
      vscode.postMessage({ type: 'insertCode', code: btn.closest('.code-block').querySelector('pre').textContent });
    }));
  }

  function bindThinkingCards(scope) {
    scope.querySelectorAll('.thinking-card').forEach(card => {
      const head = card.querySelector('.thinking-head');
      const body = card.querySelector('.thinking-body');
      const chevron = card.querySelector('.thinking-chevron');
      head.addEventListener('click', e => { e.stopPropagation(); body.classList.toggle('collapsed'); chevron.textContent = body.classList.contains('collapsed') ? '▸' : '▾'; });
    });
  }

  // ── Model/Effort pickers ─────────────────────────────────────────────────

  modelBtn.addEventListener('click', e => {
    e.stopPropagation(); effortPicker.classList.add('hidden');
    if (modelPicker.classList.contains('hidden')) {
      vscode.postMessage({ type: 'loadModels' });
      modelPicker.classList.remove('hidden');
      modelPicker.innerHTML = '<div class="picker-loading">loading models…</div>';
    } else modelPicker.classList.add('hidden');
  });

  function renderModels(models, current) {
    modelPicker.innerHTML = '';
    let lastProvider = '';
    models.forEach(m => {
      if (m.provider !== lastProvider) { lastProvider = m.provider; modelPicker.appendChild(el('div','picker-group', m.provider.toUpperCase())); }
      const row = el('div', 'picker-row' + (m.id===current?' active':''));
      row.appendChild(el('span','picker-dot', m.id===current?'●':'○'));
      row.appendChild(el('span','picker-name', m.name));
      row.appendChild(el('span','picker-tier tier-'+m.tier, m.tier));
      if (!m.has_key) row.appendChild(el('span','picker-nokey','no key'));
      row.addEventListener('click', () => { vscode.postMessage({type:'setModel',model:m.id}); modelPicker.classList.add('hidden'); });
      modelPicker.appendChild(row);
    });
  }

  effortBtn.addEventListener('click', e => {
    e.stopPropagation(); modelPicker.classList.add('hidden');
    if (effortPicker.classList.contains('hidden')) { effortPicker.classList.remove('hidden'); renderEfforts(); }
    else effortPicker.classList.add('hidden');
  });

  function renderEfforts() {
    const efforts = ['low','medium','high','xhigh','max'];
    effortPicker.innerHTML = '';
    efforts.forEach(e => {
      const row = el('div','picker-row'+(e===currentEffort?' active':''));
      row.appendChild(el('span','picker-dot', e===currentEffort?'●':'○'));
      row.appendChild(el('span','picker-name', e.toUpperCase()));
      row.addEventListener('click', () => { vscode.postMessage({type:'setEffort',effort:e}); effortPicker.classList.add('hidden'); });
      effortPicker.appendChild(row);
    });
  }

  document.addEventListener('click', () => { modelPicker.classList.add('hidden'); effortPicker.classList.add('hidden'); atPicker.classList.add('hidden'); });

  // ── @ Mention file picker ────────────────────────────────────────────────

  function showAtPicker(query) {
    const q = query.toLowerCase();
    matchingFiles = allFiles.filter(f => f.toLowerCase().includes(q)).slice(0, 15);
    if (matchingFiles.length === 0) { atPicker.classList.add('hidden'); return; }
    atPicker.innerHTML = '';
    matchingFiles.forEach((f, idx) => {
      const row = el('div', 'picker-row' + (idx===atSelectedIdx?' active':''));
      row.appendChild(el('span','picker-dot','@'));
      row.appendChild(el('span','picker-name', f.split('/').pop()));
      row.appendChild(el('span','picker-desc',' '+f));
      row.addEventListener('click', () => selectMentionFile(f));
      atPicker.appendChild(row);
    });
    atPicker.classList.remove('hidden');
  }

  function selectMentionFile(relativePath) {
    atPicker.classList.add('hidden');
    const val = inputEl.value;
    const atIdx = val.lastIndexOf('@');
    if (atIdx !== -1) inputEl.value = val.slice(0, atIdx);
    autoResize();
    vscode.postMessage({ type: 'getMentionFileContent', relativePath });
  }

  // Pinned files for the CURRENT session — kept in sync via sessionsInit/
  // switchSession/sessionCreated (which carry each session's pinnedFiles)
  // and pinnedFilesChanged (live updates after a pin/unpin this session).
  let pinnedFiles = [];

  function renderPinnedFiles() {
    pinnedFilesContainer.innerHTML = '';
    if (pinnedFiles.length === 0) { pinnedFilesContainer.classList.add('hidden'); updateContextChip(); return; }
    pinnedFilesContainer.classList.remove('hidden');
    pinnedFiles.forEach((relativePath) => {
      const chip = el('div', 'mention-chip pinned-chip');
      chip.title = relativePath + ' — included in every message this session';
      chip.appendChild(el('span','mention-at','📌'));
      chip.appendChild(el('span','mention-name', relativePath.split('/').pop()));
      const rm = el('button','mention-remove','×');
      rm.addEventListener('click', e => { e.stopPropagation(); vscode.postMessage({type:'unpinFile', relativePath}); });
      chip.appendChild(rm);
      pinnedFilesContainer.appendChild(chip);
    });
    updateContextChip();
  }

  function renderPinnedFilesForActiveSession() {
    const s = sessions.find(s => s.id === activeSessionId);
    pinnedFiles = (s && s.pinnedFiles) || [];
    renderPinnedFiles();
  }

  function renderMentions() {
    mentionsContainer.innerHTML = '';
    if (mentionedFiles.length === 0) { mentionsContainer.classList.add('hidden'); updateContextChip(); return; }
    mentionsContainer.classList.remove('hidden');
    mentionedFiles.forEach((m, i) => {
      const chip = el('div', 'mention-chip');
      chip.appendChild(el('span','mention-at','@'));
      chip.appendChild(el('span','mention-name', m.relativePath.split('/').pop()));
      const pin = el('button','mention-pin','📌');
      pin.title = 'Pin — include in every message this session';
      pin.addEventListener('click', e => {
        e.stopPropagation();
        vscode.postMessage({type:'pinFile', relativePath: m.relativePath});
        mentionedFiles.splice(i,1); renderMentions();
      });
      chip.appendChild(pin);
      const rm = el('button','mention-remove','×');
      rm.addEventListener('click', e => { e.stopPropagation(); mentionedFiles.splice(i,1); renderMentions(); });
      chip.appendChild(rm);
      mentionsContainer.appendChild(chip);
    });
    updateContextChip();
  }

  // ── Slash picker ─────────────────────────────────────────────────────────

  function updateSlashSuggestions() {
    const val = inputEl.value;
    if (!val.startsWith('/')) { slashPicker.classList.add('hidden'); return; }
    const q = val.toLowerCase();
    matchingCommands = SLASH_COMMANDS.filter(c => c.cmd.startsWith(q));
    if (matchingCommands.length === 0) { slashPicker.classList.add('hidden'); return; }
    slashPicker.innerHTML = '';
    matchingCommands.forEach((c, idx) => {
      const row = el('div', 'picker-row' + (idx===slashSelectedIdx?' active':''));
      const cmdSpan = el('span','picker-name', c.cmd); cmdSpan.style.color='#00e676'; cmdSpan.style.fontWeight='bold';
      row.appendChild(cmdSpan);
      row.appendChild(el('span','picker-desc',' - '+c.desc));
      row.addEventListener('click', () => { inputEl.value = c.cmd+' '; inputEl.focus(); slashPicker.classList.add('hidden'); });
      slashPicker.appendChild(row);
    });
    slashPicker.classList.remove('hidden');
  }

  // ── Attachments ──────────────────────────────────────────────────────────

  function renderAttachments() {
    attachmentsContainer.innerHTML = '';
    if (attachedFiles.length === 0) { attachmentsContainer.classList.add('hidden'); updateContextChip(); return; }
    attachmentsContainer.classList.remove('hidden');
    attachedFiles.forEach((f, i) => {
      const chip = el('div', 'attachment-chip');
      if (f.isImage && f.base64Data) { const img=el('img','attachment-thumb'); img.src=f.base64Data; chip.appendChild(img); }
      else chip.appendChild(el('span','attachment-icon','📄'));
      chip.appendChild(el('span','attachment-name', f.name));
      const rm = el('button','attachment-remove','×');
      rm.addEventListener('click', e => { e.stopPropagation(); attachedFiles.splice(i,1); renderAttachments(); });
      chip.appendChild(rm);
      attachmentsContainer.appendChild(chip);
    });
    updateContextChip();
  }

  // Populated by the extension's 'contextPreview' response — what the active
  // editor/pinned files would contribute if the user hit send right now.
  let editorContextPreview = { activeFile: null, selectionChars: 0, pinnedChars: 0 };

  function estimateTokens(charCount) {
    // Rough, provider-agnostic heuristic (~4 chars/token) — good enough for
    // "am I about to send way more than I think", not meant to be exact.
    return Math.max(0, Math.round(charCount / 4));
  }

  /**
   * Composer toolbar chip previewing exactly what will be sent alongside the
   * typed message: active file, selection size, pinned/@-mentioned/attached
   * files, and a rough token estimate — so the user isn't guessing what the
   * model actually sees. Hover for the full breakdown (native title tooltip).
   */
  function updateContextChip() {
    const fileCount = attachedFiles.length + mentionedFiles.length + pinnedFiles.length;
    const hasActive = !!editorContextPreview.activeFile;
    const hasSelection = editorContextPreview.selectionChars > 0;
    if (fileCount === 0 && !hasActive && !hasSelection && inputEl.value.length === 0) {
      contextChip.classList.add('hidden');
      return;
    }

    const mentionChars = mentionedFiles.reduce((sum, m) => sum + (m.content || '').length, 0);
    const approxTokens = estimateTokens(
      inputEl.value.length + mentionChars + editorContextPreview.selectionChars + editorContextPreview.pinnedChars
    );

    const parts = [];
    if (hasActive) { parts.push('📄 ' + editorContextPreview.activeFile.split('/').pop()); }
    if (hasSelection) { parts.push(editorContextPreview.selectionChars + ' sel'); }
    if (pinnedFiles.length) { parts.push('📌 ' + pinnedFiles.length); }
    if (attachedFiles.length + mentionedFiles.length > 0) {
      parts.push((attachedFiles.length + mentionedFiles.length) + ' file' + (attachedFiles.length + mentionedFiles.length === 1 ? '' : 's'));
    }
    parts.push('~' + approxTokens + ' tok');

    contextChip.classList.remove('hidden');
    contextChip.textContent = parts.join(' · ');

    const tooltip = ['Context that will be sent:'];
    if (hasActive) { tooltip.push('Active file: ' + editorContextPreview.activeFile); }
    if (hasSelection) { tooltip.push('Selection: ' + editorContextPreview.selectionChars + ' characters'); }
    if (pinnedFiles.length) { tooltip.push('Pinned (every message): ' + pinnedFiles.join(', ')); }
    if (mentionedFiles.length) { tooltip.push('Mentioned (this message): ' + mentionedFiles.map(m => m.relativePath).join(', ')); }
    if (attachedFiles.length) { tooltip.push('Attached: ' + attachedFiles.map(f => f.name).join(', ')); }
    tooltip.push('Estimated tokens: ~' + approxTokens);
    contextChip.title = tooltip.join('\n');
  }

  // ── + Attach dropdown (Workflows / Media / Mentions) ─────────────────────
  const attachDropdown = document.getElementById('attach-dropdown');

  function openAttachMenu(e) {
    e.stopPropagation();
    const isOpen = !attachDropdown.classList.contains('hidden');
    // Close other pickers first
    modelPicker.classList.add('hidden');
    effortPicker.classList.add('hidden');
    slashPicker.classList.add('hidden');
    if (isOpen) {
      attachDropdown.classList.add('hidden');
      attachBtn.classList.remove('active');
    } else {
      attachDropdown.classList.remove('hidden');
      attachBtn.classList.add('active');
    }
  }

  function closeAttachMenu() {
    attachDropdown.classList.add('hidden');
    attachBtn.classList.remove('active');
  }

  attachBtn.addEventListener('click', openAttachMenu);

  // Workflows — type a slash command trigger for now; can be extended later
  document.getElementById('attachWorkflowBtn').addEventListener('click', e => {
    e.stopPropagation();
    closeAttachMenu();
    inputEl.value = '/plan ';
    inputEl.focus();
    updateSlashSuggestions();
    addSystemLine('⚡ Type your workflow goal after /plan and press Enter.');
  });

  // Media — open the file-picker dialog (existing behaviour)
  document.getElementById('attachMediaBtn').addEventListener('click', e => {
    e.stopPropagation();
    closeAttachMenu();
    vscode.postMessage({ type: 'attachFile' });
  });

  // Mentions — insert @ into the input to trigger the file mention picker
  document.getElementById('attachMentionBtn').addEventListener('click', e => {
    e.stopPropagation();
    closeAttachMenu();
    const cur = inputEl.value;
    inputEl.value = cur + '@';
    inputEl.focus();
    // Trigger the @ picker by dispatching an input event
    inputEl.dispatchEvent(new Event('input'));
    autoResize();
  });

  // Close attach menu when clicking outside
  document.addEventListener('click', e => {
    if (!attachDropdown.classList.contains('hidden') &&
        !attachDropdown.contains(e.target) &&
        e.target !== attachBtn) {
      closeAttachMenu();
    }
  });

  // ── Diff / changed-files toggle ──────────────────────────────────────────
  diffModeBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (changedFiles.length === 0) {
      addSystemLine('No files changed yet this session');
      return;
    }
    diffModeBtn.classList.toggle('active');
    changedFilesBar.classList.toggle('hidden');
  });

  // ── Permission mode toggle ────────────────────────────────────────────────
  permissionModeBtn.addEventListener('click', e => {
    e.stopPropagation();
    vscode.postMessage({ type: 'togglePermissionMode' });
  });

  function applyPermissionMode(mode) {
    if (mode === 'auto') {
      permissionModeBtn.textContent = '✓ Auto-accept edits';
      permissionModeBtn.classList.add('auto-accept');
    } else {
      permissionModeBtn.textContent = '✋ Ask before edits';
      permissionModeBtn.classList.remove('auto-accept');
    }
  }

  // ── Voice input ──────────────────────────────────────────────────────────
  // Recording happens on the extension host (arecord), not here — VS Code
  // webviews can't reliably get microphone permission via getUserMedia, and
  // the browser's own SpeechRecognition needs network access to a speech
  // backend that isn't reachable from inside the webview sandbox either.
  // This just toggles start/stop and waits for the transcribed text back.
  let recording = false;

  micBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (recording) {
      recording = false;
      micBtn.classList.remove('recording');
      micBtn.classList.add('transcribing');
      vscode.postMessage({ type: 'stopVoiceInput' });
    } else {
      recording = true;
      micBtn.classList.add('recording');
      vscode.postMessage({ type: 'startVoiceInput' });
    }
  });

  // ── Send ─────────────────────────────────────────────────────────────────

  function send() {
    const text = inputEl.value.trim();
    if (!text || running) return;
    if (text === '/clear' || text === '/new-session') {
      inputEl.value = ''; autoResize(); slashPicker.classList.add('hidden');
      vscode.postMessage({type:'clearConversation'}); return;
    }
    inputEl.value = ''; autoResize(); slashPicker.classList.add('hidden');
    vscode.postMessage({ type:'sendMessage', text, attachments:attachedFiles, mentions:mentionedFiles });
    attachedFiles = []; mentionedFiles = []; renderAttachments(); renderMentions();
  }

  function autoResize() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  }

  sendBtn.addEventListener('click', send);
  stopBtn.addEventListener('click', () => vscode.postMessage({type:'stopAgent'}));
  regenBtn.addEventListener('click', () => {
    regenBtn.disabled = true;
    regenRow.classList.add('hidden');
    vscode.postMessage({type:'regenerateLastResponse'});
  });
  settingsBtn.addEventListener('click', () => vscode.postMessage({type:'openSettings'}));

  moreBtn.addEventListener('click', e => {
    e.stopPropagation();
    const opening = headerMenu.classList.contains('hidden');
    headerMenu.classList.toggle('hidden');
    moreBtn.setAttribute('aria-expanded', String(opening));
  });
  document.addEventListener('click', e => {
    if (!headerMenu.classList.contains('hidden') && !headerMenu.contains(e.target) && e.target !== moreBtn) {
      headerMenu.classList.add('hidden'); moreBtn.setAttribute('aria-expanded', 'false');
    }
  });
  headerMenu.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
    headerMenu.classList.add('hidden'); moreBtn.setAttribute('aria-expanded', 'false');
  }));

  optionsBtn.addEventListener('click', () => {
    const compact = document.getElementById('selectors-row').classList.toggle('expanded');
    optionsBtn.setAttribute('aria-expanded', String(compact));
  });

  // ── Settings panel ───────────────────────────────────────────────────────

  function openSettingsPanel() { settingsOverlay.classList.remove('hidden'); settingsCloseBtn.focus(); }
  function closeSettingsPanel() { settingsOverlay.classList.add('hidden'); settingsBtn.focus(); }

  function populateSettingsPanel(settings, hasApiKey, maskedApiKey) {
    document.getElementById('set-apiEndpoint').value = settings.apiEndpoint || '';
    document.getElementById('set-effort').value = settings.effort || 'medium';
    document.getElementById('set-maxTokens').value = settings.maxTokens || 4096;
    document.getElementById('set-temperature').value = settings.temperature != null ? settings.temperature : 0.7;
    document.getElementById('set-autoReviewOnSave').checked = !!settings.autoReviewOnSave;
    document.getElementById('set-enableDiagnostics').checked = !!settings.enableDiagnostics;
    document.getElementById('set-theme').value = settings.theme || 'auto';
    settingsKeyStatus.textContent = hasApiKey ? ('Current key: ' + maskedApiKey) : 'No API key stored';
    settingsKeyStatus.className = 'settings-hint';
    openSettingsPanel();
  }

  settingsCloseBtn.addEventListener('click', closeSettingsPanel);
  settingsOverlay.addEventListener('click', e => { if (e.target === settingsOverlay) closeSettingsPanel(); });

  settingsSaveBtn.addEventListener('click', () => {
    vscode.postMessage({
      type: 'saveSettings',
      settings: {
        apiEndpoint: document.getElementById('set-apiEndpoint').value.trim(),
        effort: document.getElementById('set-effort').value,
        maxTokens: parseInt(document.getElementById('set-maxTokens').value, 10) || 4096,
        temperature: parseFloat(document.getElementById('set-temperature').value),
        autoReviewOnSave: document.getElementById('set-autoReviewOnSave').checked,
        enableDiagnostics: document.getElementById('set-enableDiagnostics').checked,
        theme: document.getElementById('set-theme').value,
      }
    });
  });

  settingsAdvancedBtn.addEventListener('click', () => vscode.postMessage({ type: 'openNativeSettings' }));

  settingsKeySaveBtn.addEventListener('click', () => {
    const key = document.getElementById('set-apiKey').value.trim();
    if (!key) { settingsKeyStatus.textContent = 'Enter a key first'; settingsKeyStatus.className='settings-hint settings-hint-err'; return; }
    vscode.postMessage({ type: 'saveApiKey', key });
  });

  // ── MCP panel ────────────────────────────────────────────────────────────

  function openMcpPanel() { mcpOverlay.classList.remove('hidden'); mcpCloseBtn.focus(); }
  function closeMcpPanel() { mcpOverlay.classList.add('hidden'); mcpBtn.focus(); }

  function renderMcpServers(servers, configPath, serverReachable) {
    if (!serverReachable) {
      mcpHint.textContent = 'Could not reach the Dabba server at the configured API endpoint — showing configured servers only. Start the server to connect them.';
      mcpHint.className = 'settings-hint settings-hint-err';
    } else {
      mcpHint.textContent = "Adding a server connects immediately. Editing/removing a server that's already connected needs a Dabba server restart to take effect.";
      mcpHint.className = 'settings-hint';
    }

    if (!servers || servers.length === 0) {
      mcpServerList.innerHTML = '<div class="mcp-empty">No MCP servers configured yet — config file: <code>' + escapeHtml(configPath || '') + '</code></div>';
      return;
    }

    mcpServerList.innerHTML = servers.map(s => {
      const badge = s.connected
        ? '<span class="mcp-badge mcp-badge-on">connected</span>'
        : '<span class="mcp-badge mcp-badge-off">not connected</span>';
      const tools = (s.tools || []).length
        ? '<div class="mcp-tools">' + s.tools.map(t => '<code>' + escapeHtml(t) + '</code>').join(' ') + '</div>'
        : '';
      return (
        '<div class="mcp-server-card">' +
          '<div class="mcp-server-row">' +
            '<span class="mcp-server-name">' + escapeHtml(s.name) + '</span>' +
            badge +
            '<button class="icon-btn mcp-remove-btn" data-name="' + escapeHtml(s.name) + '" title="Remove">🗑</button>' +
          '</div>' +
          '<div class="mcp-server-cmd">' + escapeHtml(s.command) + ' ' + escapeHtml((s.args || []).join(' ')) + '</div>' +
          tools +
        '</div>'
      );
    }).join('');

    mcpServerList.querySelectorAll('.mcp-remove-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        vscode.postMessage({ type: 'deleteMcpServer', name: btn.getAttribute('data-name') });
      });
    });
  }

  mcpBtn.addEventListener('click', () => { openMcpPanel(); vscode.postMessage({ type: 'openMcpPanel' }); });
  mcpCloseBtn.addEventListener('click', closeMcpPanel);
  mcpOverlay.addEventListener('click', e => { if (e.target === mcpOverlay) closeMcpPanel(); });

  mcpAddSaveBtn.addEventListener('click', () => {
    const name = document.getElementById('mcp-add-name').value.trim();
    const command = document.getElementById('mcp-add-command').value.trim();
    const args = document.getElementById('mcp-add-args').value;
    const env = document.getElementById('mcp-add-env').value;
    if (!name || !command) { return; }
    vscode.postMessage({ type: 'addMcpServer', name, command, args, env });
    document.getElementById('mcp-add-name').value = '';
    document.getElementById('mcp-add-command').value = '';
    document.getElementById('mcp-add-args').value = '';
    document.getElementById('mcp-add-env').value = '';
  });

  mcpRefreshBtn.addEventListener('click', () => vscode.postMessage({ type: 'reloadMcpServers' }));

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!settingsOverlay.classList.contains('hidden')) { e.preventDefault(); closeSettingsPanel(); return; }
    if (!mcpOverlay.classList.contains('hidden')) { e.preventDefault(); closeMcpPanel(); return; }
    if (!historyDropdown.classList.contains('hidden')) { e.preventDefault(); closeHistoryDropdown(); historyBtn.focus(); return; }
    if (!headerMenu.classList.contains('hidden')) { e.preventDefault(); headerMenu.classList.add('hidden'); moreBtn.setAttribute('aria-expanded', 'false'); moreBtn.focus(); }
  });

  inputEl.addEventListener('keydown', e => {
    const slashOpen = !slashPicker.classList.contains('hidden');
    const atOpen = !atPicker.classList.contains('hidden');
    if (slashOpen && matchingCommands.length > 0) {
      if (e.key==='ArrowDown') { e.preventDefault(); slashSelectedIdx=(slashSelectedIdx+1)%matchingCommands.length; updateSlashSuggestions(); return; }
      if (e.key==='ArrowUp') { e.preventDefault(); slashSelectedIdx=(slashSelectedIdx-1+matchingCommands.length)%matchingCommands.length; updateSlashSuggestions(); return; }
      if (e.key==='Enter'||e.key==='Tab') { e.preventDefault(); inputEl.value=matchingCommands[slashSelectedIdx].cmd+' '; slashPicker.classList.add('hidden'); autoResize(); return; }
      if (e.key==='Escape') { e.preventDefault(); slashPicker.classList.add('hidden'); return; }
    }
    if (atOpen && matchingFiles.length > 0) {
      if (e.key==='ArrowDown') { e.preventDefault(); atSelectedIdx=(atSelectedIdx+1)%matchingFiles.length; showAtPicker(inputEl.value.slice(inputEl.value.lastIndexOf('@')+1)); return; }
      if (e.key==='ArrowUp') { e.preventDefault(); atSelectedIdx=(atSelectedIdx-1+matchingFiles.length)%matchingFiles.length; showAtPicker(inputEl.value.slice(inputEl.value.lastIndexOf('@')+1)); return; }
      if (e.key==='Enter'||e.key==='Tab') { e.preventDefault(); selectMentionFile(matchingFiles[atSelectedIdx]); return; }
      if (e.key==='Escape') { e.preventDefault(); atPicker.classList.add('hidden'); return; }
    }
    if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  inputEl.addEventListener('input', () => {
    autoResize(); slashSelectedIdx=0; atSelectedIdx=0;
    const val = inputEl.value;
    updateSlashSuggestions();
    updateContextChip();
    const atIdx = val.lastIndexOf('@');
    if (atIdx !== -1 && (atIdx===0 || val[atIdx-1]===' ')) {
      if (allFiles.length === 0) vscode.postMessage({type:'searchFiles'});
      else showAtPicker(val.slice(atIdx+1));
    } else {
      atPicker.classList.add('hidden');
    }
  });

  // Refresh the editor-context part of the preview (active file/selection)
  // whenever the composer regains focus — cheap to query and covers the
  // common case of clicking back in after changing the selection/file.
  inputEl.addEventListener('focus', () => vscode.postMessage({ type: 'getContextPreview' }));

  // ── Messages from extension ───────────────────────────────────────────────

  window.addEventListener('message', msg => {
    const m = msg.data;
    switch (m.type) {
      case 'sessionsInit':
        sessions = m.sessions; activeSessionId = m.active; renderSessionTabs(); renderPinnedFilesForActiveSession(); break;
      case 'startupStatus':
        startupEnvironment = m;
        setConnectionState(m.backendReachable ? 'connected' : 'error', m.backendReachable ? 'Ready' : 'Backend offline');
        updateWelcomeEnvironment();
        break;
      case 'sessionCreated':
        sessions.push({id:m.id, label:m.label, messages:[], createdAt:m.createdAt, pinnedFiles:[]}); activeSessionId = m.id; renderSessionTabs();
        messagesEl.innerHTML=''; todoCard=null; lastUserMessageEl=null; regenRow.classList.add('hidden'); renderPinnedFilesForActiveSession(); renderWelcomeIfEmpty(); break;
      case 'pinnedFilesChanged': {
        const s = sessions.find(s => s.id === activeSessionId);
        if (s) { s.pinnedFiles = m.pinnedFiles; }
        renderPinnedFilesForActiveSession();
        break;
      }
      case 'historyDeleted':
        addSystemLine('🗑 All chat history deleted'); break;
      case 'addMessage':
        if (m.role==='user') addUserMessage(m.content, m.attachments, m.mentions);
        else addAgentText(m.content); break;
      case 'fileAttached':
        attachedFiles.push({name:m.name,path:m.path,isImage:m.isImage,base64Data:m.base64Data}); renderAttachments(); break;
      case 'voiceTranscript':
        micBtn.classList.remove('transcribing');
        if (m.text) { inputEl.value = (inputEl.value + ' ' + m.text).trim(); autoResize(); inputEl.focus(); }
        else { addSystemLine('Heard nothing — try again'); }
        break;
      case 'voiceError':
        recording = false;
        micBtn.classList.remove('recording'); micBtn.classList.remove('transcribing');
        addSystemLine('🎤 ' + m.content);
        break;
      case 'fileList':
        allFiles = m.files; showAtPicker(inputEl.value.slice(inputEl.value.lastIndexOf('@')+1)); break;
      case 'mentionFileContent':
        mentionedFiles.push({relativePath:m.relativePath,content:m.content}); renderMentions(); break;
      case 'permissionRequired':
        addPermissionCard(m.callId, m.toolName, m.args, m.untrustedWorkspace); break;
      case 'contextPreview':
        editorContextPreview = {
          activeFile: m.activeFile || null,
          selectionChars: m.selectionChars || 0,
          pinnedChars: m.pinnedChars || 0,
        };
        updateContextChip();
        break;
      case 'toolDenied':
        addSystemLine('Tool denied: '+m.name); break;
      case 'agentStart':
        running=true; currentTools={}; statusBar.classList.remove('hidden'); statusPhase.textContent='Working'; statusText.textContent='Preparing request…';
        setConnectionState('working', 'Working'); startStatusTimer();
        sendBtn.disabled=true; composerSpinner.classList.remove('hidden'); regenRow.classList.add('hidden'); break;
      case 'agentText': statusPhase.textContent='Responding'; statusText.textContent='Receiving model output'; setConnectionState('connected','Connected'); addAgentText(m.content); break;
      case 'toolCall':
        addToolCall(m.callId, m.name, m.args, m.thought, m.isDangerous, m.isEdit); break;
      case 'toolResult':
        addToolResult(m.name, m.success, m.output, m.filePath, m.isEdit, m.isArtifact); break;
      case 'todoUpdate': renderTodoCard(m.todos || []); break;
      case 'agentPlan': addPlanCard(m.steps); break;
      case 'tokenUsage':
        totalInputTokens += (m.inputTokens||0); totalOutputTokens += (m.outputTokens||0); updateTokenCounter(); break;
      case 'agentError': setConnectionState('error', /key|401|403/i.test(m.content) ? 'Check API key' : 'Request failed'); statusPhase.textContent='Request failed'; statusText.textContent=m.content; addError(m.content, !!m.retryable); break;
      case 'agentInterrupted': addSystemLine('Interrupted'); break;
      case 'agentEnd':
        running=false; stopStatusTimer(); statusBar.classList.add('hidden'); sendBtn.disabled=false;
        if (!connectionBadge.classList.contains('error')) setConnectionState('connected','Ready');
        composerSpinner.classList.add('hidden'); inputEl.focus();
        if (lastUserMessageEl) { regenBtn.disabled = false; regenRow.classList.remove('hidden'); }
        break;
      case 'removeLastTurn': removeLastTurn(); break;
      case 'permissionModeChanged':
        applyPermissionMode(m.mode); break;
      case 'clearMessages':
        messagesEl.innerHTML=''; todoCard=null; currentTools={}; changedFiles=[]; renderChangedFiles();
        totalInputTokens=0; totalOutputTokens=0; updateTokenCounter();
        lastUserMessageEl=null; regenRow.classList.add('hidden');
        renderWelcomeIfEmpty();
        break;
      case 'restoreDone':
        setConnectionState('connected', 'Ready'); renderWelcomeIfEmpty();
        break;
      case 'modelsLoaded':
        if (m.effort) { currentEffort=m.effort; effortBtn.textContent=currentEffort+' ▾'; }
        renderModels(m.models||[], m.current); break;
      case 'modelsLoadError':
        modelPicker.innerHTML='<div class="picker-loading" style="color:var(--red);font-size:11px;padding:10px;">'+escapeHtml(m.error)+'</div>'; break;
      case 'modelSet':
        modelBtn.textContent=(m.model.split('/').pop()||m.model)+' ▾'; addSystemLine('Model → '+m.model); break;
      case 'effortSet':
        currentEffort=m.effort; effortBtn.textContent=currentEffort+' ▾'; addSystemLine('Reasoning Effort → '+currentEffort); break;
      case 'fileChanged':
        changedFiles = m.changedFiles || []; renderChangedFiles(); break;
      case 'settingsData':
        populateSettingsPanel(m.settings, m.hasApiKey, m.maskedApiKey); break;
      case 'settingsSaved':
        addSystemLine('⚙ Settings saved'); closeSettingsPanel(); break;
      case 'mcpData':
        renderMcpServers(m.servers, m.configPath, m.serverReachable); break;
      case 'mcpError':
        mcpHint.textContent = m.content; mcpHint.className = 'settings-hint settings-hint-err'; break;
      case 'apiKeySaved':
        settingsKeyStatus.textContent = '✓ Key saved'; settingsKeyStatus.className = 'settings-hint settings-hint-ok';
        document.getElementById('set-apiKey').value = ''; break;
    }
  });

  // Tell the extension host we're ready to receive session data + replayed history
  vscode.postMessage({ type: 'ready' });
  inputEl.focus();
})();
