import React, { useEffect, useState, useRef, useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import { Tldraw, createTLStore, defaultShapeUtils, useEditor } from 'tldraw';
import 'tldraw/tldraw.css';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';
import { IndexeddbPersistence } from 'y-indexeddb';

const DEBOUNCE_MS = 120;

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
          editor.createShapes([{
            type: cmd.shape || 'geo',
            x: cmd.x || 100, y: cmd.y || 100,
            props: cmd.props || { geo: 'rectangle', w: 160, h: 80 },
          }]);
        } else if (cmd.kind === 'add_sticky') {
          editor.createShapes([{
            type: 'note',
            x: cmd.x || 200, y: cmd.y || 200,
            props: { text: cmd.text || '' },
          }]);
        }
      } catch (e) {
        postStatus('command_failed: ' + e.message, 'error');
      }
    };
  }, [editor]);
  return null;
}

function postStatus(msg, level = 'info') {
  try {
    if (window.flutter_inappwebview?.callHandler) {
      window.flutter_inappwebview.callHandler('bridge', { kind: 'status', message: msg, level });
    }
    if (window.Bridge?.postMessage) {
      window.Bridge.postMessage(JSON.stringify({ type: 'status', payload: { message: msg, level } }));
    }
  } catch (_) {}
  const bar = document.getElementById('status-bar');
  if (bar) bar.textContent = msg;
}

/* ── Connection status indicator overlay ── */
function ConnectionStatus({ wsStatus, peerCount, idbSynced }) {
  const color =
    wsStatus === 'connected' ? '#22c55e' :
    wsStatus === 'connecting' ? '#f59e0b' : '#ef4444';
  const label =
    wsStatus === 'connected' ? `sync · ${peerCount} online` :
    wsStatus === 'connecting' ? 'connecting...' : 'offline';

  return (
    <div style={{
      position: 'fixed', top: 8, right: 12, zIndex: 9999,
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 6,
      background: 'rgba(0,0,0,0.6)', color: '#E6EDF3',
      font: '12px/1.4 -apple-system, system-ui, sans-serif',
      pointerEvents: 'none',
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: color, display: 'inline-block',
        boxShadow: `0 0 4px ${color}`,
      }} />
      <span>{label}</span>
      {idbSynced && wsStatus !== 'connected' && (
        <span style={{ opacity: 0.7, marginLeft: 4 }}>(local cache OK)</span>
      )}
    </div>
  );
}

function App() {
  const cfg = getConfig();
  const [store, setStore] = useState(null);
  const providerRef = useRef(null);
  const [wsStatus, setWsStatus] = useState('connecting');
  const [peerCount, setPeerCount] = useState(1);
  const [idbSynced, setIdbSynced] = useState(false);

  useEffect(() => {
    const doc = new Y.Doc();
    const tlStore = createTLStore({ shapeUtils: defaultShapeUtils });
    const yShapes = doc.getMap('tl.shapes');

    /* Track previous key set for incremental diff */
    let prevKeys = new Set();
    let flushTimer = null;

    const flushIncremental = () => {
      const snapshot = tlStore.getSnapshot();
      const currentEntries = Object.entries(snapshot.store);
      const currentKeys = new Set(currentEntries.map(([k]) => k));

      doc.transact(() => {
        for (const key of prevKeys) {
          if (!currentKeys.has(key)) yShapes.delete(key);
        }
        for (const [id, rec] of currentEntries) {
          const existing = yShapes.get(id);
          if (!existing || JSON.stringify(existing) !== JSON.stringify(rec)) {
            yShapes.set(id, rec);
          }
        }
      }, 'local');

      prevKeys = currentKeys;
    };

    const debouncedFlush = () => {
      if (flushTimer) clearTimeout(flushTimer);
      flushTimer = setTimeout(flushIncremental, DEBOUNCE_MS);
    };

    const applyFromY = () => {
      const snap = { store: {}, schema: tlStore.schema.serialize() };
      yShapes.forEach((v, k) => (snap.store[k] = v));
      if (Object.keys(snap.store).length) {
        tlStore.loadSnapshot(snap);
        prevKeys = new Set(Object.keys(snap.store));
      }
    };

    yShapes.observe((e) => { if (e.transaction.origin !== 'local') applyFromY(); });
    tlStore.listen(debouncedFlush, { source: 'user', scope: 'document' });

    // L1: IndexedDB offline persistence
    const idb = new IndexeddbPersistence(`agent-pilot-canvas-${cfg.roomId}`, doc);
    idb.on('synced', () => {
      setIdbSynced(true);
      postStatus('local cache synced');
    });

    // L2: WebSocket collaboration
    const ws = new WebsocketProvider(cfg.wsUrl, cfg.roomId, doc, { connect: true });
    ws.on('status', (ev) => {
      setWsStatus(ev.status);
      postStatus(`${ev.status} · room=${cfg.roomId}`);
    });
    ws.awareness.setLocalStateField('user', { name: cfg.displayName, color: cfg.color });
    ws.awareness.on('change', () => {
      const states = [...ws.awareness.getStates().values()];
      const others = states.filter(s => s.user && s.user.name !== cfg.displayName);
      setPeerCount(others.length + 1);
    });
    providerRef.current = ws;

    setStore(tlStore);
    return () => {
      if (flushTimer) clearTimeout(flushTimer);
      ws.destroy();
      idb.destroy();
    };
  }, []);

  if (!store) return <div style={{ padding: 24, color: '#aaa' }}>initializing...</div>;
  return (
    <>
      <ConnectionStatus wsStatus={wsStatus} peerCount={peerCount} idbSynced={idbSynced} />
      <Tldraw
        store={store}
        onMount={(editor) => {
          if (providerRef.current) {
            editor.on('change-cursor', (c) =>
              providerRef.current.awareness.setLocalStateField('cursor', c));
          }
          postStatus('canvas mounted');
        }}
      >
        <Bridge />
      </Tldraw>
    </>
  );
}

createRoot(document.getElementById('root')).render(<App />);

// Signal to the bridge HTML that the local bundle is ready
window.__CANVAS_READY__ = true;
