/* ============================================================================
 * 6 张高保真飞书 UI mock · 用 HTML+CSS 直接在浏览器里渲染
 * 这种做法比 PNG 截图清晰、轻量、可缩放、暗色模式自适应
 * 暴露 FG.Screens.render(name, theme) → HTMLElement
 * ========================================================================== */
(function () {
  const STYLE_ID = 'fg-screens-style';

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
.fg-shot{font-family:Inter,-apple-system,'PingFang SC',sans-serif;border-radius:12px;overflow:hidden;border:1px solid var(--shot-bd,#e7e5e4);background:var(--shot-bg,#fff);width:100%;max-width:520px;box-shadow:0 16px 48px rgba(0,0,0,.08);position:relative}
.fg-shot.dark{--shot-bg:#1c1917;--shot-bd:#262220;color:#fafaf9}
.fg-shot *{box-sizing:border-box}
.fg-shot .topbar{background:#3370FF;color:#fff;padding:8px 14px;display:flex;align-items:center;gap:8px;font-size:12px}
.fg-shot .topbar .feishu-logo{width:18px;height:18px;border-radius:4px;background:#fff;color:#3370FF;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:11px}
.fg-shot .topbar .title{flex:1;font-weight:500}
.fg-shot .topbar .right{font-size:10px;opacity:.85}
.fg-shot .body{padding:18px}
/* P0 加急卡 */
.fg-shot.p0 .card{border:2px solid #ef4444;border-radius:8px;padding:14px;background:#fff;color:#0c0a09}
.fg-shot.p0.dark .card{background:#3a1a1a;color:#fff}
.fg-shot.p0 .card-h{display:flex;align-items:center;gap:6px;color:#ef4444;font-weight:600;font-size:11px;letter-spacing:.06em;margin-bottom:8px}
.fg-shot.p0 .card-h .ping{width:8px;height:8px;border-radius:50%;background:#ef4444;animation:fg-shot-ping 1.5s infinite}
@keyframes fg-shot-ping{0%,100%{opacity:1}50%{opacity:.3}}
.fg-shot.p0 .from{font-size:13px;font-weight:600;margin-bottom:4px}
.fg-shot.p0 .from .chat{color:#525252;font-weight:400;font-size:11.5px;margin-left:6px}
.fg-shot.p0 .content{font-size:14px;line-height:1.6;margin:8px 0;padding:8px 11px;background:#fef2f2;border-radius:6px;color:#7f1d1d;font-weight:500}
.fg-shot.p0.dark .content{background:#7f1d1d33;color:#fecaca}
.fg-shot.p0 .scoring{display:flex;gap:6px;margin:8px 0}
.fg-shot.p0 .pill{padding:2px 8px;border-radius:10px;font-size:10px;font-family:'JetBrains Mono',monospace;background:#fef2f2;color:#991b1b}
.fg-shot.p0.dark .pill{background:#7f1d1d;color:#fecaca}
.fg-shot.p0 .actions{display:flex;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid #fee2e2}
.fg-shot.p0 .btn{flex:1;padding:7px;font-size:12px;border-radius:6px;background:#ef4444;color:#fff;text-align:center;font-weight:500;border:0}
.fg-shot.p0 .btn.ghost{background:transparent;color:#525252;border:1px solid #e5e5e5}

/* Recovery Card */
.fg-shot.recovery .card{border:1px solid #3370FF;border-radius:8px;padding:16px;background:#eff6ff;color:#0c0a09}
.fg-shot.recovery.dark .card{background:#1a2740;color:#fff}
.fg-shot.recovery .h{font-size:14px;font-weight:600;color:#3370FF;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.fg-shot.recovery .stats{display:flex;gap:12px;margin-bottom:12px;font-size:11px;color:#525252}
.fg-shot.recovery.dark .stats{color:#a8a29e}
.fg-shot.recovery .stats span strong{display:block;font-size:18px;font-family:'JetBrains Mono',monospace;color:#0c0a09;font-weight:700}
.fg-shot.recovery.dark .stats span strong{color:#fafaf9}
.fg-shot.recovery .sub{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#525252;margin:6px 0;font-weight:600}
.fg-shot.recovery.dark .sub{color:#a8a29e}
.fg-shot.recovery ul{margin:0;padding:0;list-style:none}
.fg-shot.recovery li{padding:6px 10px;background:#fff;margin:5px 0;border-radius:5px;font-size:12.5px;display:flex;gap:6px;border-left:2.5px solid #3370FF}
.fg-shot.recovery.dark li{background:#0c0a09}
.fg-shot.recovery .doc{margin-top:10px;font-size:10.5px;color:#525252;font-family:'JetBrains Mono',monospace;padding-top:8px;border-top:1px dashed #c7d7f7}
.fg-shot.recovery.dark .doc{color:#a8a29e;border-top-color:#1a2740}

/* Welcome Card (建工作台) */
.fg-shot.welcome .card{border-radius:8px;padding:18px;background:linear-gradient(135deg,#3370FF 0%,#5b8def 100%);color:#fff}
.fg-shot.welcome .h{font-size:16px;font-weight:700;margin-bottom:8px}
.fg-shot.welcome .sub{font-size:12.5px;opacity:.9;margin-bottom:14px;line-height:1.6}
.fg-shot.welcome .progress{background:rgba(255,255,255,.18);border-radius:8px;padding:12px;margin:10px 0}
.fg-shot.welcome .step{display:flex;align-items:center;gap:8px;padding:6px 0;font-size:12px}
.fg-shot.welcome .step .dot{width:18px;height:18px;border-radius:50%;background:rgba(255,255,255,.3);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0}
.fg-shot.welcome .step.done .dot{background:#10b981}
.fg-shot.welcome .step.cur .dot{background:#fff;color:#3370FF;animation:fg-shot-spin 1.5s linear infinite}
@keyframes fg-shot-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.fg-shot.welcome .step.cur{font-weight:600}
.fg-shot.welcome .links{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.fg-shot.welcome .link-pill{background:rgba(255,255,255,.22);padding:5px 11px;border-radius:6px;font-size:11px;backdrop-filter:blur(4px)}

/* Dashboard 概览 */
.fg-shot.dashboard{max-width:560px}
.fg-shot.dashboard .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}
.fg-shot.dashboard .stat{padding:10px;background:#f5f5f4;border-radius:6px;text-align:left}
.fg-shot.dashboard.dark .stat{background:#0c0a09}
.fg-shot.dashboard .stat .v{font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700;color:#3370FF}
.fg-shot.dashboard .stat .k{font-size:10px;color:#525252;margin-top:2px}
.fg-shot.dashboard.dark .stat .k{color:#a8a29e}
.fg-shot.dashboard .heatmap{display:grid;grid-template-columns:repeat(24,1fr);gap:2px}
.fg-shot.dashboard .heat-cell{aspect-ratio:1;border-radius:2px;background:#f5f5f4}
.fg-shot.dashboard.dark .heat-cell{background:#0c0a09}
.fg-shot.dashboard .heat-h{font-size:10.5px;color:#525252;margin-bottom:6px}
.fg-shot.dashboard.dark .heat-h{color:#a8a29e}

/* Weekly Report */
.fg-shot.weekly .card{padding:16px;background:#fafaf9;border-radius:8px;color:#0c0a09}
.fg-shot.weekly.dark .card{background:#0c0a09;color:#fff}
.fg-shot.weekly .h{font-size:15px;font-weight:700;margin-bottom:4px}
.fg-shot.weekly .sub{font-size:11px;color:#525252;margin-bottom:14px}
.fg-shot.weekly.dark .sub{color:#a8a29e}
.fg-shot.weekly .section{margin:10px 0}
.fg-shot.weekly .section-h{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:#525252;margin-bottom:6px;font-weight:600}
.fg-shot.weekly.dark .section-h{color:#a8a29e}
.fg-shot.weekly .bar-row{display:flex;align-items:center;gap:6px;margin:4px 0;font-size:11.5px}
.fg-shot.weekly .bar-row .lbl{width:48px;color:#525252}
.fg-shot.weekly.dark .bar-row .lbl{color:#a8a29e}
.fg-shot.weekly .bar-row .bar{flex:1;height:8px;border-radius:4px;background:#f5f5f4}
.fg-shot.weekly.dark .bar-row .bar{background:#262220}
.fg-shot.weekly .bar-row .bar i{display:block;height:100%;border-radius:4px}
.fg-shot.weekly .bar-row .v{font-family:'JetBrains Mono',monospace;font-size:11px;width:32px;text-align:right}
.fg-shot.weekly p{font-size:12px;line-height:1.7;margin:6px 0;color:#525252}
.fg-shot.weekly.dark p{color:#d6d3d1}

/* Cursor + MCP */
.fg-shot.cursor{background:#1e1e1e;color:#d4d4d4;font-family:'JetBrains Mono',monospace}
.fg-shot.cursor .topbar{background:#0e0e0e;color:#888;font-family:Inter,sans-serif}
.fg-shot.cursor .topbar .feishu-logo{background:#3370FF;color:#fff}
.fg-shot.cursor .body{padding:0;font-size:11.5px}
.fg-shot.cursor .pane-h{padding:6px 12px;background:#252525;color:#888;font-size:10.5px;border-bottom:1px solid #333}
.fg-shot.cursor .chat-block{padding:10px 14px;border-bottom:1px solid #2a2a2a}
.fg-shot.cursor .role-user{color:#7dd3fc;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.fg-shot.cursor .role-asst{color:#86efac;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.fg-shot.cursor .text{font-size:12px;line-height:1.6;color:#d4d4d4;font-family:Inter,sans-serif}
.fg-shot.cursor .tool-call{margin:8px 0;padding:8px 12px;background:#0e0e0e;border-left:3px solid #3370FF;border-radius:0 6px 6px 0;font-size:11px}
.fg-shot.cursor .tool-call .name{color:#7dd3fc;font-weight:500;margin-bottom:2px}
.fg-shot.cursor .tool-call .args{color:#86efac;white-space:pre-wrap}
.fg-shot.cursor .tool-call .resp{color:#fcd34d;margin-top:4px;white-space:pre-wrap}
`;
    const el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = css;
    document.head.appendChild(el);
  }

  const screens = {
    p0: () => `
<div class="topbar">
  <div class="feishu-logo">L</div>
  <div class="title">飞书 · 加急通知</div>
  <div class="right">14:32</div>
</div>
<div class="body">
  <div class="card">
    <div class="card-h"><span class="ping"></span>P0 BREAK_IN · LarkMentor 加急推送</div>
    <div class="from">陈总<span class="chat">· 私聊</span></div>
    <div class="content">"今晚 8 点能开个 30 分钟的会吗"</div>
    <div class="scoring">
      <span class="pill">D1 身份 1.00</span>
      <span class="pill">D5 时间 0.85</span>
      <span class="pill">score 0.81</span>
    </div>
    <div style="font-size:10.5px;color:#991b1b;font-family:'JetBrains Mono',monospace">why → 白名单 (上级) + 时间敏感强</div>
    <div class="actions">
      <button class="btn">立即查看</button>
      <button class="btn ghost">10 分钟后再提醒</button>
    </div>
  </div>
</div>`,

    recovery: () => `
<div class="topbar">
  <div class="feishu-logo">L</div>
  <div class="title">飞书 · LarkMentor</div>
  <div class="right">15:02</div>
</div>
<div class="body">
  <div class="card">
    <div class="h">🌊 上下文恢复 · 你刚才被守护了 30 分钟</div>
    <div class="stats">
      <span><strong>2</strong>P0</span>
      <span><strong>1</strong>P1</span>
      <span><strong>1</strong>P2</span>
      <span><strong>1</strong>P3</span>
      <span><strong>27</strong>分钟节省</span>
    </div>
    <div class="sub">下一步建议</div>
    <ul>
      <li>🔴 立刻回陈总：8 点会议确认或改约</li>
      <li>🔴 跟进运维 5xx 告警是否已解决</li>
      <li>🟠 张三 Q3 方案：先看一遍再回，预计 15 分钟</li>
      <li>🟢 王五的周报模板已自动回复，完成</li>
    </ul>
    <div class="doc">📎 已写入飞书云文档「LarkMentor 上下文恢复卡片」</div>
  </div>
</div>`,

    welcome: () => `
<div class="topbar">
  <div class="feishu-logo">L</div>
  <div class="title">飞书 · 欢迎使用 LarkMentor</div>
  <div class="right">10:00</div>
</div>
<div class="body">
  <div class="card">
    <div class="h">👋 欢迎，正在为你创建专属工作台...</div>
    <div class="sub">30 秒内你将拥有一套属于自己的 LarkMentor 工作台</div>
    <div class="progress">
      <div class="step done"><span class="dot">✓</span><span>识别新用户身份</span></div>
      <div class="step done"><span class="dot">✓</span><span>创建多维表格「打断分析看板」</span></div>
      <div class="step cur"><span class="dot">⟳</span><span>创建飞书云文档「上手指南 + 恢复卡片」</span></div>
      <div class="step"><span class="dot">○</span><span>预填演示数据 · 6 行</span></div>
    </div>
    <div class="links">
      <span class="link-pill">📊 多维表格</span>
      <span class="link-pill">📝 上手指南</span>
      <span class="link-pill">🔁 恢复卡片</span>
    </div>
  </div>
</div>`,

    dashboard: () => {
      const heatColors = ['#f5f5f4', '#ddebff', '#9ec4ff', '#5b8def', '#3370FF'];
      let cells = '';
      for (let h = 0; h < 24; h++) {
        const v = Math.min(4, Math.round(Math.abs(Math.sin(h / 3.5)) * 4 + (h > 8 && h < 19 ? 1 : 0)));
        cells += `<div class="heat-cell" style="background:${heatColors[v]}"></div>`;
      }
      return `
<div class="topbar">
  <div class="feishu-logo">L</div>
  <div class="title">LarkMentor Dashboard · Live</div>
  <div class="right">● 在线 · 7×24</div>
</div>
<div class="body">
  <div class="grid">
    <div class="stat"><div class="v">2,847</div><div class="k">本周处理</div></div>
    <div class="stat"><div class="v">99%</div><div class="k">分类准确</div></div>
    <div class="stat"><div class="v">11.4%</div><div class="k">LLM 仲裁</div></div>
    <div class="stat"><div class="v">0</div><div class="k">关键漏报</div></div>
  </div>
  <div class="heat-h">今日 24 小时打断热力</div>
  <div class="heatmap">${cells}</div>
  <div style="margin-top:10px;font-size:10.5px;color:#a8a29e;font-family:'JetBrains Mono',monospace">数字基于 102 YAML 测试集 · 灰测启动后将切换为真实数据</div>
</div>`;
    },

    weekly: () => `
<div class="topbar">
  <div class="feishu-logo">L</div>
  <div class="title">本周周报 · LarkMentor 自动生成</div>
  <div class="right">📎 飞书 docx</div>
</div>
<div class="body">
  <div class="card">
    <div class="h">📅 本周（4/14 - 4/20）专注力周报</div>
    <div class="sub">由 LarkMentor FlowMemory 自动汇总 · 已写入飞书 docx</div>
    <div class="section">
      <div class="section-h">优先级分布</div>
      <div class="bar-row"><span class="lbl">P0</span><span class="bar"><i style="width:8%;background:#ef4444"></i></span><span class="v">8%</span></div>
      <div class="bar-row"><span class="lbl">P1</span><span class="bar"><i style="width:18%;background:#f59e0b"></i></span><span class="v">18%</span></div>
      <div class="bar-row"><span class="lbl">P2</span><span class="bar"><i style="width:24%;background:#10b981"></i></span><span class="v">24%</span></div>
      <div class="bar-row"><span class="lbl">P3</span><span class="bar"><i style="width:50%;background:#9ca3af"></i></span><span class="v">50%</span></div>
    </div>
    <div class="section">
      <div class="section-h">本周三句话</div>
      <p>📌 主线工作 Q3 方案推进至 70%，被打断 12 次，LarkMentor 拦截 9 次。</p>
      <p>⚡ 2 次 P0 真紧急（陈总临时会、运维告警），其余群消息均被合理分流。</p>
      <p>🌊 平均每次中断恢复用时 <strong>32 秒</strong>（基线 23 分钟），节省约 4 小时。</p>
    </div>
  </div>
</div>`,

    cursor: () => `
<div class="topbar">
  <div class="feishu-logo">⌘</div>
  <div class="title">Cursor · MCP Connected to LarkMentor</div>
  <div class="right">● flowguard@118.178.242.26</div>
</div>
<div class="body">
  <div class="pane-h">CHAT</div>
  <div class="chat-block">
    <div class="role-user">USER</div>
    <div class="text">我现在在专注吗？还有多少时间？</div>
  </div>
  <div class="chat-block">
    <div class="role-asst">ASSISTANT</div>
    <div class="text">让我查询 LarkMentor 的状态…</div>
    <div class="tool-call">
      <div class="name">→ flowguard.get_focus_status</div>
      <div class="args">{ "open_id": "ou_demo" }</div>
      <div class="resp">← { "focusing": true, "duration_min": 47, "pending_count": 3 }</div>
    </div>
    <div class="text">你正在专注，已持续 47 分钟，还有 43 分钟。期间积压了 3 条 P1 消息，结束专注后会汇总给你。</div>
  </div>
</div>`,
  };

  function render(name, theme = 'light') {
    injectStyle();
    const el = document.createElement('div');
    el.className = 'fg-shot ' + name + (theme === 'dark' ? ' dark' : '');
    el.innerHTML = (screens[name] || (() => '<div class="body">unknown</div>'))();
    return el;
  }

  function list() { return Object.keys(screens); }

  window.FG.Screens = { render, list };
})();
