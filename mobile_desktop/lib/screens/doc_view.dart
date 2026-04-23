import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../services/settings_service.dart';

/// Embeds the web dashboard's Doc editor view in a WebView.
/// Same Tiptap instance, same Yjs channel → the Flutter client is a
/// thin co-pilot of the canonical web editor.
class DocView extends StatefulWidget {
  const DocView({super.key});
  @override
  State<DocView> createState() => _DocViewState();
}

class _DocViewState extends State<DocView> {
  late final WebViewController _controller;

  @override
  void initState() {
    super.initState();
    final url = '${SettingsService.instance.backendUrl}/dashboard/pilot';
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..loadRequest(Uri.parse(url));
  }

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _controller);
}
