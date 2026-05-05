import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:webview_flutter/webview_flutter.dart';

import '../services/settings_service.dart';

/// Real-collab canvas view (P3.1).
///
/// Loads `assets/web_bridge/tldraw.html` into a WebView; the HTML bundle
/// binds a tldraw editor to a Yjs document backed by `y-websocket`
/// against the backend `/sync/ws` hub, and `y-indexeddb` for offline
/// persistence. Awareness (peer cursors + presence) is surfaced back to
/// Flutter via a postMessage bridge so the status chip shows who else is
/// editing.
class CanvasView extends StatefulWidget {
  const CanvasView({super.key, this.planId = "default"});
  final String planId;

  String get room => "canvas:$planId";

  @override
  State<CanvasView> createState() => _CanvasViewState();
}

class _CanvasViewState extends State<CanvasView> {
  late final WebViewController _controller;
  final List<Map<String, dynamic>> _peers = [];
  String _wsStatus = "init";
  bool _offlineLoaded = false;
  VoidCallback? _settingsListener;

  @override
  void initState() {
    super.initState();
    _bootstrap();
    _settingsListener = () => _reload();
    SettingsService.instance.addChangeListener(_settingsListener!);
  }

  @override
  void didUpdateWidget(covariant CanvasView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.planId != widget.planId) {
      _reload();
    }
  }

  @override
  void dispose() {
    if (_settingsListener != null) {
      SettingsService.instance.removeChangeListener(_settingsListener!);
    }
    super.dispose();
  }

  Future<void> _bootstrap() async {
    final html = await rootBundle.loadString('assets/web_bridge/tldraw.html');
    final wsUrl = SettingsService.instance.wsUrl;
    final user = {
      "name": SettingsService.instance.displayName,
      "color": "#58A6FF",
    };
    final cfgJson = jsonEncode({
      "wsUrl": wsUrl,
      "room": widget.room,
      "user": user,
    });
    final injected = html.replaceFirst(
      '<head>',
      '<head>\n<script>window.__BRIDGE_CFG__ = $cfgJson;</script>',
    );

    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF1F252E))
      ..addJavaScriptChannel('Bridge',
          onMessageReceived: (m) => _onBridge(m.message))
      ..loadHtmlString(injected, baseUrl: 'https://agent-pilot.local/');
    if (mounted) setState(() {});
  }

  Future<void> _reload() async {
    try {
      final html = await rootBundle.loadString('assets/web_bridge/tldraw.html');
      final cfgJson = jsonEncode({
        "wsUrl": SettingsService.instance.wsUrl,
        "room": widget.room,
        "user": {
          "name": SettingsService.instance.displayName,
          "color": "#58A6FF",
        },
      });
      final injected = html.replaceFirst(
        '<head>',
        '<head>\n<script>window.__BRIDGE_CFG__ = $cfgJson;</script>',
      );
      await _controller.loadHtmlString(injected, baseUrl: 'https://agent-pilot.local/');
    } catch (e) {
      debugPrint('CanvasView reload failed: $e');
    }
  }

  void _onBridge(String payload) {
    try {
      final Map msg = jsonDecode(payload);
      switch (msg['type']) {
        case 'ws:status':
          setState(() => _wsStatus = (msg['payload']['status'] ?? '').toString());
          break;
        case 'awareness':
          final peers = (msg['payload']['peers'] as List?)?.cast<Map>() ?? [];
          setState(() {
            _peers
              ..clear()
              ..addAll(peers.map((m) => Map<String, dynamic>.from(m)));
          });
          break;
        case 'offline:loaded':
          setState(() => _offlineLoaded = true);
          break;
        case 'net:offline':
          setState(() => _wsStatus = 'offline');
          break;
        case 'net:online':
          setState(() => _wsStatus = 'reconnecting');
          break;
      }
    } catch (e) {
      debugPrint('CanvasView bridge decode error: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      _StatusBar(
        wsStatus: _wsStatus,
        peers: _peers,
        offlineReady: _offlineLoaded,
        onReload: _reload,
      ),
      Expanded(
        child: WebViewWidget(controller: _controller),
      ),
    ]);
  }
}

class _StatusBar extends StatelessWidget {
  const _StatusBar({
    required this.wsStatus,
    required this.peers,
    required this.offlineReady,
    required this.onReload,
  });
  final String wsStatus;
  final List<Map<String, dynamic>> peers;
  final bool offlineReady;
  final VoidCallback onReload;

  @override
  Widget build(BuildContext context) {
    final color = wsStatus == 'connected'
        ? Colors.green
        : wsStatus == 'offline'
            ? Colors.red
            : Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      color: const Color(0xFF252C38),
      child: Row(children: [
        Icon(Icons.circle, color: color, size: 10),
        const SizedBox(width: 6),
        Text('实时协同 · $wsStatus',
            style: const TextStyle(color: Color(0xFFE6EDF3), fontSize: 12)),
        const SizedBox(width: 16),
        if (offlineReady)
          const Chip(
            label: Text('离线可编辑', style: TextStyle(color: Colors.white, fontSize: 11)),
            backgroundColor: Color(0xFF238636),
            visualDensity: VisualDensity.compact,
            padding: EdgeInsets.zero,
          ),
        const Spacer(),
        ...peers.take(5).map((p) => Padding(
              padding: const EdgeInsets.only(right: 6),
              child: Tooltip(
                message: p['name']?.toString() ?? 'peer',
                child: CircleAvatar(
                  radius: 10,
                  backgroundColor: Color(int.tryParse(
                          (p['color']?.toString() ?? '#58A6FF').replaceFirst('#', 'FF'),
                          radix: 16) ??
                      0xFF58A6FF),
                  child: Text(
                    (p['name']?.toString().isNotEmpty ?? false)
                        ? p['name'].toString().substring(0, 1)
                        : '?',
                    style: const TextStyle(color: Colors.white, fontSize: 10),
                  ),
                ),
              ),
            )),
        if (peers.length > 5)
          Text('+${peers.length - 5}',
              style: const TextStyle(color: Color(0xFF8B949E), fontSize: 12)),
        IconButton(
          onPressed: onReload,
          icon: const Icon(Icons.refresh, color: Color(0xFF8B949E), size: 18),
          visualDensity: VisualDensity.compact,
          tooltip: '重连',
        ),
      ]),
    );
  }
}
