/* ============================================================================
 * Demo 2 · 6 维分类引擎前端简化版（雷达图 SVG）
 * 暴露 FG.Classifier.mount(rootEl, opts)
 * 算法逻辑同 classification_engine.py 精神，权重一致
 * ========================================================================== */
(function () {
  const STYLE_ID = 'fg-classifier-style';
  const DIMS = window.FG.dims;

  function injectStyle(theme) {
    if (document.getElementById(STYLE_ID)) return;
    const dark = theme === 'dark';
    const css = `
.fg-cls{--c-bg:${dark?'#0c0a09':'#fff'};--c-fg:${dark?'#fafaf9':'#0c0a09'};--c-fg2:${dark?'#a8a29e':'#525252'};--c-fg3:${dark?'#57534e':'#a8a29e'};--c-bd:${dark?'#262220':'#e7e5e4'};--c-soft:${dark?'#1c1917':'#f5f5f4'};--c-blue:#3370FF;--c-p0:#ef4444;--c-p1:#f59e0b;--c-p2:#10b981;--c-p3:#9ca3af;font-family:Inter,-apple-system,'PingFang SC',sans-serif;background:var(--c-bg);color:var(--c-fg);border:1px solid var(--c-bd);border-radius:14px;padding:24px;display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start}
.fg-cls *{box-sizing:border-box}
.fg-cls .input-area{display:flex;flex-direction:column;gap:14px}
.fg-cls label{font-size:11px;color:var(--c-fg3);text-transform:uppercase;letter-spacing:.06em;font-weight:600;margin-bottom:5px;display:block}
.fg-cls input,.fg-cls select{width:100%;background:var(--c-soft);border:1px solid var(--c-bd);color:var(--c-fg);padding:10px 12px;border-radius:7px;font-size:13.5px;font-family:inherit;transition:border-color .15s}
.fg-cls input:focus,.fg-cls select:focus{outline:none;border-color:var(--c-blue)}
.fg-cls input{font-family:'JetBrains Mono',monospace;font-size:12.5px}
.fg-cls .row-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.fg-cls .examples{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.fg-cls .examples button{background:transparent;border:1px solid var(--c-bd);color:var(--c-fg2);padding:5px 11px;border-radius:14px;cursor:pointer;font-size:11.5px;transition:all .15s}
.fg-cls .examples button:hover{border-color:var(--c-blue);color:var(--c-blue)}
.fg-cls .out-area{background:var(--c-soft);border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:14px;min-height:340px}
.fg-cls .verdict{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-radius:8px;color:#fff;font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600}
.fg-cls .verdict .lvl{font-size:22px;letter-spacing:.05em}
.fg-cls .verdict .score{font-size:13px;opacity:.9}
.fg-cls .radar-wrap{display:flex;align-items:center;justify-content:center;padding:6px 0}
.fg-cls .radar-wrap svg{width:100%;max-width:280px;height:auto}
.fg-cls .breakdown{display:flex;flex-direction:column;gap:5px}
.fg-cls .br-row{display:flex;align-items:center;gap:8px;font-family:'JetBrains Mono',monospace;font-size:11.5px}
.fg-cls .br-row .lbl{width:74px;color:var(--c-fg2);font-size:11px}
.fg-cls .br-row .bar{flex:1;height:5px;background:var(--c-bd);border-radius:3px;overflow:hidden}
.fg-cls .br-row .bar i{display:block;height:100%;background:var(--c-blue);transition:width .4s ease}
.fg-cls .br-row .v{width:32px;text-align:right;color:var(--c-fg)}
.fg-cls .reason{font-size:12.5px;color:var(--c-fg2);line-height:1.65;padding:8px 10px;background:var(--c-bg);border-radius:6px;border-left:3px solid var(--c-blue)}
.fg-cls .footnote{font-size:10.5px;color:var(--c-fg3);font-style:italic;margin-top:4px;line-height:1.5}
@media(max-width:760px){.fg-cls{grid-template-columns:1fr}}
`;
    const el = document.createElement('style');
    el.id = STYLE_ID;
    el.textContent = css;
    document.head.appendChild(el);
  }

  // 简化版分类（核心同 classification_engine.py，权重 0.25/0.15/0.25/0.15/0.10/0.10）
  function classify({ text, sender, chat, task }) {
    const D1 = { boss: 1.0, vip: 0.85, colleague: 0.55, stranger: 0.18, bot: 0.05 }[sender] || 0.5;
    const D2 = { boss: 0.85, vip: 0.7, colleague: 0.5, stranger: 0.15, bot: 0.1 }[sender] || 0.4;
    let D3 = 0.3;
    if (/(故障|紧急|马上|严重|宕机|事故|down|error|critical|urgent|asap)/i.test(text)) D3 = 0.95;
    else if (/(请教|确认|意见|方案|讨论|review|approval)/i.test(text)) D3 = 0.65;
    else if (/(吃啥|周末|哈哈|表情|拼车|聚餐|emoji|🎉|❤️|👍)/i.test(text)) D3 = 0.1;
    else if (/(\?|？|怎么|如何|how|what|why)/i.test(text)) D3 = 0.45;
    let D4 = 0.3;
    if (task && task.length > 0) {
      const taskKws = task.split(/[\s,，·、]+/).filter(s => s.length > 0);
      const hits = taskKws.filter(kw => text.includes(kw)).length;
      if (hits > 0) D4 = Math.min(1.0, 0.4 + hits * 0.25);
    }
    let D5 = 0.3;
    if (/(今天|马上|deadline|尽快|立刻|tonight|today|now|asap)/i.test(text)) D5 = 0.9;
    else if (/(明天|本周|下周|tomorrow|this week)/i.test(text)) D5 = 0.55;
    const D6 = chat === 'p2p' ? 0.85 : chat === 'small' ? 0.55 : chat === 'large' ? 0.2 : 0.4;
    const score = D1 * 0.25 + D2 * 0.15 + D3 * 0.25 + D4 * 0.15 + D5 * 0.10 + D6 * 0.10;
    const level = score >= 0.72 ? 'P0' : score >= 0.45 ? 'P1' : score >= 0.25 ? 'P2' : 'P3';
    const action = { P0: '立即推送加急卡片', P1: '专注结束后摘要', P2: '智能代回复 (带 🤖 标识)', P3: '静默归档' }[level];
    let reason = [];
    if (D1 >= 0.85) reason.push('发送方为白名单 / 上级');
    if (D3 >= 0.9) reason.push('内容含紧急关键词');
    if (D5 >= 0.85) reason.push('时间敏感强');
    if (D6 >= 0.8) reason.push('私聊 / 直达频道');
    if (D3 <= 0.15) reason.push('内容为闲聊');
    if (D6 <= 0.25) reason.push('大群广播');
    if (reason.length === 0) reason.push('综合 6 维特征加权');
    return {
      score, level, action, reason: reason.join(' · '),
      dims: [D1, D2, D3, D4, D5, D6],
      isBoundary: Math.abs(score - 0.45) < 0.05 || Math.abs(score - 0.72) < 0.05 || Math.abs(score - 0.25) < 0.05,
    };
  }

  function radarSVG(values, theme) {
    const dark = theme === 'dark';
    const cx = 140, cy = 140, R = 100;
    const n = values.length;
    const angle = i => -Math.PI / 2 + (Math.PI * 2 * i) / n;
    const point = (i, r) => [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r];
    let grid = '';
    [0.25, 0.5, 0.75, 1].forEach(scale => {
      const pts = values.map((_, i) => point(i, R * scale).join(',')).join(' ');
      grid += `<polygon points="${pts}" fill="none" stroke="${dark?'#3a3735':'#e5e5e5'}" stroke-width="1"/>`;
    });
    let axes = '';
    DIMS.forEach((d, i) => {
      const [x, y] = point(i, R);
      axes += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${dark?'#3a3735':'#e5e5e5'}" stroke-width="1"/>`;
      const [lx, ly] = point(i, R + 18);
      axes += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="${dark?'#a8a29e':'#525252'}" font-family="Inter">${d.name}</text>`;
    });
    const valuePts = values.map((v, i) => point(i, R * v).join(',')).join(' ');
    return `
<svg viewBox="0 0 280 280" xmlns="http://www.w3.org/2000/svg" aria-label="6 维雷达图">
  ${grid}
  ${axes}
  <polygon points="${valuePts}" fill="rgba(51,112,255,.18)" stroke="#3370FF" stroke-width="2"/>
  ${values.map((v, i) => { const [x, y] = point(i, R * v); return `<circle cx="${x}" cy="${y}" r="3.5" fill="#3370FF"/>`; }).join('')}
</svg>`;
  }

  const EXAMPLES = [
    { label: '老板紧急',     data: { text: '今晚 8 点能开个 30 分钟的会吗',     sender: 'boss',      chat: 'p2p',   task: 'Q3 方案' } },
    { label: '运维告警',     data: { text: '数据库主库 5xx 错误率 12% 紧急处理', sender: 'colleague', chat: 'small', task: '专注开发' } },
    { label: '同事请教',     data: { text: '这个 Q3 方案给个意见',                sender: 'colleague', chat: 'small', task: 'Q3 方案' } },
    { label: '大群闲聊',     data: { text: '中午吃啥呀大家',                       sender: 'colleague', chat: 'large', task: '专注开发' } },
    { label: 'Bot 推送',     data: { text: '【日报】昨日活跃用户 12,394',          sender: 'bot',       chat: 'large', task: '专注开发' } },
    { label: '陌生人请求',   data: { text: '能加个微信吗',                         sender: 'stranger',  chat: 'p2p',   task: 'Q3 方案' } },
  ];

  function mount(rootEl, opts = {}) {
    const theme = opts.theme || 'light';
    injectStyle(theme);
    rootEl.classList.add('fg-cls');
    rootEl.innerHTML = `
<div class="input-area">
  <div>
    <label>消息内容</label>
    <input type="text" data-text value="今晚 8 点能开个 30 分钟的会吗" placeholder="试试输入一条消息..." />
  </div>
  <div class="row-grid">
    <div>
      <label>发送方身份</label>
      <select data-sender>
        <option value="boss">上级 / 老板</option>
        <option value="vip">重要客户</option>
        <option value="colleague">同事</option>
        <option value="stranger">陌生人</option>
        <option value="bot">机器人</option>
      </select>
    </div>
    <div>
      <label>频道</label>
      <select data-chat>
        <option value="p2p">私聊</option>
        <option value="small">小群 (≤10)</option>
        <option value="large">大群 (>50)</option>
      </select>
    </div>
  </div>
  <div>
    <label>当前任务上下文</label>
    <input type="text" data-task value="Q3 方案" placeholder="比如：专注开发、Q3 方案..." />
  </div>
  <div>
    <label>预设示例</label>
    <div class="examples" data-examples>
      ${EXAMPLES.map((e, i) => `<button data-ex="${i}">${e.label}</button>`).join('')}
    </div>
  </div>
  <div class="footnote">这是前端运行的 6 维加权简化版（与生产环境算法权重一致）。生产路径在边界（±0.05）会触发 LLM 仲裁。</div>
</div>
<div class="out-area">
  <div class="verdict" data-verdict><span class="lvl">—</span><span class="score">score: —</span></div>
  <div class="radar-wrap" data-radar></div>
  <div class="breakdown" data-breakdown></div>
  <div class="reason" data-reason>—</div>
</div>`;

    function render() {
      const text = rootEl.querySelector('[data-text]').value;
      const sender = rootEl.querySelector('[data-sender]').value;
      const chat = rootEl.querySelector('[data-chat]').value;
      const task = rootEl.querySelector('[data-task]').value;
      const r = classify({ text, sender, chat, task });
      const colorMap = { P0: '#ef4444', P1: '#f59e0b', P2: '#10b981', P3: '#9ca3af' };
      const v = rootEl.querySelector('[data-verdict]');
      v.style.background = colorMap[r.level];
      v.innerHTML = `<span class="lvl">${r.level}</span><span class="score">score: ${r.score.toFixed(3)}${r.isBoundary ? ' · ⚖ LLM 仲裁' : ''}</span>`;
      rootEl.querySelector('[data-radar]').innerHTML = radarSVG(r.dims, theme);
      rootEl.querySelector('[data-breakdown]').innerHTML = DIMS.map((d, i) => {
        const val = r.dims[i];
        return `<div class="br-row"><span class="lbl">${d.code} ${d.name}</span><span class="bar"><i style="width:${(val*100).toFixed(0)}%"></i></span><span class="v">${val.toFixed(2)}</span></div>`;
      }).join('');
      rootEl.querySelector('[data-reason]').textContent = r.action + ' · ' + r.reason;
    }

    ['[data-text]', '[data-sender]', '[data-chat]', '[data-task]'].forEach(sel => {
      rootEl.querySelector(sel).addEventListener('input', render);
      rootEl.querySelector(sel).addEventListener('change', render);
    });
    rootEl.querySelectorAll('[data-ex]').forEach(btn => {
      btn.addEventListener('click', () => {
        const e = EXAMPLES[+btn.dataset.ex];
        rootEl.querySelector('[data-text]').value = e.data.text;
        rootEl.querySelector('[data-sender]').value = e.data.sender;
        rootEl.querySelector('[data-chat]').value = e.data.chat;
        rootEl.querySelector('[data-task]').value = e.data.task;
        render();
      });
    });
    render();
  }

  window.FG.Classifier = { mount, classify };
})();
