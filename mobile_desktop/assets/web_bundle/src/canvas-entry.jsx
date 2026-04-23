// LarkMentor v4 · Canvas Entry (tldraw + Yjs 真协同 + IndexedDB 离线)
import React, { useEffect, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { Tldraw, useEditor } from 'tldraw';
import 'tldraw/tldraw.css';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';
import { IndexeddbPersistence } from 'y-indexeddb';

function getConfig() {
  const params = new URLSearchParams(window.location.search);
  const flutterCfg = window.LARKMENTOR_CONFIG || {};
  return {
    wsUrl: params.get('wsUrl') || flutterCfg.wsUrl || 'ws://127.0.0.1:8002',
    roomId: params.get('room') || flutterCfg.roomId || 'default-canvas',
    displayName: params.get('name') || flutterCfg.displayName || 'anon',
    color: params.get('color') || '#3b82f6',
  };
}

function Bridge({ room }) {
  const editor = useEditor();
  useEffect(() => {
    if (!editor) return;
    // Expose a command handler for Flutter to call
    window.larkmentor = window.larkmentor || {};
    window.larkmentor.applyCommand = (cmd) => {
      try {
        if (cmd.kind === 'insert_shape') {
          editor.createShapes([{ type: cmd.shape || 'geo', x: cmd.x || 100, y: cmd.y || 100, props: cmd.props || { geo: 'rectangle', w: 160, h: 80 } }]);
        } else if (cmd.kind === 'add_sticky') {
          editor.createShapes([{ type: 'note', x: cmd.x || 200, y: cmd.y || 200, props: { text: cmd.text || '' } }]);
        }
      } catch (e) {
        postStatus('command_failed: ' + e.message);
      }
    };
  }, [editor]);
  return null;
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

function App() {
  const cfg = getConfig();
  const [ready, setReady] = useState(false);
  const docRef = useRef(null);

  useEffect(() => {
    const doc = new Y.Doc();
    docRef.current = doc;

    // L1: IndexedDB persistence (本地离线持久化)
    const idb = new IndexeddbPersistence(`larkmentor-canvas-${cfg.roomId}`, doc);
    idb.on('synced', () => postStatus('🟢 本地离线缓存已同步'));

    // L2: WebSocket for真协同
    const ws = new WebsocketProvider(cfg.wsUrl, cfg.roomId, doc, { connect: true });
    ws.on('status', (ev) => {
      const icon = ev.status === 'connected' ? '🟢' : (ev.status === 'connecting' ? '🟡' : '🔴');
      postStatus(`${icon} ${ev.status} · room=${cfg.roomId}`);
    });
    ws.awareness.setLocalStateField('user', {
      name: cfg.displayName,
      color: cfg.color,
    });
    ws.awareness.on('change', () => {
      const others = [...ws.awareness.getStates().values()].filter(s => s.user && s.user.name !== cfg.displayName);
      postStatus(`🟢 同步中 · 在线 ${others.length + 1} 人`);
    });

    setReady(true);
    return () => {
      ws.destroy();
      idb.destroy();
    };
  }, []);

  if (!ready) return <div style={{ padding: 24 }}>初始化中…</div>;
  return (
    <Tldraw persistenceKey={`canvas-${cfg.roomId}`}>
      <Bridge room={cfg.roomId} />
    </Tldraw>
  );
}

createRoot(document.getElementById('root')).render(<App />);
