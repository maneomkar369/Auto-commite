const terminal = document.getElementById('terminalOutput');
const mirrorText = document.getElementById('mirrorText');
const mirrorReflection = document.getElementById('mirrorReflection');
const healthStatus = document.getElementById('healthStatus');
const liveState = document.getElementById('liveState');
const mirrorFrame = document.querySelector('.mirror-frame');
const stateMode = document.getElementById('stateMode');
const stateLatency = document.getElementById('stateLatency');
const statePhase = document.getElementById('statePhase');
const stateStatus = document.getElementById('stateStatus');
const authPage = document.getElementById('authPage');
const enginePage = document.getElementById('enginePage');
const goAuthPage = document.getElementById('goAuthPage');
const goEnginePage = document.getElementById('goEnginePage');
const continueToEngineBtn = document.getElementById('continueToEngineBtn');

let typeTimer = null;

function showPage(page) {
  const authActive = page === 'auth';
  authPage.classList.toggle('active', authActive);
  enginePage.classList.toggle('active', !authActive);
  goAuthPage.classList.toggle('active', authActive);
  goEnginePage.classList.toggle('active', !authActive);
}

function printTerminal(message) {
  const stamp = new Date().toLocaleTimeString();
  terminal.textContent = `${terminal.textContent}\n[${stamp}] ${message}`;
  terminal.scrollTop = terminal.scrollHeight;
}

function setMirror(content) {
  if (typeTimer) {
    clearInterval(typeTimer);
    typeTimer = null;
  }

  mirrorText.textContent = '';
  mirrorReflection.textContent = '';

  const source = String(content);
  let index = 0;
  typeTimer = setInterval(() => {
    index += 4;
    const current = source.slice(0, index);
    mirrorText.textContent = current;
    mirrorReflection.textContent = current;
    if (index >= source.length) {
      clearInterval(typeTimer);
      typeTimer = null;
    }
  }, 12);
}

function setExecutionState(running, phase = 'idle') {
  liveState.textContent = running ? 'Running' : 'Idle';
  liveState.classList.toggle('running', running);
  statePhase.textContent = phase;
  stateMode.textContent = running ? 'executing' : 'standby';
  terminal.classList.toggle('typing', running);
  mirrorFrame.classList.toggle('executing', running);
}

async function checkHealth() {
  try {
    const res = await fetch('/health');
    const json = await res.json();
    healthStatus.textContent = json.status === 'ok' ? 'API Online' : 'API Unknown';
    healthStatus.style.color = json.status === 'ok' ? '#6cf0c2' : '#ff6a8a';
    stateStatus.textContent = json.status === 'ok' ? 'healthy' : 'unstable';
  } catch (error) {
    healthStatus.textContent = 'API Offline';
    healthStatus.style.color = '#ff6a8a';
    stateStatus.textContent = 'offline';
  }
}

async function checkAuthStatus() {
  try {
    const res = await fetch('/auth/status');
    if (!res.ok) return;
    const json = await res.json();
    stateMode.textContent = json.github_token_set ? 'authenticated' : 'standby';
    if (json.github_token_set) {
      showPage('engine');
    } else {
      showPage('auth');
    }
    if (json.ollama_url) {
      document.getElementById('ollamaUrlInput').value = json.ollama_url;
    }
    if (json.ollama_model) {
      document.getElementById('ollamaModelInput').value = json.ollama_model;
    }
  } catch {
    // no-op
  }
}

function toQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value));
    }
  });
  return query.toString();
}

async function callEndpoint(path, params) {
  const query = toQuery(params);
  const url = query ? `${path}?${query}` : path;

  setExecutionState(true, 'dispatch');
  setMirror(`$ POST ${url}`);
  printTerminal(`$ curl -X POST '${url}'`);

  const start = performance.now();

  try {
    setExecutionState(true, 'waiting');
    const res = await fetch(url, { method: 'POST' });
    const text = await res.text();
    const duration = Math.round(performance.now() - start);

    stateLatency.textContent = `${duration}ms`;
    statePhase.textContent = 'response';
    stateStatus.textContent = res.ok ? 'success' : 'error';

    printTerminal(text);
    setMirror(text.slice(0, 520));
  } catch (error) {
    stateStatus.textContent = 'error';
    printTerminal(`Request failed: ${error.message || error}`);
    setMirror(`Request failed: ${error.message || error}`);
  } finally {
    setExecutionState(false, 'idle');
  }
}

document.getElementById('runInternalBtn').addEventListener('click', async () => {
  const issueNumber = document.getElementById('issueNumber').value.trim();
  const dryRun = document.getElementById('dryRunInternal').checked;
  const ensureIssue = document.getElementById('ensureIssue').checked;

  const path = ensureIssue ? '/autonomous/ensure-run-now' : '/autonomous/run-now';
  await callEndpoint(path, {
    issue_number: issueNumber || undefined,
    dry_run: dryRun,
  });
});

document.getElementById('saveAuthBtn').addEventListener('click', async () => {
  const githubToken = document.getElementById('githubTokenInput').value.trim();
  const modelApiKey = document.getElementById('modelApiKeyInput').value.trim();
  const ollamaUrl = document.getElementById('ollamaUrlInput').value.trim();
  const ollamaModel = document.getElementById('ollamaModelInput').value.trim();

  if (!githubToken) {
    printTerminal('GitHub token is required.');
    setMirror('GitHub token is required.');
    return;
  }

  setExecutionState(true, 'auth-verify');
  const start = performance.now();

  try {
    const res = await fetch('/auth/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        github_token: githubToken,
        model_api_key: modelApiKey || null,
        ollama_url: ollamaUrl || null,
        ollama_model: ollamaModel || null,
      }),
    });

    const text = await res.text();
    const duration = Math.round(performance.now() - start);
    stateLatency.textContent = `${duration}ms`;
    stateStatus.textContent = res.ok ? 'authenticated' : 'auth-error';
    stateMode.textContent = res.ok ? 'authenticated' : 'standby';
    printTerminal(text);
    setMirror(text.slice(0, 520));
    if (res.ok) {
      showPage('engine');
    }
  } catch (error) {
    stateStatus.textContent = 'auth-error';
    printTerminal(`Auth failed: ${error.message || error}`);
    setMirror(`Auth failed: ${error.message || error}`);
  } finally {
    setExecutionState(false, 'idle');
  }
});

continueToEngineBtn.addEventListener('click', () => {
  showPage('engine');
  statePhase.textContent = 'navigation';
});

goAuthPage.addEventListener('click', () => showPage('auth'));
goEnginePage.addEventListener('click', () => showPage('engine'));

document.getElementById('useRepoLinkBtn').addEventListener('click', () => {
  const repoLink = document.getElementById('repoLink').value.trim();
  if (!repoLink) {
    printTerminal('Please paste a GitHub repository link first.');
    return;
  }

  let parsed;
  try {
    parsed = new URL(repoLink);
  } catch {
    printTerminal('Invalid URL format. Example: https://github.com/owner/repo');
    return;
  }

  const host = parsed.hostname.toLowerCase();
  if (host !== 'github.com' && host !== 'www.github.com') {
    printTerminal('Only github.com repository links are supported.');
    return;
  }

  const parts = parsed.pathname.split('/').filter(Boolean);
  if (parts.length < 2) {
    printTerminal('Repository URL must include owner and repo.');
    return;
  }

  const owner = parts[0];
  const repo = parts[1].replace(/\.git$/i, '');

  document.getElementById('upstreamOwner').value = owner;
  document.getElementById('upstreamRepo').value = repo;

  const msg = `Fork workflow target set to ${owner}/${repo}`;
  printTerminal(msg);
  setMirror(msg);
  statePhase.textContent = 'repo-selected';
  stateStatus.textContent = 'ready';
});

document.getElementById('runForkBtn').addEventListener('click', async () => {
  const upstreamOwner = document.getElementById('upstreamOwner').value.trim();
  const upstreamRepo = document.getElementById('upstreamRepo').value.trim();
  const issueNumber = document.getElementById('forkIssueNumber').value.trim();
  const dryRun = document.getElementById('dryRunFork').checked;
  const createIfMissing = document.getElementById('createIfMissing').checked;

  if (!upstreamOwner || !upstreamRepo) {
    printTerminal('Please provide upstream owner and repo for fork workflow.');
    return;
  }

  await callEndpoint('/autonomous/fork-run-now', {
    upstream_owner: upstreamOwner,
    upstream_repo: upstreamRepo,
    issue_number: issueNumber || undefined,
    dry_run: dryRun,
    allow_create_issue_if_missing: createIfMissing,
  });
});

checkHealth();
checkAuthStatus();
printTerminal('Terminal ready. Run an internal or fork workflow command.');
setMirror('$ ready');
setExecutionState(false, 'idle');
showPage('auth');
