/* ============================================================================
 * LarkMentor pitch-site · 单一数据源
 * 这一份数据被 A 套（editorial）和 B 套（agent OS）共用。
 * 修改文案 → 改这里 → 两版同步生效。
 * ========================================================================== */

window.FG = window.FG || {};

FG.meta = {
  project: 'LarkMentor',
  tagline: '飞书 IM 上的双引擎协同助手 · 挡掉不该打断你的，接住打断你的人想说的',
  shortDesc: '飞书生态里第一个把"消息分流"和"表达带教"做在同一个 Bot 里的产品 · Smart Shield + 4 个 Mentor Skill + MCP 跨 Agent 协议。',
  contest: {
    name: '2026 飞书 AI 校园挑战赛',
    homepage: 'https://bytedance.aiforce.cloud/app/app_4jv6kvy942afr',
    track1: '飞书 AI 产品创新赛道 · 课题二：基于 IM 的办公协同智能助手',
    track2: '飞书 OpenClaw 赛道 · 课题二：企业级长程协作 Memory 系统',
    track3: 'AI 大模型安全赛道 · 课题一：面向 Agent + 客户端环境下的安全操作与数据防护',
    submittedAt: '2026-04-17',
    status: '已提交报名 · 一套代码三志愿覆盖',
  },
  liveUrls: {
    home: 'http://118.178.242.26/',
    dashboard: 'http://118.178.242.26/dashboard',
    mcpTools: 'http://118.178.242.26/mcp/tools',
    mcpCall: 'http://118.178.242.26/mcp/call',
    health: 'http://118.178.242.26/health',
    githubRepo: 'https://github.com/bcefghj/larkmentor',
    githubPages: 'https://bcefghj.github.io/larkmentor/',
  },
};

/* --------------------------------------------------------------------------
 * Hero CTA 按钮
 * ----------------------------------------------------------------------- */
FG.heroCTAs = [
  { label: '看 90 秒 Demo',  href: '#demo-sim',     primary: true },
  { label: '试玩分类引擎',     href: '#demo-play',    primary: false },
  { label: '调用 MCP API',    href: '#demo-mcp',     primary: false },
  { label: 'GitHub',          href: 'https://github.com/bcefghj/larkmentor', external: true, primary: false },
];

/* --------------------------------------------------------------------------
 * 关键数字（Hero 下的徽章 + Metrics 章节）
 * 严格区分：Built（真实）/ Planned（计划）
 * ----------------------------------------------------------------------- */
FG.heroStats = [
  { v: '4',       k: '个 Mentor Skill',   note: '消息起草/任务澄清/入职沉淀/周报回顾', kind: 'built' },
  { v: '119/119', k: 'pytest 通过',      note: 'v3 + v4 + LarkMentor 全过', kind: 'built' },
  { v: '99%',     k: '6 维分类准确率',   note: '102 YAML 测试场景', kind: 'built' },
  { v: '10',      k: '个 MCP 工具',       note: '4 mentor_* + 4 alias + 6 v3', kind: 'built' },
];

/* --------------------------------------------------------------------------
 * Problem 章节：3 个真实数据 + 1 个反思
 * ----------------------------------------------------------------------- */
FG.problemStats = [
  {
    num: '11',
    unit: 'min',
    label: '知识工作者平均每 11 分钟被打断一次',
    src: 'Mark · UC Irvine · 2005',
  },
  {
    num: '23',
    unit: 'min',
    label: '每次打断后平均要 23 分钟才能重回深度工作',
    src: '同上 · 实证研究',
  },
  {
    num: '0',
    unit: '',
    label: '现有 IM 工具中能在中断后帮你恢复上下文的数量',
    src: 'LarkMentor 团队 · 7 类工具横评',
  },
];

FG.problemQuote = {
  text: '大多数深度工作失败，不是因为不会做，而是因为工作流被消息和沟通切碎。',
  author: '李洁盈 · 团队产品观',
};

/* --------------------------------------------------------------------------
 * Solution 章节：4 大能力支柱
 * ----------------------------------------------------------------------- */
FG.solutions = [
  {
    code: '01',
    tag: '专业技能',
    title: 'MentorWrite · 写作 Mentor',
    desc: 'NVC（非暴力沟通）4 段诊断（事实 / 感受 / 需求 / 请求）+ 3 档语气切换（对老板 / 同事 / 下属）+ 3 版改写（保守 / 中性 / 直接）+ 引用追踪。',
    bullets: ['NVC 框架', '3 档语气', '3 版可选', '组织 RAG 引用'],
  },
  {
    code: '02',
    tag: '工作方法',
    title: 'MentorTask · 任务 Mentor',
    desc: 'LLM 评 ambiguity 0-1，>0.5 给信息增益最高的 1-2 个澄清问题；4 维缺失分析（scope / deadline / stakeholder / success_criteria）；≤0.5 给"理解 + 计划 + 风险点"。',
    bullets: ['模糊度打分', '4 维缺失', '主动澄清', 'arXiv 2603.26233'],
  },
  {
    code: '03',
    tag: '团队融入',
    title: 'MentorOnboard · 入门指引',
    desc: '5 问 onboarding 流（部门 / 导师 / 第一周目标 / 不熟悉的工具 / 想优先了解），答案存入用户 RAG 标记最高优先级，后续 Mentor 出手优先召回。',
    bullets: ['5 问 30 秒', '答案入 RAG', '最高优先级召回', 'LarkMentor v1 新增'],
  },
  {
    code: '04',
    tag: '成长跟进',
    title: 'MentorReview · 周报 Mentor',
    desc: 'STAR 强制结构（Situation / Task / Action / Result）+ archival 引用，周日 21:00 LLM 自动生成成长摘要追加到飞书 Docx。',
    bullets: ['STAR 校验', '引用 archival', '周报自动', '成长档案 Docx'],
  },
];

/* ----------------------------------------------------------------------
 * LarkMentor 4 个 Mentor Skill 模块说明
 * （新加一屏，给评委看产品叙事的核心）
 * ----------------------------------------------------------------------- */
FG.bytedanceAlignment = {
  title: '4 个 Mentor Skill 覆盖新人 IM 高频场景',
  intro: 'LarkMentor 把表达引导代码化为 4 个 Skill——写作改写、任务澄清、周报生成、新人入职。让每个人有 24 小时在线的 AI Mentor，所有输出均为草稿，需确认后发送。',
  rows: [
    { dim: '专业技能传授', module: 'MentorWrite', impl: 'NVC 4 段诊断 + 3 档语气 + 3 版改写' },
    { dim: '工作方法指导', module: 'MentorTask', impl: 'ambiguity 0-1 + 4 维缺失 + 主动澄清' },
    { dim: '团队融入协助', module: 'MentorOnboard', impl: '5 问入职流 + RAG 最高优先级' },
    { dim: '成长跟进', module: 'MentorReview', impl: 'STAR 强制结构 + 引用追踪 + 周日摘要' },
  ],
  cta: { label: '看完整对齐说明 PDF', href: '/larkmentor_pitch.pdf' },
};

/* --------------------------------------------------------------------------
 * 4 个 P 级分类卡（Smart Shield 章节用）
 * ----------------------------------------------------------------------- */
FG.priorityLevels = [
  { lvl: 'P0', name: 'BREAK_IN',    color: '#ef4444', desc: '立即推送加急卡片',           example: '"线上故障，立即处理"',  rule: '白名单 / 紧急词 / 上级 + 时间词' },
  { lvl: 'P1', name: 'QUEUE',       color: '#f59e0b', desc: '专注结束后摘要',             example: '"Q3 方案的数据怎么取的"', rule: '当前任务关联 / 重要客户' },
  { lvl: 'P2', name: 'AUTO_REPLY',  color: '#10b981', desc: '智能代回复（带 🤖 标识）',   example: '"明天会议改到几点"',     rule: '普通提问 / 同部门事务' },
  { lvl: 'P3', name: 'ARCHIVE',     color: '#9ca3af', desc: '静默归档不打扰',             example: '"今天天气真好"',         rule: '大群闲聊 / Bot 推送 / 广播' },
];

/* --------------------------------------------------------------------------
 * 6 维分类引擎（Demo 2 试玩用）
 * ----------------------------------------------------------------------- */
FG.dims = [
  { code: 'D1', name: '身份',     en: 'Identity',     weight: 0.25 },
  { code: 'D2', name: '关系',     en: 'Relationship', weight: 0.15 },
  { code: 'D3', name: '内容',     en: 'Content',      weight: 0.25 },
  { code: 'D4', name: '任务关联', en: 'Task',         weight: 0.15 },
  { code: 'D5', name: '时间',     en: 'Time',         weight: 0.10 },
  { code: 'D6', name: '频道',     en: 'Channel',      weight: 0.10 },
];

/* --------------------------------------------------------------------------
 * 8 层安全栈
 * ----------------------------------------------------------------------- */
FG.securityGates = [
  { id: 'G1', name: 'PermissionManager',   en: '5 级权限控制',     desc: '5 级权限模型，工具调用前检查身份 + 范围' },
  { id: 'G2', name: 'TranscriptClassifier', en: '防 prompt 注入',  desc: 'regex 快路 + LLM-as-judge 慢路双层防御' },
  { id: 'G3', name: 'Hook System',         en: '声明式策略',       desc: 'YAML 配置 deny / force_level / require_human' },
  { id: 'G4', name: 'PII Scrubber',        en: '7 类正则脱敏',     desc: '手机 / 身份证 / 邮箱 / open_id / IP / 银行卡' },
  { id: 'G5', name: 'Keyword Denylist',    en: '敏感词快速拒',     desc: '千级敏感词字典，毫秒级匹配' },
  { id: 'G6', name: 'Rate Limiter',        en: '每用户/每工具上限', desc: '滑动窗口防滥用' },
  { id: 'G7', name: 'Tool Sandbox',        en: '飞书 API 白名单',   desc: '只放过显式允许的 SDK 调用' },
  { id: 'G8', name: 'Audit Log',           en: 'JSONL 可回滚',     desc: 'append-only 决策日志，30 秒内可撤销' },
];

/* --------------------------------------------------------------------------
 * MCP 6 工具（Demo 4 试玩用）
 * ----------------------------------------------------------------------- */
FG.mcpTools = [
  {
    name: 'get_focus_status',
    desc: '查询用户当前是否在专注',
    args: { open_id: 'ou_demo' },
    sampleResp: { focusing: true, duration_min: 47, pending_count: 3 },
  },
  {
    name: 'classify_message',
    desc: '试算一条消息的优先级',
    args: { user_open_id: 'ou_demo', sender_name: '张三', sender_id: 'ou_zhang', content: '数据库 5xx 告警，紧急', chat_type: 'group' },
    sampleResp: { level: 'P0', score: 0.91, reason: '内容紧急 + 时间敏感', action: 'forward_urgent' },
  },
  {
    name: 'get_recent_digest',
    desc: '获取最近 N 条 Archival 摘要',
    args: { open_id: 'ou_demo', limit: 5 },
    sampleResp: { items: ['本周完成 Q3 方案', '修复 5xx 告警 ×3', '招新面试 2 场'] },
  },
  {
    name: 'add_whitelist',
    desc: '把发件人加入 P0 短路白名单',
    args: { open_id: 'ou_demo', who: 'ou_boss' },
    sampleResp: { ok: true, whitelist_size: 4 },
  },
  {
    name: 'rollback_decision',
    desc: '撤回某次 AI 决策（30 秒内）',
    args: { open_id: 'ou_demo', decision_id: 'dec_20260418_001' },
    sampleResp: { ok: true, original: 'P3', new: 'P0' },
  },
  {
    name: 'query_memory',
    desc: '在用户记忆里做关键词查询',
    args: { open_id: 'ou_demo', query: 'Q3 方案', limit: 3 },
    sampleResp: { items: [{ ts: '2026-04-17', text: '李四发来 Q3 方案 v2 草稿' }] },
  },
];

/* --------------------------------------------------------------------------
 * 飞书 9 大 API 整合
 * ----------------------------------------------------------------------- */
FG.feishuApis = [
  { name: 'IM 消息',        scope: 'im:message',                 status: 'built' },
  { name: '群聊',            scope: 'im:chat:readonly',           status: 'built' },
  { name: '通讯录',          scope: 'contact:user.base:readonly', status: 'built' },
  { name: '多维表格',        scope: 'bitable:app',                status: 'built' },
  { name: '云文档',          scope: 'docx:document',              status: 'built' },
  { name: '加急三件套',      scope: 'im:message.urgent',          status: 'lab' },
  { name: '日历',            scope: 'calendar:calendar',          status: 'lab' },
  { name: '任务 v2',         scope: 'task:task',                  status: 'lab' },
  { name: '妙记 / Wiki',     scope: 'minutes / wiki',             status: 'lab' },
];

/* --------------------------------------------------------------------------
 * Built / Lab / Planned 三列（核心诚实展示）
 * ----------------------------------------------------------------------- */
FG.statusGroups = {
  built: {
    title: 'Built · 已实现',
    subtitle: '代码可跑、有测试覆盖、生产环境运行',
    items: [
      'Smart Shield 6 维分类引擎',
      '102 YAML 场景测试集 99% 准确率',
      '33 例 pytest 全通过',
      '14 例 promptfoo 红队全 PASS',
      'Flow Detector 30+ 自然语言指令',
      'Context Recall 中断恢复卡（LLM 生成）',
      'FlowMemory 三层记忆（Working / Compaction / Archival）',
      '6 级 flow_memory.md 企业租户结构',
      '8 层安全栈（PII / TranscriptClassifier / Hooks / Permission / Denylist / RateLimiter / ToolSandbox / AuditLog）',
      'MCP Server 6 工具 · stdio + HTTP + SSE 三种 transport',
      '飞书工作台杀手锏（Bitable + Docx 自动建）',
      '实时 Dashboard（FastAPI + WebSocket）',
      '阿里云 7×24 三件套 systemd 守护',
      '可解释决策 + 一键回滚',
      '决策审计 JSONL append-only',
    ],
  },
  lab: {
    title: 'Lab · 已编码 · 待开通',
    subtitle: '代码已写完，部分飞书 API 需要审批后启用',
    items: [
      '加急三件套（urgent_app / sms / phone）',
      '消息表情回复（reaction）',
      '日历自动忙碌事件（calendar busy）',
      '飞书任务 v2 自动建任务',
      '妙记转录拉取',
      'Wiki 知识库搜索',
      '话题内回复（reply thread）',
    ],
  },
  planned: {
    title: 'Planned · 规划中',
    subtitle: '设计已完成，待评审窗口期推进',
    items: [
      '14 天真实用户灰测（拟 5 月启动 · 6 用户起步）',
      '周报 / 月报 / Wrapped 卡片（骨架已有，等灰测数据）',
      '团队级注意力热力图与打断分析',
      '多模态消息（图 / 语音 / 文件）语义分级',
      '钉钉 / 企业微信 / Slack 跨平台版本',
      '用户可训练的个性化 AI 偏好',
      '企业 SaaS：多租户 / 数据隔离 / SSO',
    ],
  },
};

/* --------------------------------------------------------------------------
 * 架构图节点（Inside the Engine 章节）
 * ----------------------------------------------------------------------- */
FG.architecture = {
  layers: [
    { name: '用户层',     nodes: ['飞书 IM / 桌面 / 手机', 'Web Dashboard', 'MCP Client（Cursor / Claude Code）'] },
    { name: '接入层',     nodes: ['飞书 WebSocket 长连接', 'FastAPI HTTP', 'FastMCP（stdio + SSE）'] },
    { name: 'Agent Loop', nodes: ['Router', 'Smart Shield', 'Flow Detector', 'Context Recall', 'WorkReview'] },
    { name: '记忆层',     nodes: ['Working 200 条', 'Compaction · wU2', 'Archival（Bitable + Docx + JSONL）'] },
    { name: '安全层',     nodes: ['8 Gates · 借鉴 Claude Code 7-gate'] },
    { name: 'LLM 层',     nodes: ['火山方舟 Doubao Pro', 'Kimi K2.5', 'GLM-4.7'] },
    { name: '飞书生态',   nodes: ['IM · Bitable · Docx · Calendar · Task · Minutes · Wiki · Contact · Urgent'] },
  ],
  inspirations: [
    { from: 'Claude Code nO',       to: 'LarkMentor Agent Loop',  detail: '51 行主循环范式' },
    { from: 'Claude Code wU2',      to: 'FlowMemory 三层压缩',    detail: 'Working / Compaction / Archival' },
    { from: 'Claude Code 7-gate',   to: '8 层安全栈',             detail: '权限 → 注入 → Hook → PII → 词典 → 速率 → 沙箱 → 审计' },
    { from: 'Claude Code 6-tier MD', to: '6 级 flow_memory.md',    detail: 'Enterprise / Workspace / Department / Group / User / Session' },
  ],
};

/* --------------------------------------------------------------------------
 * Trust & Privacy
 * ----------------------------------------------------------------------- */
FG.privacy = [
  { icon: '🔐', title: '权限最小化',     desc: '只申请「IM 消息读 / 写 / 卡片」三类权限，不读群历史，不申请通讯录全量。' },
  { icon: '📍', title: '数据本地化',     desc: '所有用户画像 / 决策日志存 JSON 在企业自有服务器，不回传任何中央服务。' },
  { icon: '✂️', title: '正文不持久化',   desc: '仅存关键词样本片段（≤ 30 字），完整消息正文 24 小时后自动清理。' },
  { icon: '🪟', title: '决策可解释',     desc: '每条分类附 6 维评分卡，"为什么"一键展开，AI 不再是黑箱。' },
  { icon: '⏪', title: '用户可回滚',     desc: '不满意可一键改正，反馈进入发送方画像，形成"学习闭环"而非"单向投喂"。' },
  { icon: '🗑️', title: '一键删除',       desc: '"清除我的数据"二次确认后清空所有本人画像 / 决策 / 待办，符合 GDPR 思路。' },
];

/* --------------------------------------------------------------------------
 * 团队（核心，李洁盈完整 Jane Li 信息）
 * ----------------------------------------------------------------------- */
FG.team = [
  {
    order: '01',
    name: '李洁盈',
    enName: 'Jane Li',
    role: 'Product · Design · User Research',
    roleZh: '产品 / 设计 / 用户研究 / 演讲',
    eduPrimary: '深圳大学 BME · 在读',
    eduHighlight: '港科 TIE 全奖录取（2026 Incoming）',
    bio: '跨界 AI Builder。工科底子、产品与交互设计、AI 辅助原型、硬件协同与增长表达。在意人的情绪、体验与长期价值。',
    quote: '最好的产品应该像空气一样，被需要时就在手边，不被需要时完全隐形。',
    experiences: [
      { org: '弘火智能',  role: 'MoYa 硬件产品实习', detail: '柔性机器人 · 触觉安抚与睡眠陪伴 · 产品定义 / 打样迭代' },
      { org: '文石科技',  role: 'BooxReader 产品实习', detail: 'Reader 工具方向 · 市场定位 / P1-P3 优先级框架' },
      { org: 'Ponder AI', role: 'AI 研究工作台产品运营实习', detail: '内容种草 / 社群留存 / 反馈闭环' },
    ],
    achievements: ['百度秒哒优秀奖', '小红书 8.2w 赞与收藏', '全网 3w+ 粉丝沉淀', '国家级生物医学工程竞赛二等奖'],
    contributions: ['产品定位与场景设计', 'Rookie Buddy 新人辅导模块', '视频脚本与演讲', '用户访谈 SOP', '飞书云文档项目介绍'],
    links: [
      { label: 'Portfolio',   href: 'https://janeliii.netlify.app/',                         external: true },
      { label: '小红书 @李什么盈', href: 'https://www.xiaohongshu.com/user/profile',         external: true },
      { label: 'Email',       href: 'mailto:JieyingLiii@outlook.com',                       external: false },
    ],
  },
  {
    order: '02',
    name: '戴尚号',
    enName: 'Dai Shanghao',
    role: 'Engineering · Full-stack · Infra',
    roleZh: '技术负责人 / 全栈实现 / 主答辩',
    eduPrimary: '中国科学技术大学 · 硕士在读',
    eduHighlight: '2027 届 · 计算机方向',
    bio: '全栈开发。负责 LarkMentor 整体技术架构、飞书 API 集成、LLM 工程、自动化测试与阿里云 7×24 运维。',
    quote: '我们不展示飞书 API 的"调用能力"，我们让评委亲身体验飞书生态的"网络效应"。',
    experiences: [
      { org: 'LarkMentor',     role: '技术负责人', detail: '从零到一完成 v1 → v2 → v3 全部模块 · 5500+ 行代码' },
      { org: '阿里云 ECS',    role: 'DevOps',     detail: 'systemd 三件套 + Nginx + 7×24 守护 + LaTeX 编译流水线' },
      { org: '自动化测试',    role: 'QA 设计',    detail: '102 YAML 仿真器 + 33 pytest + 14 promptfoo 红队 + 30 项手工 SOP' },
    ],
    achievements: ['Anthropic Claude Code 架构源码深度阅读与移植', '8 层安全栈设计', 'MCP Server 三 transport 实现', '双 LaTeX 报告（10p + 45p）'],
    contributions: ['整体技术架构', 'FlowMemory 三层记忆系统', '8 层安全栈', 'MCP Server', '阿里云部署与运维', 'LaTeX 报告撰写', '自动化测试体系'],
    links: [
      { label: '个人主页',  href: 'https://bcefghj.github.io/',     external: true },
      { label: 'GitHub',    href: 'https://github.com/bcefghj',      external: true },
      { label: 'Email',     href: 'mailto:bcefghj@163.com',          external: false },
    ],
  },
];

FG.teamNarrative = '设计师懂工程师为什么要做 8 层安全；工程师懂设计师为什么要把恢复卡片做成卡片不做成纯文本。两个人，互补的能力，共同的判断：好产品不是炫技，是真正能让用户被理解。';

/* --------------------------------------------------------------------------
 * Resources 资源磁贴
 * ----------------------------------------------------------------------- */
FG.resources = [
  { icon: '📄', title: '10 页评审版 PDF',        href: 'http://118.178.242.26/dashboard',      note: '3 分钟读完核心', kind: 'doc' },
  { icon: '📚', title: '45 页技术深度报告',       href: 'http://118.178.242.26/dashboard',      note: '架构 / 算法 / 威胁模型', kind: 'doc' },
  { icon: '💻', title: 'GitHub 开源仓库',         href: 'https://github.com/bcefghj/larkmentor', note: 'MIT License', kind: 'code' },
  { icon: '📊', title: 'Live Dashboard',          href: 'http://118.178.242.26/dashboard',      note: '实时分类 / 热力图', kind: 'live' },
  { icon: '🔌', title: 'MCP Tools API',           href: 'http://118.178.242.26/mcp/tools',      note: '6 工具 · JSON Schema', kind: 'live' },
  { icon: '🌐', title: '飞书 AI 校园挑战赛',     href: 'https://bytedance.aiforce.cloud/app/app_4jv6kvy942afr', note: '官方报名页', kind: 'ext' },
  { icon: '🧑', title: '戴尚号 个人主页',         href: 'https://bcefghj.github.io/',           note: 'USTC · 全栈', kind: 'ext' },
  { icon: '✨', title: '李洁盈 Jane Li 个人站',   href: 'https://janeliii.netlify.app/',        note: '产品 / 设计', kind: 'ext' },
];

/* --------------------------------------------------------------------------
 * FAQ
 * ----------------------------------------------------------------------- */
FG.faq = [
  {
    q: 'LarkMentor 跟飞书原生勿扰、Slack AI 有什么不同？',
    a: '飞书勿扰会漏老板 P0；Slack AI 只做 thread 内总结，没跨群注意力。LarkMentor 在飞书原生层做"跨群智能挡 + 中断后恢复 + 三层企业记忆 + MCP 对外开放"四件事。',
  },
  {
    q: '隐私怎么保护？',
    a: '所有 LLM 调用前过 PII Scrubber（手机 / 身份证 / 邮箱 / open_id 7 类正则脱敏）；所有数据本地化；24 小时后清原文；只存分类标签 + Hash；审计日志 append-only。',
  },
  {
    q: '怎么部署到自己的飞书？',
    a: '一台 2 核 2G 服务器 + 一个飞书自建应用，clone 仓库 → 改 .env → bash deploy_v3.sh，全程幂等。完整步骤见 GitHub README。',
  },
  {
    q: '为什么要做 MCP Server？',
    a: '我们想让 LarkMentor 不只是 Bot，而是飞书生态的 Memory 中间件。Cursor / Claude Code / OpenClaw 用户接入后能直接询问"我现在在专注吗"、"本周做了什么"、"把这个发件人加白名单"。',
  },
  {
    q: '99% 准确率是真的吗？',
    a: '是 102 个 YAML 真实办公消息测试集上的成绩（自动化跑），不是灰测数据。配套的 33 例 pytest + 14 例 promptfoo 红队也全部通过。14 天真实用户灰测计划在评审窗口后启动。',
  },
];

/* --------------------------------------------------------------------------
 * 飞书聊天模拟器脚本（Demo 1）
 * ----------------------------------------------------------------------- */
FG.simScript = [
  {
    t: 0,
    type: 'system',
    text: '用户私聊 Bot："开始专注 90 分钟"',
    detail: 'LarkMentor 进入 Shield 状态，所有群消息开始走分流',
  },
  {
    t: 2.5,
    type: 'message',
    chat: '运维告警群',
    chatType: 'group',
    sender: '监控机器人',
    avatar: '🤖',
    text: '【告警】数据库主库 5xx 错误率 12% · 紧急处理',
    classify: { D1: 0.85, D2: 0.4, D3: 0.95, D4: 0.7, D5: 0.95, D6: 0.5, score: 0.79, level: 'P0', reason: '内容紧急 + 时间敏感' },
    action: 'forward_urgent',
    actionLabel: 'P0 加急推送',
  },
  {
    t: 7,
    type: 'message',
    chat: '产品评审群',
    chatType: 'group',
    sender: '张三 · PM',
    avatar: '👨‍💼',
    text: '@你 这个 Q3 方案给个意见',
    classify: { D1: 0.5, D2: 0.6, D3: 0.6, D4: 0.7, D5: 0.4, D6: 0.5, score: 0.56, level: 'P1', reason: '当前任务关联 + 同部门' },
    action: 'queue',
    actionLabel: 'P1 暂存',
  },
  {
    t: 11.5,
    type: 'message',
    chat: '部门闲聊群',
    chatType: 'group_large',
    sender: '李四',
    avatar: '🍔',
    text: '中午吃啥呀大家',
    classify: { D1: 0.5, D2: 0.3, D3: 0.1, D4: 0.05, D5: 0.3, D6: 0.2, score: 0.21, level: 'P3', reason: '大群闲聊 + 与任务无关' },
    action: 'archive',
    actionLabel: 'P3 静默',
  },
  {
    t: 16,
    type: 'message',
    chat: '王五 · 私聊',
    chatType: 'p2p',
    sender: '王五',
    avatar: '👨',
    text: '周报模板发我下',
    classify: { D1: 0.5, D2: 0.7, D3: 0.4, D4: 0.3, D5: 0.4, D6: 0.8, score: 0.50, level: 'P2', reason: '私聊 + 普通请求' },
    action: 'auto_reply',
    actionLabel: 'P2 代回复',
    autoReply: '🤖 我专注中，预计 1 小时后回。已为你登记，到点提醒我。',
  },
  {
    t: 22,
    type: 'message',
    chat: '老板 · 私聊',
    chatType: 'p2p',
    sender: '陈总',
    avatar: '👔',
    text: '今晚 8 点能开个 30 分钟的会吗',
    classify: { D1: 1.0, D2: 0.9, D3: 0.7, D4: 0.5, D5: 0.85, D6: 0.8, score: 0.81, level: 'P0', reason: '白名单 (上级) + 时间敏感' },
    action: 'forward_urgent',
    actionLabel: 'P0 白名单短路',
  },
  {
    t: 28,
    type: 'system',
    text: '用户敲 "结束专注"',
    detail: 'LarkMentor 调用 LLM 生成 Recovery Card',
  },
  {
    t: 30,
    type: 'recovery',
    title: '🌊 上下文恢复 · 你刚才被守护了 30 分钟',
    blocked: { p0: 2, p1: 1, p2: 1, p3: 1 },
    saved: 27,
    suggestions: [
      '🔴 立刻回陈总：8 点会议确认或改约',
      '🔴 跟进运维 5xx 告警是否已解决',
      '🟠 张三 Q3 方案：先看一遍再回，预计 15 分钟',
      '🟢 王五的周报模板已自动回复，完成',
    ],
    docLink: '已写入飞书云文档「LarkMentor 上下文恢复卡片」',
  },
];

/* --------------------------------------------------------------------------
 * 导航条
 * ----------------------------------------------------------------------- */
FG.nav = [
  { id: 'problem',  label: 'Problem' },
  { id: 'solution', label: 'Solution' },
  { id: 'demo-sim', label: 'Live Demo' },
  { id: 'demo-play', label: '试玩' },
  { id: 'engine',    label: 'Engine' },
  { id: 'demo-mcp',  label: 'MCP' },
  { id: 'security',  label: 'Security' },
  { id: 'team',      label: 'Team' },
];
