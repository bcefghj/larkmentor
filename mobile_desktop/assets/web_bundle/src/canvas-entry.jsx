import React, { useEffect, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { Tldraw, createTLStore, defaultShapeUtils, useEditor } from 'tldraw';
import 'tldraw/tldraw.css';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';
import { IndexeddbPersistence } from 'y-indexeddb';

function getConfig() {
  const params = new URLSearchParams(window.location.search);
  const flutterCfg = window.AGENT_PILOT_CONFIG || {};
  return {
    wsUrl: params.get('wsUrl') || flutterCfg.wsUrl || 'ws://127.0.0.1:8002',
    roomId: params.get('room') || flutterCfg.roomId || 'default-canvas',
    displayName: params.get('name') || flutterCfg.displayName || 'anon',
    color: params.get('color') || '#3b82f6',
  };
}

function Bridge() {
  const editor = useEditor();
  useEffect(() => {
    if (!editor) return;
    window.agentPilot = window.agentPilot || {};
    window.agentPilot.applyCommand = (cmd) => {
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
    if (window.Bridge && window.Bridge.postMessage) {
      window.Bridge.postMessage(JSON.stringify({ type: 'status', payload: { message: msg } }));
    }
  } catch (_) {}
  const bar = document.getElementById('status-bar');
  if (bar) bar.textContent = msg;
}

function App() {
  const cfg = getConfig();
  const [store, setStore] = useState(null);
  const providerRef = useRef(null);

  useEffect(() => {
    const doc = new Y.Doc();
    const tlStore = createTLStore({ shapeUtils: defaultShapeUtils });
    const yShapes = doc.getMap('tl.shapes');

    const flushToY = () => {
      const snapshot = tlStore.getSnapshot();
      doc.transact(() => {
        yShapes.clear();
        for (const [id, rec] of Object.entries(snapshot.store)) {
          yShapes.set(id, rec);
        }
      }, 'local');
    };

    const applyFromY = () => {
      const snap = { store: {}, schema: tlStore.schema.serialize() };
      yShapes.forEach((v, k) => (snap.store[k] = v));
      if (Object.keys(snap.store).length) tlStore.loadSnapshot(snap);
    };

    yShapes.observe((e) => { if (e.transaction.origin !== 'local') applyFromY(); });
    tlStore.listen(flushToY, { source: 'user', scope: 'document' });

    const idb = new IndexeddbPersistence(`agent-pilot-canvas-${cfg.roomId}`, doc);
    idb.on('synced', () => postStatus('🟢 本地离线缓存已同步'));

    const ws = new WebsocketProvider(cfg.wsUrl, cfg.roomId, doc, { connect: true });
    ws.on('status', (ev) => {
      const icon = ev.status === 'connected' ? '🟢' : (ev.status === 'connecting' ? '🟡' : '🔴');
      postStatus(`${icon} ${ev.status} · room=${cfg.roomId}`);
    });
    ws.awareness.setLocalStateField('user', { name: cfg.displayName, color: cfg.color });
    ws.awareness.on('change', () => {
      const others = [...ws.awareness.getStates().values()].filter(s => s.user && s.user.name !== cfg.displayName);
      postStatus(`🟢 同步中 · 在线 ${others.length + 1} 人`);
    });
    providerRef.current = ws;

    setStore(tlStore);
    return () => {
      ws.destroy();
      idb.destroy();
    };
  }, []);

  if (!store) return <div style={{ padding: 24 }}>初始化中…</div>;
  return (
    <Tldraw
      store={store}
      onMount={(editor) => {
        if (providerRef.current) {
          editor.on('change-cursor', (c) =>
            providerRef.current.awareness.setLocalStateField('cursor', c));
        }
        postStatus('🟢 画布已加载');
      }}
    >
      <Bridge />
    </Tldraw>
  );
}

createRoot(document.getElementById('root')).render(<App />);
