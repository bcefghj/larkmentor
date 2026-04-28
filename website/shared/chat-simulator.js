/* ============================================================================
 * Demo 1 · 飞书聊天模拟器
 * 仿真飞书桌面端 UI（左侧群列表 / 中间消息流 / 右侧 LarkMentor 守护面板）
 * 暴露 FG.ChatSim.mount(rootEl, options) 到全局
 * ========================================================================== */
(function () {
  const STYLE_ID = 'fg-chatsim-style';
  const SCRIPT = window.FG.simScript;

  function injectStyle(theme) {
    if (document.getElementById(STYLE_ID)) return;
    const dark = theme === 'dark';
    const css = `
.fg-sim{--sim-bg:${dark?'#0c0a09':'#fff'};--sim-fg:${dark?'#fafaf9':'#0c0a09'};--sim-fg2:${dark?'#a8a29e':'#525252'};--sim-fg3:${dark?'#57534e':'#a8a29e'};--sim-bd:${dark?'#262220':'#e7e5e4'};--sim-side:${dark?'#1c1917':'#f5f5f4'};--sim-bubble:${dark?'#262220':'#f5f5f4'};--sim-blue:#3370FF;--sim-mine:#ddebff;--sim-p0:#ef4444;--sim-p1:#f59e0b;--sim-p2:#10b981;--sim-p3:#9ca3af;font-family:Inter,-apple-system,'PingFang SC',sans-serif;background:var(--sim-bg);color:var(--sim-fg);border:1px solid var(--sim-bd);border-radius:14px;overflow:hidden;display:grid;grid-template-rows:auto 1fr auto;height:680px;max-height:90vh;box-shadow:0 24px 64px rgba(0,0,0,${dark?.4:.08});position:relative}
.fg-sim *{box-sizing:border-box}
.fg-sim .top{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--sim-bd);background:var(--sim-side);font-size:12px;color:var(--sim-fg2)}
.fg-sim .top .traffic{display:flex;gap:6px}.fg-sim .traffic span{width:11px;height:11px;border-radius:50%;display:block}
.fg-sim .traffic .r{background:#ff5f57}.fg-sim .traffic .y{background:#febc2e}.fg-sim .traffic .g{background:#28c840}
.fg-sim .top .title{flex:1;text-align:center;font-weight:500;color:var(--sim-fg)}
.fg-sim .body{display:grid;grid-template-columns:160px 1fr 280px;overflow:hidden;min-height:0}
.fg-sim .side{background:var(--sim-side);border-right:1px solid var(--sim-bd);overflow-y:auto;padding:8px 0}
.fg-sim .side h4{font-size:10px;color:var(--sim-fg3);text-transform:uppercase;letter-spacing:.08em;padding:6px 14px;margin:0;font-weight:600}
.fg-sim .chat-item{padding:8px 14px;display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:var(--sim-fg)}
.fg-sim .chat-item.active{background:${dark?'#262220':'#fff'};border-left:3px solid var(--sim-blue);padding-left:11px}
.fg-sim .chat-item .avatar{width:28px;height:28px;border-radius:50%;background:var(--sim-bubble);display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.fg-sim .chat-item .info{min-width:0;flex:1}.fg-sim .chat-item .info .n{font-weight:500;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fg-sim .chat-item .badge{background:var(--sim-p0);color:#fff;font-size:10px;border-radius:10px;padding:1px 6px;display:none}
.fg-sim .chat-item.has-unread .badge{display:inline-block;animation:fg-pulse 1.6s infinite}
@keyframes fg-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.18)}}
.fg-sim .stream{padding:14px 18px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;background:var(--sim-bg);scroll-behavior:smooth}
.fg-sim .system-line{align-self:center;font-size:11px;color:var(--sim-fg3);background:var(--sim-side);padding:4px 12px;border-radius:10px;margin:6px 0}
.fg-sim .msg{display:flex;gap:8px;align-items:flex-start;animation:fg-slide-in .35s ease}
@keyframes fg-slide-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.fg-sim .msg .avatar{width:32px;height:32px;border-radius:50%;background:var(--sim-bubble);display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.fg-sim .msg .bubble-wrap{max-width:75%;display:flex;flex-direction:column;gap:3px}
.fg-sim .msg .meta{font-size:11px;color:var(--sim-fg3);display:flex;gap:6px;align-items:center}
.fg-sim .msg .meta .chat-name{color:var(--sim-fg2)}
.fg-sim .msg .bubble{background:var(--sim-bubble);padding:9px 13px;border-radius:4px 12px 12px 12px;font-size:13.5px;line-height:1.55;color:var(--sim-fg);position:relative}
.fg-sim .msg.bot-reply .bubble{background:#dcfce7;color:#166534;border-radius:4px 12px 12px 12px}
.fg-sim .msg.bot-reply .meta{color:#10b981}
.fg-sim .urgent-card{border:2px solid var(--sim-p0);background:${dark?'#3a1a1a':'#fff5f5'};border-radius:8px;padding:12px;margin-top:6px;font-size:12.5px;color:var(--sim-fg);box-shadow:0 4px 16px rgba(239,68,68,.25);animation:fg-shake .55s}
@keyframes fg-shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}
.fg-sim .urgent-card .h{display:flex;align-items:center;gap:6px;color:var(--sim-p0);font-weight:600;margin-bottom:6px;font-size:11px;letter-spacing:.06em}
.fg-sim .recovery-card{align-self:stretch;border:1px solid var(--sim-blue);background:${dark?'#1a2740':'#eff6ff'};border-radius:12px;padding:18px;margin:10px 0;font-size:13px;color:var(--sim-fg);box-shadow:0 8px 32px rgba(51,112,255,.18);animation:fg-slide-in .5s}
.fg-sim .recovery-card .title{font-size:14px;font-weight:600;margin-bottom:10px;color:var(--sim-blue)}
.fg-sim .recovery-card .stats{display:flex;gap:14px;margin-bottom:12px;font-size:11.5px;color:var(--sim-fg2)}
.fg-sim .recovery-card .stats span strong{color:var(--sim-fg);font-size:14px;font-family:'JetBrains Mono',monospace;display:block}
.fg-sim .recovery-card ul{margin:0;padding:0;list-style:none}
.fg-sim .recovery-card li{padding:5px 0;font-size:12.5px;color:var(--sim-fg)}
.fg-sim .recovery-card .doc-link{margin-top:10px;padding-top:10px;border-top:1px dashed var(--sim-bd);font-size:11px;color:var(--sim-fg3)}
.fg-sim .panel{background:var(--sim-side);border-left:1px solid var(--sim-bd);padding:12px 14px;overflow-y:auto;font-size:12px;color:var(--sim-fg2)}
.fg-sim .panel h4{font-size:10.5px;color:var(--sim-fg3);text-transform:uppercase;letter-spacing:.08em;margin:8px 0;font-weight:600}
.fg-sim .panel .badge-state{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:14px;background:var(--sim-blue);color:#fff;font-size:11px;font-weight:500}
.fg-sim .panel .badge-state .dot{width:6px;height:6px;background:#fff;border-radius:50%;animation:fg-pulse 1.4s infinite}
.fg-sim .panel .score-row{margin:6px 0;font-family:'JetBrains Mono',monospace;font-size:11.5px;display:flex;align-items:center;gap:6px}
.fg-sim .panel .score-row .lbl{flex-shrink:0;color:var(--sim-fg3);width:46px}
.fg-sim .panel .score-row .bar{flex:1;height:5px;background:var(--sim-bd);border-radius:3px;overflow:hidden}
.fg-sim .panel .score-row .bar i{display:block;height:100%;background:var(--sim-blue);transition:width .4s ease}
.fg-sim .panel .score-row .v{flex-shrink:0;width:32px;text-align:right;color:var(--sim-fg2)}
.fg-sim .panel .verdict{margin-top:8px;padding:8px 10px;border-radius:6px;font-size:12px;font-weight:600;color:#fff;text-align:center;letter-spacing:.04em;font-family:'JetBrains Mono',monospace}
.fg-sim .panel .reason{font-size:11px;color:var(--sim-fg3);margin-top:6px;line-height:1.55}
.fg-sim .panel .ledger{margin-top:14px;display:flex;flex-direction:column;gap:5px}
.fg-sim .panel .ledger .row{display:flex;justify-content:space-between;font-size:11.5px;font-family:'JetBrains Mono',monospace;color:var(--sim-fg2);padding:4px 0;border-bottom:1px solid var(--sim-bd)}
.fg-sim .panel .ledger .row strong{color:var(--sim-fg)}
.fg-sim .panel .ledger .p0 strong{color:var(--sim-p0)}.fg-sim .panel .ledger .p1 strong{color:var(--sim-p1)}.fg-sim .panel .ledger .p2 strong{color:var(--sim-p2)}.fg-sim .panel .ledger .p3 strong{color:var(--sim-p3)}
.fg-sim .controls{display:flex;align-items:center;gap:10px;padding:10px 14px;border-top:1px solid var(--sim-bd);background:var(--sim-side);font-size:12px}
.fg-sim .controls .btn{background:var(--sim-bg);border:1px solid var(--sim-bd);color:var(--sim-fg);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;transition:all .15s;display:inline-flex;align-items:center;gap:5px}
.fg-sim .controls .btn:hover{border-color:var(--sim-blue);color:var(--sim-blue)}
.fg-sim .controls .btn.primary{background:var(--sim-blue);color:#fff;border-color:var(--sim-blue)}
.fg-sim .controls .btn.primary:hover{background:#2860e0}
.fg-sim .controls .timeline{flex:1;height:4px;background:var(--sim-bd);border-radius:2px;overflow:hidden}
.fg-sim .controls .timeline i{display:block;height:100%;background:var(--sim-blue);width:0;transition:width .3s linear}
.fg-sim .controls .clock{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--sim-fg3);min-width:46px;text-align:right}
@media(max-width:820px){.fg-sim .body{grid-template-columns:1fr 240px}.fg-sim .side{display:none}}
@media(max-width:560px){.fg-sim .body{grid-template-columns:1fr}.fg-sim .panel{display:none}.fg-sim{height:520px}}
`;
    const el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = css;
    document.head.appendChild(el);
  }

  function buildLayout(root, theme) {
    const sideChats = [
      { name: '产品评审群', icon: '💬', key: '产品评审群' },
      { name: '运维告警群', icon: '⚠️', key: '运维告警群' },
      { name: '部门闲聊群', icon: '🍔', key: '部门闲聊群' },
      { name: '王五', icon: '👨', key: '王五 · 私聊' },
      { name: '陈总', icon: '👔', key: '老板 · 私聊' },
      { name: 'LarkMentor', icon: '🛡️', key: 'LarkMentor', special: true },
    ];
    root.classList.add('fg-sim');
    root.innerHTML = `
<div class="top">
  <div class="traffic"><span class="r"></span><span class="y"></span><span class="g"></span></div>
  <div class="title">飞书 · 消息</div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--sim-fg3)">LarkMentor Live Demo</div>
</div>
<div class="body">
  <div class="side" data-side>
    <h4>会话</h4>
    ${sideChats.map((c,i) => `
      <div class="chat-item ${c.special?'active':''}" data-chat="${c.key}">
        <div class="avatar">${c.icon}</div>
        <div class="info"><div class="n">${c.name}</div></div>
        <span class="badge">!</span>
      </div>`).join('')}
  </div>
  <div class="stream" data-stream></div>
  <div class="panel" data-panel>
    <span class="badge-state" data-state><span class="dot"></span>SHIELD READY</span>
    <h4 style="margin-top:14px">实时分类</h4>
    <div data-scoreboard><div style="font-size:11px;color:var(--sim-fg3);font-style:italic">等待消息进入...</div></div>
    <h4>本次专注 · 累计</h4>
    <div class="ledger">
      <div class="row p0"><span>P0 加急</span><strong data-cnt="P0">0</strong></div>
      <div class="row p1"><span>P1 暂存</span><strong data-cnt="P1">0</strong></div>
      <div class="row p2"><span>P2 代回</span><strong data-cnt="P2">0</strong></div>
      <div class="row p3"><span>P3 静默</span><strong data-cnt="P3">0</strong></div>
    </div>
  </div>
</div>
<div class="controls">
  <button class="btn primary" data-act="play">▶ 播放</button>
  <button class="btn" data-act="step">⏭ 单步</button>
  <button class="btn" data-act="replay">↻ 重播</button>
  <div class="timeline"><i data-progress></i></div>
  <span class="clock" data-clock>0.0s</span>
</div>`;
  }

  function makeMsgEl(ev) {
    const div = document.createElement('div');
    div.className = 'msg';
    div.innerHTML = `
      <div class="avatar">${ev.avatar || '👤'}</div>
      <div class="bubble-wrap">
        <div class="meta"><span class="chat-name">${ev.chat || ''}</span> · <span>${ev.sender}</span></div>
        <div class="bubble">${ev.text}</div>
      </div>`;
    return div;
  }
  function makeBotReply(ev, replyText) {
    const div = document.createElement('div');
    div.className = 'msg bot-reply';
    div.innerHTML = `
      <div class="avatar">🛡️</div>
      <div class="bubble-wrap">
        <div class="meta">LarkMentor · 自动代回复</div>
        <div class="bubble">${replyText}</div>
      </div>`;
    return div;
  }
  function makeUrgentCard(ev) {
    const div = document.createElement('div');
    div.className = 'urgent-card';
    div.innerHTML = `
      <div class="h">⚡ P0 加急推送 · 已置顶</div>
      <div><strong>${ev.sender}</strong> @ ${ev.chat || '私聊'}</div>
      <div style="margin-top:4px;color:var(--sim-fg2)">${ev.text}</div>
      <div style="margin-top:6px;font-size:10.5px;color:var(--sim-fg3);font-family:'JetBrains Mono',monospace">score=${ev.classify.score.toFixed(2)} · ${ev.classify.reason}</div>`;
    return div;
  }
  function makeSystemLine(text) {
    const div = document.createElement('div');
    div.className = 'system-line';
    div.textContent = text;
    return div;
  }
  function makeRecovery(ev) {
    const div = document.createElement('div');
    div.className = 'recovery-card';
    div.innerHTML = `
      <div class="title">${ev.title}</div>
      <div class="stats">
        <span><strong>${ev.blocked.p0}</strong>P0</span>
        <span><strong>${ev.blocked.p1}</strong>P1</span>
        <span><strong>${ev.blocked.p2}</strong>P2</span>
        <span><strong>${ev.blocked.p3}</strong>P3</span>
        <span><strong>${ev.saved}</strong>分钟节省</span>
      </div>
      <ul>${ev.suggestions.map(s => `<li>${s}</li>`).join('')}</ul>
      <div class="doc-link">📎 ${ev.docLink}</div>`;
    return div;
  }

  function renderScoreboard(panelEl, ev) {
    const sb = panelEl.querySelector('[data-scoreboard]');
    const dims = window.FG.dims;
    const c = ev.classify;
    const colorMap = { P0: 'var(--sim-p0)', P1: 'var(--sim-p1)', P2: 'var(--sim-p2)', P3: 'var(--sim-p3)' };
    sb.innerHTML = `
      ${dims.map((d, i) => {
        const v = c['D' + (i + 1)];
        return `<div class="score-row"><span class="lbl">${d.code} ${d.name.slice(0, 2)}</span><span class="bar"><i style="width:${(v*100).toFixed(0)}%"></i></span><span class="v">${v.toFixed(2)}</span></div>`;
      }).join('')}
      <div class="verdict" style="background:${colorMap[c.level]}">→ ${c.level} · ${(c.score * 100).toFixed(0)}</div>
      <div class="reason">${c.reason}</div>`;
  }

  function highlightChat(rootEl, chatKey) {
    rootEl.querySelectorAll('.chat-item').forEach(el => {
      el.classList.toggle('has-unread', el.dataset.chat === chatKey);
    });
  }

  function mount(rootEl, opts = {}) {
    const theme = opts.theme || 'light';
    injectStyle(theme);
    buildLayout(rootEl, theme);
    const stream = rootEl.querySelector('[data-stream]');
    const panel = rootEl.querySelector('[data-panel]');
    const stateBadge = rootEl.querySelector('[data-state]');
    const progressEl = rootEl.querySelector('[data-progress]');
    const clockEl = rootEl.querySelector('[data-clock]');
    const cnt = { P0: 0, P1: 0, P2: 0, P3: 0 };

    const totalDuration = SCRIPT[SCRIPT.length - 1].t + 4;
    let cursor = 0;
    let startTs = 0;
    let elapsed = 0;
    let raf = null;
    let playing = false;

    function reset() {
      stream.innerHTML = '';
      cnt.P0 = cnt.P1 = cnt.P2 = cnt.P3 = 0;
      ['P0','P1','P2','P3'].forEach(k => rootEl.querySelector(`[data-cnt="${k}"]`).textContent = '0');
      cursor = 0;
      elapsed = 0;
      startTs = 0;
      stateBadge.innerHTML = '<span class="dot"></span>SHIELD READY';
      stateBadge.style.background = 'var(--sim-blue)';
      panel.querySelector('[data-scoreboard]').innerHTML = '<div style="font-size:11px;color:var(--sim-fg3);font-style:italic">等待消息进入...</div>';
      progressEl.style.width = '0%';
      clockEl.textContent = '0.0s';
    }

    function processEvent(ev) {
      if (ev.type === 'system') {
        if (ev.text.includes('开始专注')) {
          stream.appendChild(makeSystemLine('🛡️ ' + ev.text));
          stateBadge.innerHTML = '<span class="dot"></span>SHIELD ACTIVE';
          stateBadge.style.background = '#10b981';
        } else if (ev.text.includes('结束')) {
          stream.appendChild(makeSystemLine('🌊 ' + ev.text));
          stateBadge.innerHTML = '<span class="dot"></span>RECOVERING';
          stateBadge.style.background = 'var(--sim-blue)';
        } else {
          stream.appendChild(makeSystemLine(ev.text));
        }
      } else if (ev.type === 'message') {
        highlightChat(rootEl, ev.chat);
        stream.appendChild(makeMsgEl(ev));
        renderScoreboard(panel, ev);
        const lvl = ev.classify.level;
        cnt[lvl] = (cnt[lvl] || 0) + 1;
        rootEl.querySelector(`[data-cnt="${lvl}"]`).textContent = cnt[lvl];
        if (ev.action === 'forward_urgent') stream.appendChild(makeUrgentCard(ev));
        if (ev.action === 'auto_reply' && ev.autoReply) {
          setTimeout(() => {
            stream.appendChild(makeBotReply(ev, ev.autoReply));
            stream.scrollTop = stream.scrollHeight;
          }, 400);
        }
      } else if (ev.type === 'recovery') {
        stream.appendChild(makeRecovery(ev));
        stateBadge.innerHTML = '<span class="dot"></span>FOCUS COMPLETE';
        stateBadge.style.background = '#10b981';
      }
      stream.scrollTop = stream.scrollHeight;
    }

    function tick(now) {
      if (!startTs) startTs = now;
      elapsed = (now - startTs) / 1000;
      while (cursor < SCRIPT.length && SCRIPT[cursor].t <= elapsed) {
        processEvent(SCRIPT[cursor]);
        cursor++;
      }
      progressEl.style.width = Math.min(100, (elapsed / totalDuration) * 100) + '%';
      clockEl.textContent = elapsed.toFixed(1) + 's';
      if (cursor < SCRIPT.length && playing) {
        raf = requestAnimationFrame(tick);
      } else if (cursor >= SCRIPT.length) {
        playing = false;
        rootEl.querySelector('[data-act="play"]').textContent = '✓ 完成';
        progressEl.style.width = '100%';
      }
    }
    function play() {
      if (cursor >= SCRIPT.length) { reset(); }
      playing = true;
      startTs = performance.now() - elapsed * 1000;
      rootEl.querySelector('[data-act="play"]').textContent = '⏸ 暂停';
      raf = requestAnimationFrame(tick);
    }
    function pause() {
      playing = false;
      if (raf) cancelAnimationFrame(raf);
      rootEl.querySelector('[data-act="play"]').textContent = '▶ 继续';
    }
    function step() {
      if (cursor >= SCRIPT.length) return;
      processEvent(SCRIPT[cursor]);
      cursor++;
      elapsed = SCRIPT[cursor]?.t || elapsed + 1;
      progressEl.style.width = Math.min(100, (elapsed / totalDuration) * 100) + '%';
      clockEl.textContent = elapsed.toFixed(1) + 's';
    }

    rootEl.querySelector('[data-act="play"]').onclick = () => { playing ? pause() : play(); };
    rootEl.querySelector('[data-act="step"]').onclick = () => { pause(); step(); };
    rootEl.querySelector('[data-act="replay"]').onclick = () => { pause(); reset(); play(); };

    reset();
    if (opts.autoPlay !== false) {
      // Auto-play when scrolled into view
      const io = new IntersectionObserver(entries => {
        entries.forEach(e => {
          if (e.isIntersecting && cursor === 0 && !playing) {
            setTimeout(() => play(), 400);
            io.disconnect();
          }
        });
      }, { threshold: 0.3 });
      io.observe(rootEl);
    }
    return { play, pause, step, reset };
  }

  window.FG.ChatSim = { mount };
})();
