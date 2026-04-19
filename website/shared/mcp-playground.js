/* ============================================================================
 * Demo 4 · MCP 在线调用试玩
 * 真实调 http://118.178.242.26/mcp/call · 失败优雅降级到本地 sample
 * 暴露 FG.MCPPlayground.mount(rootEl, opts)
 * ========================================================================== */
(function () {
  const STYLE_ID = 'fg-mcp-style';
  const TOOLS = window.FG.mcpTools;
  const ENDPOINT_TOOLS = window.FG.meta.liveUrls.mcpTools;
  const ENDPOINT_CALL = window.FG.meta.liveUrls.mcpCall;

  function injectStyle(theme) {
    if (document.getElementById(STYLE_ID)) return;
    const dark = theme === 'dark';
    const css = `
.fg-mcp{--m-bg:${dark?'#0c0a09':'#fff'};--m-fg:${dark?'#fafaf9':'#0c0a09'};--m-fg2:${dark?'#a8a29e':'#525252'};--m-fg3:${dark?'#57534e':'#a8a29e'};--m-bd:${dark?'#262220':'#e7e5e4'};--m-soft:${dark?'#1c1917':'#f5f5f4'};--m-blue:#3370FF;--m-green:#10b981;--m-amber:#f59e0b;--m-red:#ef4444;font-family:Inter,-apple-system,'PingFang SC',sans-serif;background:var(--m-bg);color:var(--m-fg);border:1px solid var(--m-bd);border-radius:14px;padding:24px;display:grid;grid-template-columns:1fr 1fr;gap:24px}
.fg-mcp *{box-sizing:border-box}
.fg-mcp .left{display:flex;flex-direction:column;gap:14px}
.fg-mcp label{font-size:11px;color:var(--m-fg3);text-transform:uppercase;letter-spacing:.06em;font-weight:600;display:block;margin-bottom:5px}
.fg-mcp .endpoint{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--m-fg2);background:var(--m-soft);padding:8px 11px;border-radius:6px;border:1px solid var(--m-bd);overflow-x:auto;white-space:nowrap}
.fg-mcp select,.fg-mcp textarea{width:100%;background:var(--m-soft);border:1px solid var(--m-bd);color:var(--m-fg);padding:10px 12px;border-radius:7px;font-size:13px;font-family:inherit;resize:vertical}
.fg-mcp select:focus,.fg-mcp textarea:focus{outline:none;border-color:var(--m-blue)}
.fg-mcp textarea{font-family:'JetBrains Mono',monospace;font-size:12px;min-height:140px;line-height:1.55}
.fg-mcp .tool-desc{font-size:12.5px;color:var(--m-fg2);line-height:1.6;padding:8px 12px;background:var(--m-soft);border-left:3px solid var(--m-blue);border-radius:0 6px 6px 0}
.fg-mcp .btn-row{display:flex;gap:8px}
.fg-mcp .btn{padding:9px 18px;border-radius:7px;border:1px solid var(--m-bd);cursor:pointer;font-size:13px;font-weight:500;background:var(--m-bg);color:var(--m-fg);transition:all .15s;display:inline-flex;align-items:center;gap:6px}
.fg-mcp .btn:hover{border-color:var(--m-blue);color:var(--m-blue)}
.fg-mcp .btn.primary{background:var(--m-blue);color:#fff;border-color:var(--m-blue)}
.fg-mcp .btn.primary:hover{background:#2860e0;color:#fff}
.fg-mcp .btn:disabled{opacity:.5;cursor:not-allowed}
.fg-mcp .right{display:flex;flex-direction:column;gap:10px}
.fg-mcp .status-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:14px;font-size:11px;font-family:'JetBrains Mono',monospace;font-weight:500;width:fit-content}
.fg-mcp .status-pill.idle{background:var(--m-soft);color:var(--m-fg3)}
.fg-mcp .status-pill.loading{background:#fef3c7;color:#92400e}
.fg-mcp .status-pill.ok{background:#d1fae5;color:#065f46}
.fg-mcp .status-pill.err{background:#fee2e2;color:#991b1b}
.fg-mcp .status-pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.fg-mcp .status-pill.loading .dot{animation:fg-mcp-pulse 1s infinite}
@keyframes fg-mcp-pulse{0%,100%{opacity:1}50%{opacity:.3}}
.fg-mcp .json-view{background:#0c0a09;color:#d4d4d4;border-radius:8px;padding:14px 16px;font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.65;overflow:auto;min-height:240px;max-height:380px;white-space:pre;border:1px solid #262220}
.fg-mcp .json-view .k{color:#7dd3fc}
.fg-mcp .json-view .s{color:#86efac}
.fg-mcp .json-view .n{color:#fcd34d}
.fg-mcp .json-view .b{color:#f9a8d4}
.fg-mcp .meta-line{font-size:10.5px;color:var(--m-fg3);font-family:'JetBrains Mono',monospace}
.fg-mcp .meta-line .badge{padding:1px 7px;border-radius:8px;background:var(--m-soft);margin-right:5px}
@media(max-width:760px){.fg-mcp{grid-template-columns:1fr}.fg-mcp .json-view{font-size:11px;min-height:160px}}
`;
    const el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = css;
    document.head.appendChild(el);
  }

  function jsonHighlight(obj) {
    const str = JSON.stringify(obj, null, 2);
    return str
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"([^"\\]+)":/g, '<span class="k">"$1"</span>:')
      .replace(/: ?"([^"]*)"/g, ': <span class="s">"$1"</span>')
      .replace(/: ?(\-?\d+\.?\d*)/g, ': <span class="n">$1</span>')
      .replace(/: ?(true|false|null)/g, ': <span class="b">$1</span>');
  }

  function mount(rootEl, opts = {}) {
    const theme = opts.theme || 'light';
    injectStyle(theme);
    rootEl.classList.add('fg-mcp');
    rootEl.innerHTML = `
<div class="left">
  <div>
    <label>MCP HTTP Endpoint</label>
    <div class="endpoint">POST ${ENDPOINT_CALL}</div>
  </div>
  <div>
    <label>Tool</label>
    <select data-tool>
      ${TOOLS.map((t, i) => `<option value="${i}">${t.name}</option>`).join('')}
    </select>
  </div>
  <div class="tool-desc" data-tooldesc></div>
  <div>
    <label>Arguments (JSON)</label>
    <textarea data-args spellcheck="false"></textarea>
  </div>
  <div class="btn-row">
    <button class="btn primary" data-call>▶ Call MCP</button>
    <button class="btn" data-list>List Tools</button>
    <button class="btn" data-reset>Reset</button>
  </div>
</div>
<div class="right">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <span class="status-pill idle" data-status><span class="dot"></span>idle</span>
    <span class="meta-line" data-meta></span>
  </div>
  <div class="json-view" data-out>// 选择一个工具，点 ▶ Call MCP\n// 真实请求会发到 ${ENDPOINT_CALL}\n// 若服务暂时不可达，会 fallback 到本地样例响应</div>
</div>`;

    function loadTool(idx) {
      const t = TOOLS[idx];
      rootEl.querySelector('[data-tooldesc]').textContent = t.desc;
      rootEl.querySelector('[data-args]').value = JSON.stringify(t.args, null, 2);
    }
    function setStatus(kind, text, meta) {
      const pill = rootEl.querySelector('[data-status]');
      pill.className = 'status-pill ' + kind;
      pill.innerHTML = `<span class="dot"></span>${text}`;
      if (meta !== undefined) rootEl.querySelector('[data-meta]').innerHTML = meta;
    }
    function showJson(obj) {
      rootEl.querySelector('[data-out]').innerHTML = jsonHighlight(obj);
    }

    rootEl.querySelector('[data-tool]').addEventListener('change', e => loadTool(+e.target.value));
    rootEl.querySelector('[data-reset]').addEventListener('click', () => loadTool(+rootEl.querySelector('[data-tool]').value));

    rootEl.querySelector('[data-list]').addEventListener('click', async () => {
      setStatus('loading', 'GET /mcp/tools ...');
      const t0 = performance.now();
      try {
        const r = await fetch(ENDPOINT_TOOLS, { headers: { 'Accept': 'application/json' } });
        const data = await r.json();
        const dt = (performance.now() - t0).toFixed(0);
        setStatus('ok', '200 OK', `<span class="badge">${dt}ms</span> ${ENDPOINT_TOOLS}`);
        showJson(data);
      } catch (err) {
        const dt = (performance.now() - t0).toFixed(0);
        setStatus('err', 'fallback (local sample)', `<span class="badge">${dt}ms</span> 服务暂未响应，显示本地样例`);
        showJson({ tools: TOOLS.map(t => ({ name: t.name, description: t.desc, schema: { type: 'object', properties: Object.fromEntries(Object.keys(t.args).map(k => [k, { type: 'string' }])) } })) });
      }
    });

    rootEl.querySelector('[data-call]').addEventListener('click', async () => {
      const idx = +rootEl.querySelector('[data-tool]').value;
      const t = TOOLS[idx];
      let args;
      try {
        args = JSON.parse(rootEl.querySelector('[data-args]').value);
      } catch (e) {
        setStatus('err', 'JSON parse error', '');
        showJson({ error: 'invalid JSON in arguments', detail: String(e) });
        return;
      }
      const body = { tool: t.name, arguments: args };
      setStatus('loading', `POST /mcp/call · ${t.name}`);
      const t0 = performance.now();
      try {
        const r = await fetch(ENDPOINT_CALL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json();
        const dt = (performance.now() - t0).toFixed(0);
        setStatus('ok', `${r.status} ${r.statusText || 'OK'}`, `<span class="badge">${dt}ms</span> live · ${ENDPOINT_CALL}`);
        showJson(data);
      } catch (err) {
        const dt = (performance.now() - t0).toFixed(0);
        setStatus('err', 'fallback (local sample)', `<span class="badge">${dt}ms</span> 服务暂未响应，显示本地样例`);
        showJson({ tool: t.name, arguments: args, result: t.sampleResp, _note: 'this is a local fallback sample, not from server' });
      }
    });

    loadTool(0);
  }

  window.FG.MCPPlayground = { mount };
})();
