import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:webview_flutter/webview_flutter.dart';

import '../services/settings_service.dart';

/// Tiptap + Yjs collaborative document (P3.2).
///
/// Loads `assets/web_bridge/tiptap.html`, which opens a y-websocket
/// channel to the backend sync hub. This replaces the previous read-only
/// dashboard embed — now the Flutter client is a first-class editor that
/// can issue agent commands via `window.applyBridgeCommand`.
class DocView extends StatefulWidget {
  const DocView({super.key, this.room = "doc:default"});
  final String room;

  @override
  State<DocView> createState() => _DocViewState();
}

class _DocViewState extends State<DocView> {
  late final WebViewController _controller;
  String _status = "loading";
  List<Map<String, dynamic>> _peers = const [];
  bool _offlineReady = false;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    final html = await rootBundle.loadString('assets/web_bridge/tiptap.html');
    final cfg = jsonEncode({
      "wsUrl": SettingsService.instance.wsUrl,
      "room": widget.room,
      "user": {
        "name": SettingsService.instance.displayName,
        "color": "#1F6FEB",
      },
    });
    final injected = html.replaceFirst(
      '<head>',
      '<head>\n<script>window.__BRIDGE_CFG__ = $cfg;</script>',
    );
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFFFAFAF8))
      ..addJavaScriptChannel('Bridge',
          onMessageReceived: (m) => _onBridge(m.message))
      ..loadHtmlString(injected, baseUrl: 'https://larkmentor.local/');
    if (mounted) setState(() {});
  }

  void _onBridge(String payload) {
    try {
      final Map msg = jsonDecode(payload);
      switch (msg['type']) {
        case 'ws:status':
          setState(() => _status = (msg['payload']['status'] ?? '').toString());
          break;
        case 'awareness':
          final peers = (msg['payload']['peers'] as List?)?.cast<Map>() ?? [];
          setState(() => _peers = peers.map((m) => Map<String, dynamic>.from(m)).toList());
          break;
        case 'offline:loaded':
          setState(() => _offlineReady = true);
          break;
      }
    } catch (_) {}
  }

  Future<void> _insertTable() async {
    await _controller.runJavaScript(
        'window.applyBridgeCommand && window.applyBridgeCommand("insert_table", {"rows": 3, "cols": 3});');
  }

  Future<void> _insertImage() async {
    const demo = "https://placehold.co/640x320?text=LarkMentor";
    await _controller.runJavaScript(
        'window.applyBridgeCommand && window.applyBridgeCommand("insert_image", {"url": "$demo"});');
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        color: const Color(0xFFEDEDED),
        child: Row(children: [
          Icon(Icons.circle,
              size: 10,
              color: _status == 'connected'
                  ? Colors.green
                  : _status == 'offline'
                      ? Colors.red
                      : Colors.orange),
          const SizedBox(width: 6),
          Text('Tiptap 协同 · $_status',
              style: const TextStyle(fontSize: 12, color: Colors.black87)),
          const SizedBox(width: 10),
          if (_offlineReady)
            const Chip(
              label: Text('离线就绪', style: TextStyle(fontSize: 10)),
              visualDensity: VisualDensity.compact,
              backgroundColor: Color(0xFFDEF5DE),
            ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.table_chart, size: 18),
            onPressed: _insertTable, tooltip: '插入表格',
          ),
          IconButton(
            icon: const Icon(Icons.image, size: 18),
            onPressed: _insertImage, tooltip: '插入图片',
          ),
          if (_peers.isNotEmpty)
            Text('${_peers.length} 人在线',
                style: const TextStyle(fontSize: 11, color: Colors.black54)),
        ]),
      ),
      Expanded(child: WebViewWidget(controller: _controller)),
    ]);
  }
}
