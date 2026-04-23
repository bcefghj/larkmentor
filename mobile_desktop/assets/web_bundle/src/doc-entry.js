// LarkMentor v4 · Doc Entry (Tiptap + Yjs 真协同 + IndexedDB 离线)
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Collaboration from '@tiptap/extension-collaboration';
import CollaborationCursor from '@tiptap/extension-collaboration-cursor';
import Image from '@tiptap/extension-image';
import Table from '@tiptap/extension-table';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';
import { IndexeddbPersistence } from 'y-indexeddb';

function getConfig() {
  const params = new URLSearchParams(window.location.search);
  const flutterCfg = window.LARKMENTOR_CONFIG || {};
  return {
    wsUrl: params.get('wsUrl') || flutterCfg.wsUrl || 'ws://127.0.0.1:8002',
    roomId: params.get('room') || flutterCfg.roomId || 'default-doc',
    displayName: params.get('name') || flutterCfg.displayName || 'anon',
    color: params.get('color') || '#10b981',
  };
}

function postStatus(msg) {
  try {
    if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
      window.flutter_inappwebview.callHandler('bridge', { kind: 'status', message: msg });
    }
  } catch (e) {}
  const bar = document.getElementById('status-bar');
  if (bar) bar.textContent = msg;
}

const cfg = getConfig();
const doc = new Y.Doc();

// L1: IndexedDB persistence
const idb = new IndexeddbPersistence(`larkmentor-doc-${cfg.roomId}`, doc);
idb.on('synced', () => postStatus('🟢 本地离线缓存已同步'));

// L2: WebSocket 真协同
const ws = new WebsocketProvider(cfg.wsUrl, cfg.roomId, doc, { connect: true });
ws.on('status', (ev) => {
  const icon = ev.status === 'connected' ? '🟢' : (ev.status === 'connecting' ? '🟡' : '🔴');
  postStatus(`${icon} ${ev.status} · room=${cfg.roomId}`);
});

const editor = new Editor({
  element: document.getElementById('root'),
  extensions: [
    StarterKit.configure({ history: false }),  // Yjs handles history
    Collaboration.configure({ document: doc }),
    CollaborationCursor.configure({
      provider: ws,
      user: { name: cfg.displayName, color: cfg.color },
    }),
    Image,
    Table.configure({ resizable: true }),
  ],
  content: '',
});

// Expose commands for Flutter
window.larkmentor = window.larkmentor || {};
window.larkmentor.applyCommand = (cmd) => {
  try {
    if (cmd.kind === 'insert_image') {
      editor.chain().focus().setImage({ src: cmd.src }).run();
    } else if (cmd.kind === 'insert_table') {
      editor.chain().focus().insertTable({ rows: cmd.rows || 3, cols: cmd.cols || 3 }).run();
    } else if (cmd.kind === 'set_content') {
      editor.commands.setContent(cmd.html || '');
    }
  } catch (e) {
    postStatus('command_failed: ' + e.message);
  }
};
