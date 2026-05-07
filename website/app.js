/* Agent-Pilot V2.0 · App.js
 * Theme toggle, scroll reveal, IM simulator, Chat Demo */
(function () {
  'use strict';
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

  /* ====== Theme Toggle ====== */
  function initTheme() {
    const html = document.documentElement;
    const saved = localStorage.getItem('ap-theme');
    if (saved === 'dark') html.setAttribute('data-theme','dark');
    else if (!saved && matchMedia('(prefers-color-scheme:dark)').matches)
      html.setAttribute('data-theme','dark');
    const btn = $('#themeToggle');
    if (!btn) return;
    const setIcon = () => btn.textContent = html.getAttribute('data-theme') === 'dark' ? '\u2600' : '\u263E';
    setIcon();
    btn.addEventListener('click', () => {
      const isDark = html.getAttribute('data-theme') === 'dark';
      if (isDark) { html.removeAttribute('data-theme'); localStorage.setItem('ap-theme','light'); }
      else { html.setAttribute('data-theme','dark'); localStorage.setItem('ap-theme','dark'); }
      setIcon();
    });
  }

  /* ====== Scroll Reveal ====== */
  function initReveal() {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
    $$('.reveal').forEach(el => io.observe(el));
  }

  /* ====== Hero Stats (animated counter) ====== */
  function initStats() {
    const container = $('#heroStats');
    if (!container) return;
    const data = [
      { target: 90, suffix: 's', k: '全链路交付' },
      { target: 6, suffix: '', k: '专业 Agent' },
      { target: 14, suffix: '/14', k: 'PRD 测试通过' },
      { target: 185, suffix: '', k: '源文件' },
    ];
    data.forEach(d => {
      const el = document.createElement('div');
      el.className = 'stat';
      const vEl = document.createElement('div');
      vEl.className = 'v';
      vEl.textContent = '0' + d.suffix;
      el.appendChild(vEl);
      const kEl = document.createElement('div');
      kEl.className = 'k';
      kEl.textContent = d.k;
      el.appendChild(kEl);
      container.appendChild(el);
      animateCounter(vEl, d.target, d.suffix);
    });
  }

  function animateCounter(el, target, suffix) {
    let current = 0;
    const step = Math.max(1, Math.floor(target / 30));
    const interval = setInterval(() => {
      current += step;
      if (current >= target) { current = target; clearInterval(interval); }
      el.textContent = current + suffix;
    }, 40);
  }

  /* ====== IM Simulator ====== */
  const SIM_SCRIPT = [
    { type: 'user', text: '帮我写一份 AI Agent 多端协同方案' },
    { type: 'agent', text: '[IntentAgent] 识别意图: doc | 任务类型: 文档生成' },
    { type: 'agent', text: '[PlannerAgent] 生成 7 章结构化大纲...' },
    { type: 'agent', text: '[ResearchAgent] MiniMax tool calling 联网搜索中...' },
    { type: 'agent', text: '[ResearchAgent] 获取 12 条搜索结果，整理为结构化报告' },
    { type: 'agent', text: '[WriterAgent] 按章节撰写，融合搜索数据...' },
    { type: 'agent', text: '[ReviewAgent] 5 维度评估 → PASS (数据:4/5 结构:5/5 引用:4/5)' },
    { type: 'agent', text: '[BuilderAgent] 写入飞书文档，生成分享链接' },
    { type: 'bot', text: '任务完成！文档已生成（5646 字），耗时 92 秒。' },
  ];

  function initSimulator() {
    const stream = $('#simStream');
    const badge = $('#simStateBadge');
    const progress = $('#simProgress');
    const label = $('#simLabel');
    const playBtn = $('#simPlay');
    const stepBtn = $('#simStep');
    const resetBtn = $('#simReset');
    if (!stream) return;

    let idx = 0;
    let timer = null;
    let playing = false;

    function addMsg(item) {
      const el = document.createElement('div');
      el.className = 'sim-msg ' + item.type;
      el.textContent = item.text;
      stream.appendChild(el);
      stream.scrollTop = stream.scrollHeight;
      if (item.type === 'agent') {
        badge.textContent = item.text.match(/\[(.*?)\]/)?.[1] || 'WORKING';
      } else if (item.type === 'bot') {
        badge.textContent = 'DONE';
      }
    }

    function update() {
      if (progress) progress.style.width = ((idx / SIM_SCRIPT.length) * 100) + '%';
      if (label) label.textContent = `${idx} / ${SIM_SCRIPT.length}`;
    }

    function step() {
      if (idx >= SIM_SCRIPT.length) { stop(); return; }
      addMsg(SIM_SCRIPT[idx]);
      idx++;
      update();
    }

    function play() {
      if (playing) return;
      playing = true;
      if (playBtn) playBtn.textContent = '\u23F8';
      timer = setInterval(() => {
        if (idx >= SIM_SCRIPT.length) { stop(); return; }
        step();
      }, 1200);
    }

    function stop() {
      playing = false;
      if (playBtn) playBtn.textContent = '\u25B6';
      clearInterval(timer);
    }

    function reset() {
      stop();
      idx = 0;
      stream.innerHTML = '';
      badge.textContent = 'READY';
      update();
    }

    if (playBtn) playBtn.addEventListener('click', () => playing ? stop() : play());
    if (stepBtn) stepBtn.addEventListener('click', step);
    if (resetBtn) resetBtn.addEventListener('click', reset);
    update();
    setTimeout(play, 1500);
  }

  /* ====== Chat Demo ====== */
  function initChat() {
    const messages = $('#chatMessages');
    const input = $('#chatInput');
    const sendBtn = $('#chatSend');
    const suggests = $$('.suggest-btn');
    if (!messages || !input) return;

    function addChatMsg(text, isUser) {
      const msg = document.createElement('div');
      msg.className = 'msg ' + (isUser ? 'user' : 'bot');
      msg.innerHTML = `
        <div class="msg-avatar">${isUser ? '\uD83D\uDC64' : '\uD83E\uDD16'}</div>
        <div class="msg-content"><p>${text}</p></div>
      `;
      messages.appendChild(msg);
      messages.scrollTop = messages.scrollHeight;
    }

    function simulateResponse(userText) {
      addChatMsg(userText, true);
      setTimeout(() => {
        addChatMsg('收到！正在启动 Multi-Agent Pipeline...', false);
      }, 500);
      setTimeout(() => {
        const steps = [
          '[IntentAgent] 意图识别完成',
          '[PlannerAgent] 大纲规划中...',
          '[ResearchAgent] 联网搜索中...',
        ];
        const content = steps.map(s => `<span class="agent-step">${s}</span>`).join('');
        addChatMsg(`Pipeline 进行中...<div class="agent-step">${steps.join('<br>')}</div>`, false);
      }, 1500);
      setTimeout(() => {
        addChatMsg('任务已提交到服务器！您可以在 <a href="/dashboard" style="color:var(--accent)">Dashboard</a> 实时查看 Agent 协作进度。<br><br>或者在飞书 IM 中发送同样的指令，体验完整的交付流程。', false);
      }, 3000);
    }

    function send() {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      simulateResponse(text);
    }

    if (sendBtn) sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
    suggests.forEach(btn => {
      btn.addEventListener('click', () => {
        const msg = btn.getAttribute('data-msg');
        if (msg) simulateResponse(msg);
      });
    });
  }

  /* ====== Init ====== */
  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initReveal();
    initStats();
    initSimulator();
    initChat();
  });
})();
