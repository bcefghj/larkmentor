/* SVG icon set · 全部内联，无外部依赖 */
window.FG = window.FG || {};

FG.icon = (name, size = 16) => {
  const lib = {
    arrow: '<path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    check: '<path d="M5 12l5 5L20 7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    play:  '<path d="M6 4l14 8-14 8V4z" fill="currentColor"/>',
    pause: '<path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="currentColor"/>',
    replay:'<path d="M3 12a9 9 0 109-9v4l-5-5 5-5" stroke="currentColor" stroke-width="2" fill="none"/>',
    step:  '<path d="M5 4v16M9 4l11 8-11 8V4z" fill="currentColor"/>',
    shield:'<path d="M12 2l9 4v6c0 5-3.5 9-9 10-5.5-1-9-5-9-10V6l9-4z" stroke="currentColor" stroke-width="1.6" fill="none"/>',
    brain: '<path d="M9 3a4 4 0 00-4 4v1a3 3 0 00-2 3 3 3 0 002 3 3 3 0 00.5 5A4 4 0 009 21h6a4 4 0 003.5-2 3 3 0 00.5-5 3 3 0 002-3 3 3 0 00-2-3V7a4 4 0 00-4-4H9z" stroke="currentColor" stroke-width="1.4" fill="none"/>',
    bolt:  '<path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round"/>',
    chat:  '<path d="M21 12a8 8 0 01-12 7l-5 1 1-4a8 8 0 1116-4z" stroke="currentColor" stroke-width="1.6" fill="none"/>',
    code:  '<path d="M8 6l-6 6 6 6M16 6l6 6-6 6M14 4l-4 16" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    layers:'<path d="M12 2l10 6-10 6L2 8l10-6zM2 16l10 6 10-6M2 12l10 6 10-6" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round"/>',
    lock:  '<rect x="4" y="11" width="16" height="11" rx="2" stroke="currentColor" stroke-width="1.6" fill="none"/><path d="M8 11V7a4 4 0 018 0v4" stroke="currentColor" stroke-width="1.6" fill="none"/>',
    sun:   '<circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8" fill="none"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" stroke="currentColor" stroke-width="1.8"/>',
    moon:  '<path d="M21 13a9 9 0 11-10-10 7 7 0 0010 10z" stroke="currentColor" stroke-width="1.6" fill="none"/>',
    github:'<path d="M12 2a10 10 0 00-3.16 19.49c.5.09.68-.22.68-.48 0-.24-.01-.87-.01-1.71-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.46-1.11-1.46-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.95 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.55 9.55 0 0112 6.8c.85 0 1.71.11 2.51.34 1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.85-2.34 4.7-4.57 4.94.36.31.68.92.68 1.85 0 1.34-.01 2.42-.01 2.75 0 .26.18.58.69.48A10 10 0 0012 2z" fill="currentColor"/>',
    external: '<path d="M14 5h5v5M19 5L10 14M19 14v5H5V5h5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    dot:   '<circle cx="12" cy="12" r="4" fill="currentColor"/>',
    feishu:'<rect x="3" y="3" width="18" height="18" rx="4" fill="#3370FF"/><path d="M8 12c0-2.2 1.8-4 4-4s4 1.8 4 4M8 16c0-1.1.9-2 2-2h4c1.1 0 2 .9 2 2" stroke="white" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
    spark: '<path d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l4 4M15 15l4 4M5 19l4-4M15 9l4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
  };
  const path = lib[name] || lib.dot;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display:inline-block;vertical-align:middle">${path}</svg>`;
};
