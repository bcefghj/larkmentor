# web_bundle · 本地离线 tldraw + Tiptap + Yjs bundle

这个目录存放 Vite 构建好的离线 bundle，取代 v3 从 esm.sh 在线加载的 tldraw.html/tiptap.html。

## 构建方法

```bash
cd mobile_desktop/web_bundle
npm install
npm run build
# → 产物到 ./dist/{canvas,doc}.html 和 ./dist/assets/*.{js,css}
```

## 使用方式

Flutter WebView 加载 `assets/web_bundle/dist/canvas.html`（flutter_inappwebview 支持 file:// 或者直接加载 asset path）。

## 必须的包

- `yjs` - CRDT 核心
- `y-websocket` - y-websocket 客户端
- `y-indexeddb` - 离线持久化（关键！飞行模式可用）
- `tldraw` - 白板
- `@tiptap/core` + `@tiptap/starter-kit` + `@tiptap/extension-collaboration` - 文档
- `@tiptap/extension-collaboration-cursor` - 光标可视化

## 飞行模式

- y-indexeddb 在本地 IndexedDB 缓存所有操作
- 断网编辑 → 本地可用
- 联网后 y-websocket 自动 resync → CRDT 合并无冲突
