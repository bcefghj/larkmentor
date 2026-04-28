/* ============================================================================
 * LarkMentor v-c · App
 * 数据 + 渲染 + 动画 + 交互
 * 不依赖任何外部 JS 库
 * ========================================================================== */
(function () {
  'use strict';
  const $  = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
  const h  = (tag, attrs={}, children=[]) => {
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([k,v]) => {
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    });
    (Array.isArray(children) ? children : [children]).forEach(c => {
      if (c == null) return;
      if (typeof c === 'string') el.appendChild(document.createTextNode(c));
      else el.appendChild(c);
    });
    return el;
  };

  /* ====== Theme toggle ====== */
  function initTheme() {
    const html = document.documentElement;
    const saved = localStorage.getItem('lm-theme');
    if (saved === 'dark') html.setAttribute('data-theme','dark');
    else if (!saved && matchMedia('(prefers-color-scheme:dark)').matches)
      html.setAttribute('data-theme','dark');
    const btn = $('#themeToggle');
    if (!btn) return;
    const setIcon = () => btn.textContent =
      html.getAttribute('data-theme') === 'dark' ? '☀' : '☾';
    setIcon();
    btn.addEventListener('click', () => {
      const isDark = html.getAttribute('data-theme') === 'dark';
      if (isDark) { html.removeAttribute('data-theme'); localStorage.setItem('lm-theme','light'); }
      else { html.setAttribute('data-theme','dark'); localStorage.setItem('lm-theme','dark'); }
      setIcon();
    });
  }

  /* ====== Reveal on scroll ====== */
  function initReveal() {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
    $$('.reveal').forEach(el => io.observe(el));
  }

  /* ====== Hero stats ====== */
  const HERO_STATS = [
    { v: '23m15s', k: '一次打断的代价',      note: 'UC Irvine 2008' },
    { v: '~80%',   k: '飞书 IM 消息可延后',  note: '内部样本估计' },
    { v: '8-12m',  k: '新人达全产能耗时',    note: 'SHRM 2023' },
    { v: '14',     k: 'MCP 工具数',          note: '兼容 Claude Code / Cursor' },
    { v: '8 层',   k: '安全栈闸门',          note: 'OWASP LLM Top10 全覆盖' },
    { v: '11k+',   k: '行可跑代码',          note: '119+ pytest passed' }
  ];
  function renderHeroStats() {
    const root = $('#heroStats');
    root.innerHTML = '';
    HERO_STATS.forEach(s => root.appendChild(
      h('div',{class:'stat reveal'},[
        h('div',{class:'v'}, s.v),
        h('div',{class:'k'}, s.k),
        h('div',{class:'n'}, s.note),
      ])
    ));
  }

  /* ====== IM Simulator ====== */
  const SIM_SCRIPT = [
    { kind:'msg', who:'李雷', avtxt:'L', text:'兄弟今天午饭吃啥？团建群投票走起 🍜', shielded:true,
      scores:[15,12,8,5,20,30] },
    { kind:'msg', who:'通知 Bot', avtxt:'B', text:'[CI] master 构建成功 #4231', shielded:true,
      scores:[5,8,40,10,5,15] },
    { kind:'msg', who:'韩梅梅', avtxt:'H', text:'下周一团建报名链接，自愿哦~', shielded:true,
      scores:[10,18,12,8,25,28] },
    { kind:'msg', who:'老板 王总', avtxt:'王', text:'今晚 10 点 P0 上线，你和 @张三 留一下确认下', urgent:true,
      scores:[92,88,90,85,95,72] },
    { kind:'card', ttl:'P0 加急 · 已穿透专注模式', sub:'发件人：王总（直属上级）· 关键词：P0 / 上线 / 留',
      body:'命中 6 维加权 88 分，触发 P0 通道。已为你弹通知；其他 12 条消息维持静音。',
      actions:['查看完整对话','加白名单','回滚此判断'] },
    { kind:'msg', who:'你', avtxt:'U', text:'@王总 收到。', mentor:true,
      scores:[60,80,90,70,40,55] },
    { kind:'card', ttl:'Mentor · 三段重写建议', sub:'NVC 诊断：缺事实 · 缺承接动作 · 偏被动',
      body:'V1（稳）：收到。我现在切到 P0 频道，10 点准时同步部署清单。\nV2（暖）：收到 王总，会全程跟到上线。需要我提前 ping 张三同步吗？\nV3（直）：好。我 9:50 在会议室，先把回滚预案过一遍。',
      actions:['用 V1 发送','用 V2 发送','用 V3 发送'] },
    { kind:'card', ttl:'专注结束 · 上下文恢复卡', sub:'90 分钟内挡掉 12 条消息，3 条已归档',
      body:'你专注期间：\n· 1 条 P0（已弹通知 + Mentor 起草回复）\n· 2 条 P1（已折叠 1 行摘要）\n· 9 条 P2/P3（已归档到飞书 docx）\n\n下一个建议：先回王总，再处理 P1。',
      actions:['打开 docx','一键已读','再开 30 分钟'] },
  ];
  let simState = { idx:0, playing:false, timer:null };
  const SIM_DELAYS = [1100,1100,1000,1300,1700,1300,1900,1900];
  function renderSimStep(i) {
    const stream = $('#simStream');
    if (i === 0) stream.innerHTML = '';
    const s = SIM_SCRIPT[i];
    if (!s) return;
    let node;
    if (s.kind === 'msg') {
      const cls = ['imsim-msg'];
      if (s.shielded) cls.push('shielded');
      if (s.urgent)   cls.push('urgent');
      if (s.mentor)   cls.push('mentor');
      const dims = h('div',{class:'scoreboard'},
        s.scores.map(v => h('div',{},[ h('i',{style:{
          '--w': v + '%',
          width: '0',
          position:'absolute', left:'0', top:'0', height:'100%',
          background: v>=80 ? 'var(--p0)' : (v>=50 ? 'var(--warn)' : 'var(--ok)')
        }}) ]))
      );
      // animate the bars
      setTimeout(() => {
        $$('i', dims).forEach((el,idx) => {
          el.style.width = (s.scores[idx]) + '%';
          el.style.transition = 'width .9s cubic-bezier(.2,.8,.3,1)';
        });
      }, 60);
      node = h('div',{class:cls.join(' ')},[
        h('div',{class:'av'}, s.avtxt),
        h('div',{class:'body'},[
          h('div',{class:'who'}, s.who),
          h('div',{class:'text'}, s.text),
          dims,
        ])
      ]);
    } else { // card
      node = h('div',{class:'imsim-card'},[
        h('div',{class:'ttl'}, s.ttl),
        h('div',{class:'sub'}, s.sub),
        h('div',{class:'body', style:{whiteSpace:'pre-line'}}, s.body),
        h('div',{class:'actions'},
          s.actions.map((a,idx) => h('span',{class: idx===0 ? 'primary' : ''}, a)))
      ]);
    }
    stream.appendChild(node);
    // cap stream height: keep at most 5 last items visible by scroll
    stream.scrollTop = stream.scrollHeight;
    // Update progress + label
    $('#simProgress').style.width = ((i+1)/SIM_SCRIPT.length*100) + '%';
    $('#simLabel').textContent = (i+1) + ' / ' + SIM_SCRIPT.length;
    // Update state badge
    if (s.urgent) $('#simStateBadge').textContent = 'P0 BREAK';
    else if (s.kind==='card' && s.ttl.includes('恢复')) $('#simStateBadge').textContent = 'RECOVER';
    else if (s.kind==='card' && s.ttl.includes('Mentor')) $('#simStateBadge').textContent = 'MENTOR';
    else if (s.shielded) $('#simStateBadge').textContent = 'SHIELDED';
  }
  function simReset() {
    if (simState.timer) clearTimeout(simState.timer);
    simState = { idx:0, playing:false, timer:null };
    $('#simStream').innerHTML = '';
    $('#simProgress').style.width = '0%';
    $('#simLabel').textContent = '0 / ' + SIM_SCRIPT.length;
    $('#simStateBadge').textContent = 'FOCUS';
    $('#simPlay').textContent = '▶';
  }
  function simStep() {
    if (simState.idx >= SIM_SCRIPT.length) {
      simReset();
      simState.playing = true;
      $('#simPlay').textContent = '❚❚';
    }
    renderSimStep(simState.idx);
    simState.idx += 1;
  }
  function simPlay() {
    simState.playing = !simState.playing;
    $('#simPlay').textContent = simState.playing ? '❚❚' : '▶';
    if (simState.playing) loop();
    else if (simState.timer) clearTimeout(simState.timer);
  }
  function loop() {
    if (!simState.playing) return;
    simStep();
    if (simState.idx >= SIM_SCRIPT.length) {
      // pause 2.4s then auto-restart for evaluators
      simState.timer = setTimeout(() => {
        if (!simState.playing) return;
        simReset();
        simState.playing = true;
        $('#simPlay').textContent = '❚❚';
        loop();
      }, 2400);
      return;
    }
    simState.timer = setTimeout(loop, SIM_DELAYS[simState.idx-1] || 1200);
  }
  function initSim() {
    $('#simPlay').addEventListener('click', simPlay);
    $('#simStep').addEventListener('click', () => {
      if (simState.timer) clearTimeout(simState.timer);
      simState.playing = false; $('#simPlay').textContent = '▶';
      simStep();
    });
    $('#simReset').addEventListener('click', simReset);
    simReset();
    // autoplay when in viewport
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting && !simState.playing) {
          simState.playing = true; $('#simPlay').textContent = '❚❚';
          loop();
        }
      });
    }, { threshold: 0.25 });
    io.observe($('#simStream'));
  }

  /* ====== Solution · 4 Mentor Roles ====== */
  const SOLUTIONS = [
    { code:'01', tag:'专业技能', title:'写作 · 任务表达',
      desc:'帮新人把"想清楚但说不出来"的话说出来——三段重写、NVC 诊断、引用组织默契。',
      bullets:['mentor_review_message','3 段不同语气重写','PII 自动脱敏'],
      tool:'mentor_review_message' },
    { code:'02', tag:'工作方法', title:'任务理解 · 拆解',
      desc:'老板甩一句"你跟一下"——Mentor 自动拆 Scope/Deadline/产出/边界，缺哪个反问。',
      bullets:['mentor_clarify_task','缺失维度自动反问','给出 Plan + 风险'],
      tool:'mentor_clarify_task' },
    { code:'03', tag:'团队融入', title:'组织默契 RAG',
      desc:'每人一份 KB，沉淀"这家公司怎么做事"。回答带引用，可追溯。',
      bullets:['mentor_search_org_kb','embedding + BM25 双索引','永久可检索'],
      tool:'mentor_search_org_kb' },
    { code:'04', tag:'成长跟进', title:'周报 · STAR 起草',
      desc:'从 Archival 里抽事实，按 STAR 结构起草周报；带引用、可改可弃。',
      bullets:['mentor_draft_weekly','STAR 结构','含 archival 引用'],
      tool:'mentor_draft_weekly' },
  ];
  function renderSolution() {
    const root = $('#solutionGrid');
    root.innerHTML = '';
    SOLUTIONS.forEach(s => root.appendChild(
      h('div',{class:'sol-card reveal'},[
        h('div',{class:'meta'},[
          h('span',{class:'num'}, 'SKILL ' + s.code),
          h('span',{class:'tag'}, s.tag),
        ]),
        h('h3',{}, s.title),
        h('p',{}, s.desc),
        h('ul',{}, s.bullets.map(b => h('li',{}, b))),
        h('div',{class:'toolname'},[ '对应 MCP 工具：', h('code',{}, s.tool) ]),
      ])
    ));
    // wire reveal for these
    new IntersectionObserver((entries, o) => {
      entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); o.unobserve(e.target); } });
    }, {threshold:.1}).observe(root.firstChild);
    $$('.reveal', root).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }

  /* ====== Smart Shield · 6-dim Live ====== */
  const DIMS = [
    { id:'urgent',  name:'紧急度',     w:0.22 },
    { id:'self',    name:'与你相关',   w:0.18 },
    { id:'work',    name:'工作相关',   w:0.18 },
    { id:'time',    name:'时间敏感',   w:0.14 },
    { id:'sender',  name:'发送方权重', w:0.16 },
    { id:'channel', name:'频道权重',   w:0.12 },
  ];
  function classify(text, sender, chat) {
    const t = (text || '').trim();
    const len = t.length;
    const has = (kw) => kw.some(k => t.includes(k));
    let urgent = 30 + (has(['P0','上线','紧急','asap','ASAP','立即','马上','现在','尽快']) ? 55 : 0)
                    + (t.includes('!') || t.includes('！') ? 6 : 0);
    let self   = 30 + (has(['你','@','请','麻烦','帮我','帮忙']) ? 35 : 0);
    let work   = 30 + (has(['上线','需求','PR','部署','bug','BUG','报错','回滚','排查','review','文档','会议']) ? 45 : 0);
    let time   = 30 + (has(['今晚','今天','明早','明天','10 点','10点','马上','立即','之前','deadline','DDL']) ? 50 : 0);
    const senderW = { boss:90, peer:60, cross:48, bot:25 }[sender] || 50;
    const chatW   = { dm:78, team:62, big:35, biz:45 }[chat] || 50;
    const sender_score  = senderW + (sender==='bot' && t.includes('CI') ? -5 : 0);
    const channel_score = chatW;
    const cap = (n) => Math.max(0, Math.min(100, Math.round(n)));
    if (len < 6) { urgent -= 20; work -= 20; }
    return [urgent, self, work, time, sender_score, channel_score].map(cap);
  }
  function verdictFor(total) {
    if (total >= 78) return { lvl:'P0', label:'P0 · 立即送达', cls:'p0' };
    if (total >= 58) return { lvl:'P1', label:'P1 · 折叠摘要',  cls:'p1' };
    if (total >= 38) return { lvl:'P2', label:'P2 · 静默归档',  cls:'p2' };
    return                  { lvl:'P3', label:'P3 · 直接静音',  cls:'p3' };
  }
  function renderShieldEmpty() {
    const root = $('#shieldDims');
    root.innerHTML = '';
    DIMS.forEach(d => root.appendChild(
      h('div',{class:'dim-row'},[
        h('div',{class:'name'}, d.name),
        h('div',{class:'bar'},[ h('i',{}) ]),
        h('div',{class:'val', 'data-id':d.id}, '—'),
      ])
    ));
  }
  function runShield() {
    const text   = $('#shieldText').value;
    const sender = $('#shieldSender').value;
    const chat   = $('#shieldChat').value;
    const scores = classify(text, sender, chat);
    const total  = scores.reduce((acc,v,i) => acc + v * DIMS[i].w, 0);
    const verdict = verdictFor(total);
    const dimRows = $$('.dim-row', $('#shieldDims'));
    dimRows.forEach((row,i) => {
      const bar = $('.bar > i', row);
      const val = $('.val', row);
      bar.style.background = scores[i]>=80 ? 'var(--p0)' : (scores[i]>=50 ? 'var(--warn)' : 'var(--ok)');
      bar.style.width = '0%';
      requestAnimationFrame(() => {
        bar.style.width = scores[i] + '%';
      });
      val.textContent = scores[i];
    });
    const v = $('#shieldVerdict');
    v.className = 'verdict ' + verdict.cls;
    v.textContent = verdict.label;
    $('#shieldTotal').textContent = '加权总分 · ' + total.toFixed(1);
  }
  function initShield() {
    renderShieldEmpty();
    $('#shieldRun').addEventListener('click', runShield);
    setTimeout(runShield, 500);
  }

  /* ====== Mentor Skills · animated demos ====== */
  const SKILLS = [
    { name:'mentor_review_message', label:'写作 Mentor',
      desc:'三段重写 + NVC 诊断 + 引用组织默契。永远是草稿。',
      icon:'✎',
      script: [
        { type:'label', text:'原文 · 输入框' },
        { type:'orig',  text:'好的' },
        { type:'label', text:'NVC 诊断' },
        { type:'diag',  text:'缺事实 / 缺承接动作 / 偏被动' },
        { type:'label', text:'重写 · V1 稳' },
        { type:'rewrite', text:'收到。我 9:50 切到 P0 频道，先把回滚预案过一遍。' },
      ]},
    { name:'mentor_clarify_task', label:'任务澄清',
      desc:'拆 Scope/Deadline/产出/边界；缺哪个就反问哪个。',
      icon:'⌖',
      script: [
        { type:'label', text:'输入 · 老板原话' },
        { type:'orig',  text:'你跟一下下周那个需求' },
        { type:'label', text:'缺失维度' },
        { type:'diag',  text:'⚠ Scope · ⚠ Deadline · ⚠ Owner' },
        { type:'label', text:'反问草稿' },
        { type:'rewrite', text:'王总：1) 哪个需求？2) 周几之前要 demo？3) 产出物是文档还是原型？' },
      ]},
    { name:'mentor_draft_weekly', label:'周报草稿',
      desc:'从 Archival 抽事实，STAR 起草，带引用。',
      icon:'☷',
      script: [
        { type:'label', text:'本周事实 · 来自 Archival' },
        { type:'orig',  text:'42 条群消息 · 5 个 PR · 1 次 P0' },
        { type:'label', text:'STAR 草稿' },
        { type:'rewrite', text:'S: 周二 P0 上线\nT: 担任值班 owner\nA: 提前过回滚预案 / 拉张三对齐\nR: 17 分钟内完成回滚 [archival#A0421]' },
      ]},
    { name:'mentor_search_org_kb', label:'组织默契 RAG',
      desc:'每人一份 KB；embedding + BM25 双索引；带引用。',
      icon:'⌘',
      script: [
        { type:'label', text:'问题' },
        { type:'orig',  text:'我们怎么写发版公告？' },
        { type:'label', text:'命中 KB · top-3' },
        { type:'rewrite', text:'• 模板 docx · KB#TPL_05\n• 抄送范围 · KB#PRC_12\n• "三段式：变更 / 影响 / 回滚" · KB#STY_03' },
      ]},
  ];
  function renderSkills() {
    const root = $('#skillsGrid');
    root.innerHTML = '';
    SKILLS.forEach((s,idx) => {
      const demo = h('div',{class:'demo'});
      const card = h('div',{class:'skill-card reveal'},[
        h('div',{class:'top'},[
          h('div',{class:'icon'}, s.icon),
          h('div',{},[
            h('div',{class:'name'}, s.label),
            h('div',{style:{fontSize:'.7rem',color:'var(--fg3)',fontFamily:'var(--mono)'}}, s.name),
          ]),
        ]),
        h('div',{class:'desc'}, s.desc),
        demo,
      ]);
      root.appendChild(card);
      // play animation when visible
      const io = new IntersectionObserver((entries, o) => {
        entries.forEach(e => {
          if (e.isIntersecting) {
            playSkill(demo, s.script, idx);
            o.unobserve(e.target);
          }
        });
      }, { threshold: 0.35 });
      io.observe(card);
    });
    // wire reveal
    $$('.reveal', root).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }
  function playSkill(demo, script, idx) {
    demo.innerHTML = '';
    let t = 0;
    script.forEach((s,i) => {
      const delay = t;
      t += s.type === 'orig' ? 600 : (s.type === 'diag' ? 700 : (s.type === 'rewrite' ? 1100 : 350));
      setTimeout(() => {
        const node = h('div',{class:'step'});
        if (s.type === 'label') {
          node.appendChild(h('div',{class:'label'}, s.text));
        } else if (s.type === 'orig') {
          node.appendChild(h('div',{}, [ h('span',{class:'diff-del'}, s.text) ]));
        } else if (s.type === 'diag') {
          node.appendChild(h('div',{style:{color:'var(--warn)'}}, s.text));
        } else if (s.type === 'rewrite') {
          // typewriter
          const span = h('span',{class:'typed', style:{whiteSpace:'pre-line'}});
          node.appendChild(h('div',{}, [
            h('span',{class:'diff-add'},'＋'), ' ', span
          ]));
          typewriter(span, s.text, 14);
        }
        demo.appendChild(node);
        // cap at last 6 lines visually
        while (demo.childElementCount > 7) demo.removeChild(demo.firstChild);
      }, delay);
    });
  }
  function typewriter(el, text, ms) {
    let i = 0;
    const tick = () => {
      el.textContent = text.slice(0, i);
      if (i < text.length) { i += 1; setTimeout(tick, ms); }
      else { el.style.borderRight = '0'; }
    };
    tick();
  }

  /* ====== FlowMemory pipeline ====== */
  const MEM_LINES = [
    '+ working_memory.append(event#A0421-msg-12)',
    '+ working_memory.size = 87 / 128 (within window)',
    '— compaction.trigger(window full)',
    '+ archival.write_summary("周二 P0 上线 · 17m 回滚 …")',
    '+ archival.embedding(384d) + bm25 index',
    '+ flow_memory.md.tier=team write tag #postmortem',
    '+ next mentor_draft_weekly will RAG over archival',
  ];
  const MD_TIERS = [
    { n:'1', name:'org · 公司层',     ex:'/flow_memory.md' },
    { n:'2', name:'dept · 部门层',     ex:'/flow_memory/dept.md' },
    { n:'3', name:'team · 团队层',     ex:'/flow_memory/team.md' },
    { n:'4', name:'project · 项目层',  ex:'/flow_memory/proj.md' },
    { n:'5', name:'user · 个人层',     ex:'/flow_memory/me.md' },
    { n:'6', name:'session · 会话层',  ex:'(in-memory)' },
  ];
  function renderMemoryMd() {
    const root = $('#memMdList');
    root.innerHTML = '';
    MD_TIERS.forEach((t,i) => {
      const node = h('div',{class:'mem-tier', style:{ animationDelay: (i*0.12) + 's' }},[
        h('div',{class:'num'}, t.n),
        h('div',{class:'nm'}, t.name),
        h('div',{class:'ex'}, t.ex),
      ]);
      root.appendChild(node);
    });
  }
  function playMemoryPipeline() {
    const pkg = $('#memPkg');
    const n1 = $('#memN1'), n2 = $('#memN2'), n3 = $('#memN3');
    pkg.innerHTML = '';
    let t = 0;
    [n1,n2,n3].forEach(n => n.classList.remove('active'));
    setTimeout(() => n1.classList.add('active'), 200);
    setTimeout(() => { n1.classList.remove('active'); n2.classList.add('active'); }, 1800);
    setTimeout(() => { n2.classList.remove('active'); n3.classList.add('active'); }, 3600);
    MEM_LINES.forEach((l,i) => {
      setTimeout(() => {
        const ln = h('div',{class:'line', style:{ animationDelay: '0s' }}, l);
        pkg.appendChild(ln);
        if (pkg.childElementCount > 7) pkg.removeChild(pkg.firstChild);
      }, 400 + i * 700);
    });
  }
  function initMemory() {
    renderMemoryMd();
    const io = new IntersectionObserver((entries,o) => {
      entries.forEach(e => {
        if (e.isIntersecting) { playMemoryPipeline(); o.unobserve(e.target); }
      });
    }, { threshold: 0.3 });
    io.observe($('.memory-pipeline'));
  }

  /* ====== Engine ====== */
  const ENGINE = {
    layers: [
      { name:'Entry',      nodes:['Feishu Bot','MCP Server','Dashboard FastAPI','Scheduler'] },
      { name:'Domain',     nodes:['Smart Shield · 6-dim','Mentor 4 Skills','Recovery Card','Feishu 9 APIs'] },
      { name:'Memory',     nodes:['WorkingMemory','Compaction','Archival','flow_memory.md · 6 tier','Per-user RAG'] },
      { name:'Runtime',    nodes:['ToolRegistry','SkillLoader','HookSystem','PermissionFacade'] },
      { name:'Security',   nodes:['Permission','Inject','Hook','PII','Denylist','RateLimit','Sandbox','Audit'] },
    ],
    inspirations: [
      { from:'nO 主循环',     to:'Smart Shield process_message_v3', detail:'事件驱动、可中断、可回滚' },
      { from:'wU2 三层压缩',  to:'WorkingMemory → Compaction → Archival', detail:'按窗口阈值滚动压缩' },
      { from:'7-gate 沙箱',   to:'Security Stack 8 道闸门',          detail:'扩展 OWASP LLM Top10 全覆盖' },
      { from:'SkillLoader',   to:'Mentor 4 Skill 可插拔',            detail:'外部 yaml 注册即生效' },
    ]
  };
  function renderEngine() {
    const root = $('#engineWrap');
    root.innerHTML = '';
    ENGINE.layers.forEach(l => root.appendChild(
      h('div',{class:'layer-row'},[
        h('div',{class:'layer-name'}, l.name),
        h('div',{class:'nodes'}, l.nodes.map(n => h('div',{class:'node'}, n)))
      ])
    ));
    const insp = h('div',{class:'engine-insp'});
    ENGINE.inspirations.forEach(i => insp.appendChild(
      h('div',{class:'insp-row'},[
        h('span',{class:'from'}, i.from),
        h('span',{class:'arrow'}, '→'),
        h('span',{class:'to'},   i.to),
        h('span',{class:'detail'}, '· ' + i.detail),
      ])
    ));
    root.appendChild(insp);
  }

  /* ====== MCP playground ====== */
  const MCP_TOOLS = [
    { name:'get_focus_status',     doc:'返回某用户当前的专注状态（focus / break / idle）。',   alias:false, demoArgs:{open_id:'ou_demo_user_0001'} },
    { name:'classify_message',     doc:'调用 Smart Shield 6 维分类引擎，输出 P 级与 6 维评分卡。', alias:false,
      demoArgs:{user_open_id:'ou_demo_user_0001',sender_name:'王总',sender_id:'ou_boss_001',content:'今晚 10 点 P0 上线',chat_name:'核心工作群',chat_type:'team'} },
    { name:'get_recent_digest',    doc:'最近会话压缩摘要（来自 Archival）。',                 alias:false, demoArgs:{open_id:'ou_demo_user_0001',limit:5} },
    { name:'add_whitelist',        doc:'把某发送方加入个人 P0 白名单。',                       alias:false, demoArgs:{open_id:'ou_demo_user_0001',who:'ou_boss_001'} },
    { name:'rollback_decision',    doc:'把某条 AI 决策标记为已回滚（可解释 + 可追溯）。',     alias:false, demoArgs:{open_id:'ou_demo_user_0001',decision_id:'dec_demo_001'} },
    { name:'query_memory',         doc:'对个人记忆做轻量词法检索。',                           alias:false, demoArgs:{open_id:'ou_demo_user_0001',query:'P0 上线',limit:3} },
    { name:'mentor_review_message',doc:'写作 Mentor：NVC 诊断 + 3 段重写 + 引用。',              alias:false,
      demoArgs:{open_id:'ou_demo_user_0001',message:'好的',recipient:'王总'} },
    { name:'mentor_clarify_task',  doc:'任务 Mentor：拆 Scope/Deadline/Owner，缺啥反问啥。',    alias:false,
      demoArgs:{open_id:'ou_demo_user_0001',task_description:'你跟一下下周那个需求',assigner:'王总'} },
    { name:'mentor_draft_weekly',  doc:'周报 Mentor：从 Archival 抽事实，STAR 起草。',          alias:false, demoArgs:{open_id:'ou_demo_user_0001',week_offset:0} },
    { name:'mentor_search_org_kb', doc:'组织默契 RAG（embedding + BM25 双索引）。',          alias:false, demoArgs:{open_id:'ou_demo_user_0001',query:'发版公告怎么写',top_k:3} },
    { name:'classify_readonly',    doc:'V2 · 只读分类，不写副作用。',                         alias:false, demoArgs:{user_open_id:'ou_demo_user_0001',content:'你下午有空吗'} },
    { name:'skill_invoke',         doc:'V2 · 通用 Skill 调度入口。',                          alias:false, demoArgs:{open_id:'ou_demo_user_0001',skill:'mentor_review_message',input:{message:'好的'}} },
    { name:'memory_resolve',       doc:'V2 · 解析 6 级 flow_memory.md 合并视图。',           alias:false, demoArgs:{open_id:'ou_demo_user_0001'} },
    { name:'list_skills',          doc:'V2 · 列出当前可用 Skill 与版本。',                   alias:false, demoArgs:{} },
  ];
  function renderMcp() {
    const root = $('#mcpGrid');
    root.innerHTML = '';
    MCP_TOOLS.forEach(t => {
      const card = h('div',{class:'mcp-card', onclick:() => callMcp(t)},[
        h('span',{class:'badge' + (t.alias?' alias':'')}, t.alias ? 'alias' : 'tool'),
        h('div',{class:'nm'}, t.name),
        h('div',{class:'doc'}, t.doc),
      ]);
      root.appendChild(card);
    });
  }
  async function callMcp(tool) {
    const out = $('#mcpResult');
    out.textContent = `→ POST /mcp/call  { "tool": "${tool.name}", "arguments": ${JSON.stringify(tool.demoArgs)} }\n…`;
    try {
      const r = await fetch('/mcp/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: tool.name, arguments: tool.demoArgs }),
      });
      const j = await r.json();
      out.textContent = `← ${r.status} ${r.statusText}\n` + JSON.stringify(j, null, 2);
    } catch (e) {
      out.textContent =
`× 直接 fetch /mcp/call 失败（可能：本地预览没起后端，或跨域）。
工具 schema 与示例参数：
{
  "tool": "${tool.name}",
  "arguments": ${JSON.stringify(tool.demoArgs, null, 2)}
}

线上调用方式：
  curl -XPOST http://118.178.242.26/mcp/call \\
       -H 'Content-Type: application/json' \\
       -d '{"tool":"${tool.name}","arguments":${JSON.stringify(tool.demoArgs)}}'

错误信息：${e.message}`;
    }
  }

  /* ====== Security Gates ====== */
  const GATES = [
    { n:'1', nm:'Permission',  desc:'工具/能力级权限门控 ToolRegistry × Skill' },
    { n:'2', nm:'Inject',      desc:'提示词注入 / 红队 transcript 分类' },
    { n:'3', nm:'Hook',        desc:'生命周期 Hook · 组织策略可覆盖' },
    { n:'4', nm:'PII',         desc:'手机号/邮箱/身份证 正则脱敏' },
    { n:'5', nm:'Denylist',    desc:'高风险关键词模式快速拒绝' },
    { n:'6', nm:'RateLimit',   desc:'按用户 + 工具维度速率限制' },
    { n:'7', nm:'Sandbox',     desc:'飞书 API 面白名单沙箱' },
    { n:'8', nm:'Audit',       desc:'追加式 JSONL · 全部决策可回滚' },
  ];
  const PRIVACY = [
    { ttl:'数据落盘最小化', body:'只存元数据 + 摘要，不存原文（可选项）。所有数据在你自己的飞书租户内。' },
    { ttl:'AI 永远是草稿',  body:'Mentor 4 Skill 不会自动发任何消息；你点哪个版本发哪个。' },
    { ttl:'决策 100% 可回滚', body:'rollback_decision 工具 + Dashboard 一键回滚最近 N 条。' },
    { ttl:'Bot 标识 🤖',    body:'所有 AI 草稿都带 🤖；30 秒撤回；引用可追溯到 Archival id。' },
  ];
  function renderSecurity() {
    const g = $('#gateGrid');
    g.innerHTML = '';
    GATES.forEach(x => g.appendChild(
      h('div',{class:'gate-card reveal'},[
        h('div',{class:'ring'}, x.n),
        h('div',{},[
          h('div',{class:'nm'}, x.nm),
          h('div',{class:'desc'}, x.desc),
        ])
      ])
    ));
    const p = $('#privacyGrid');
    p.innerHTML = '';
    PRIVACY.forEach(x => p.appendChild(
      h('div',{class:'privacy-card reveal'},[
        h('strong',{}, x.ttl + ' · '),
        x.body,
      ])
    ));
    [...$$('.reveal',g), ...$$('.reveal',p)].forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }

  /* ====== Tracks + APIs ====== */
  const TRACKS = [
    { rank:'第一志愿', name:'飞书 AI 产品创新 · 课题二', topic:'基于 IM 的办公协同智能助手',
      map:'对应 LarkMentor 全栈：消息层 Smart Shield + 表达层 Mentor + 飞书 docx / 多维表格 / 卡片回调' },
    { rank:'第二志愿', name:'飞书 OpenClaw · 课题二',     topic:'企业级长程协作 Memory 系统',
      map:'对应 FlowMemory 三层 + 6 级 flow_memory.md，已抽成独立 SDK 可被 OpenClaw 调用' },
    { rank:'第三志愿', name:'AI 大模型安全 · 课题一',     topic:'面向 Agent + 客户端环境下的安全操作与数据防护',
      map:'对应 Security 8 道闸门 + Promptfoo 红队，已抽成 ShieldClaw 中间件库' },
  ];
  const APIS = [
    { nm:'IM Message v1', built:true },
    { nm:'IM Card v1',    built:true },
    { nm:'Card Action v1',built:true },
    { nm:'Drive · docx',  built:true },
    { nm:'Bitable',       built:true },
    { nm:'Calendar',      built:false },
    { nm:'Wiki',          built:false },
    { nm:'Task v2',       built:false },
    { nm:'Minutes 妙记',  built:false },
  ];
  function renderTracks() {
    const t = $('#tracksGrid');
    t.innerHTML = '';
    TRACKS.forEach(x => t.appendChild(
      h('div',{class:'track-card reveal'},[
        h('span',{class:'rank'}, x.rank),
        h('div',{class:'name'},  x.name),
        h('div',{class:'topic'}, x.topic),
        h('div',{class:'map'},   x.map),
      ])
    ));
    const a = $('#apiCloud');
    a.innerHTML = '';
    APIS.forEach(x => a.appendChild(
      h('div',{class:'api-chip' + (x.built ? '' : ' lab')},[
        h('span',{class:'dot'}), x.nm
      ])
    ));
    $$('.reveal', t).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }

  /* ====== Status (Built / Lab / Planned) ====== */
  const STATUS = {
    built: [
      'Smart Shield 6 维分类引擎 · LLM 兜底',
      'Mentor 4 Skill · 全部 Skill 已通过 pytest',
      'FlowMemory 三层 · WorkingMemory 自动滚动压缩',
      '8 层安全栈 · OWASP LLM Top10 全覆盖',
      'MCP HTTP / SSE 服务 · 14 工具',
      '飞书 IM/卡片/docx/多维表格 5 个 API · 上线',
      'Dashboard FastAPI · 周报 / Wrapped / 团队 / 审计',
    ],
    lab: [
      '飞书 Calendar · 已编码，等审批权限',
      '飞书 Wiki 写入 · 已编码，等审批权限',
      'Task v2 看板联动 · 已编码，等审批权限',
      '妙记 Minutes 摘要回写 · 已编码',
    ],
    planned: [
      '组织级 KB 多租户隔离层（仅设计完成）',
      '多 Bot 协作（Claude Code 风格 Sub-agent）',
      'KMS 集成的密钥沙箱',
    ],
  };
  function renderStatus() {
    const root = $('#statusGrid');
    root.innerHTML = '';
    [
      ['built','✓ Built · 评委可现场跑'],
      ['lab','◐ Lab · 已编码 等审批'],
      ['planned','◌ Planned · 设计完成'],
    ].forEach(([k,t]) => {
      root.appendChild(
        h('div',{class:'status-col reveal ' + k},[
          h('h3',{},[ h('span',{class:'dot'}), t ]),
          h('ul',{}, STATUS[k].map(it => h('li',{}, it)))
        ])
      );
    });
    $$('.reveal', root).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }

  /* ====== Team ====== */
  const TEAM = [
    {
      avatar:'李',
      name:'李洁盈',
      role:'产品 / 设计',
      bio:'',
      links:[
        { ttl:'Email',     href:'mailto:JieyingLiii@outlook.com', label:'JieyingLiii@outlook.com' },
        { ttl:'GitHub',    href:'https://github.com/Jane-0213',   label:'github.com/Jane-0213' },
        { ttl:'小红书',    href:'#',                              label:'李什么盈' },
        { ttl:'个人主页',  href:'https://janeliii.netlify.app/',  label:'janeliii.netlify.app' },
      ]
    },
    {
      avatar:'戴',
      name:'戴尚好',
      role:'全栈 / Agent 安全 / 部署',
      bio:'',
      links:[
        { ttl:'Email',     href:'mailto:bcefghj@163.com',         label:'bcefghj@163.com' },
        { ttl:'GitHub',    href:'https://github.com/bcefghj',     label:'github.com/bcefghj' },
        { ttl:'小红书',    href:'#',                              label:'bcefghj' },
        { ttl:'个人主页',  href:'https://bcefghj.github.io',      label:'bcefghj.github.io' },
      ]
    }
  ];
  function renderTeam() {
    const root = $('#teamGrid');
    root.innerHTML = '';
    TEAM.forEach(p => root.appendChild(
      h('div',{class:'team-card reveal'},[
        h('div',{class:'row'},[
          h('div',{class:'avatar'}, p.avatar),
          h('div',{},[
            h('h3',{}, p.name),
            h('div',{class:'role'}, p.role),
          ])
        ]),
        p.bio ? h('div',{class:'bio'}, p.bio) : null,
        h('div',{class:'links'}, p.links.map(l => {
          const a = h('a',{ href:l.href, target:'_blank', rel:'noopener' },[
            l.ttl + ' · ' + l.label
          ]);
          if (l.href === '#') a.removeAttribute('target');
          return a;
        })),
      ])
    ));
    $$('.reveal', root).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }

  /* ====== Resources / FAQ ====== */
  const RESOURCES = [
    { ttl:'技术报告 PDF · 下载',      href:'/larkmentor_report.pdf',                 url:'larkmentor_report.pdf' },
    { ttl:'GitHub · 主仓库',          href:'https://github.com/bcefghj/larkmentor', url:'github.com/bcefghj/larkmentor' },
    { ttl:'Live Dashboard',           href:'/dashboard',                              url:'/dashboard' },
    { ttl:'MCP · 可视化工具浏览',     href:'/mcp',                                    url:'/mcp' },
    { ttl:'MCP · Raw JSON',           href:'/mcp/tools',                              url:'/mcp/tools' },
    { ttl:'Health',                   href:'/health',                                 url:'/health' },
    { ttl:'2026 飞书 AI 校园挑战赛',  href:'https://bytedance.aiforce.cloud/app/app_4jv6kvy942afr', url:'bytedance.aiforce.cloud' },
  ];
  const FAQ = [
    { q:'你这是 ChatGPT 套壳吗？',
      a:'不是。7 支柱独立工程 + 8 层安全栈 + 6 级 memory + RAG + MCP，11k+ 行代码，119+ pytest 通过。LLM 只在 6 维分类边界模糊（±0.05）和 Mentor 草稿生成时调用。' },
    { q:'跟 Slack AI / Notion AI 有什么不同？',
      a:'我们是飞书生态里第一个把"消息分流"和"表达带教"做在同一个 IM Bot 里、共用一份组织 RAG 的产品。Slack AI 不管表达，Notion AI 不管打扰。' },
    { q:'双线产品不会精神分裂吗？',
      a:'不会。Smart Shield 与 Mentor 通过同一份 FlowMemory + per-user RAG 共享上下文，Recovery Card 是统一 UI 出口。' },
    { q:'安全栈是不是 PPT？',
      a:'不是。Promptfoo 红队 14/14 PASS，所有决策走 Audit JSONL，可在 Dashboard 一键回滚。详见 GitHub 仓库 60_tests/。' },
    { q:'代回复出错谁负责？',
      a:'Mentor 永远是草稿；用户点采纳才进入 SEND_ACTION 工具；🤖 标识；30 秒可撤回；引用可追溯。' },
    { q:'为什么叫 LarkMentor？',
      a:'"Mentor" 是关系感的词。我们要表达的是：双线服务都是为了"陪一个人在这家公司活下去"。关系感 > 工具感。' },
  ];
  function renderResources() {
    const r = $('#resGrid');
    r.innerHTML = '';
    RESOURCES.forEach(x => r.appendChild(
      h('a',{class:'res-card reveal', href:x.href, target:'_blank', rel:'noopener'},[
        h('div',{class:'ttl'}, x.ttl),
        h('div',{class:'url'}, x.url),
      ])
    ));
    const f = $('#faqList');
    f.innerHTML = '';
    FAQ.forEach(x => f.appendChild(
      h('details',{class:'faq-item reveal'},[
        h('summary',{}, x.q),
        h('p',{}, x.a),
      ])
    ));
    $$('.reveal', r).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
    $$('.reveal', f).forEach(el => {
      const io = new IntersectionObserver((es,oo) => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); oo.unobserve(e.target); }
      }), {threshold:.1});
      io.observe(el);
    });
  }

  /* ====== Boot ====== */
  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initReveal();
    renderHeroStats();
    initSim();
    renderSolution();
    initShield();
    renderSkills();
    initMemory();
    renderEngine();
    renderMcp();
    renderSecurity();
    renderTracks();
    renderStatus();
    renderTeam();
    renderResources();
    // re-run reveal observer for any reveal elements added by render functions
    setTimeout(initReveal, 100);
  });
})();
