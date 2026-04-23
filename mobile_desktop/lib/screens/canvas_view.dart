import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../services/api_service.dart';
import '../services/settings_service.dart';
import '../services/sync_service.dart';

/// Native rendering of the tldraw scene that `canvas_tool.py` emits.
/// We do NOT embed tldraw itself here (Flutter doesn't have a native
/// tldraw port yet) — instead we render the scene's shape list with
/// CustomPaint. This mirrors the same JSON the Web + Feishu Board use.
class CanvasView extends StatefulWidget {
  const CanvasView({super.key});
  @override
  State<CanvasView> createState() => _CanvasViewState();
}

class _CanvasViewState extends State<CanvasView> {
  Map<String, dynamic>? _scene;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _loadLatest();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _loadLatest());
    SyncService.instance.stream.listen((msg) {
      final state = msg['state'];
      if (state is Map && state['type'] == 'canvas.shape_added') {
        _loadLatest();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadLatest() async {
    try {
      final plans = await ApiService.instance.listPlans(limit: 3);
      for (final p in plans) {
        final detail = await ApiService.instance.getPlan(p['plan_id'].toString());
        if (detail == null) continue;
        for (final s in (detail['steps'] as List?) ?? []) {
          final r = (s as Map)['result'] as Map?;
          if (r == null) continue;
          final id = r['canvas_id']?.toString();
          if (id != null) {
            final uri = Uri.parse(
                '${SettingsService.instance.backendUrl}/artifacts/$id.json');
            try {
              final resp = await http.get(uri).timeout(const Duration(seconds: 5));
              if (resp.statusCode == 200) {
                setState(() => _scene = jsonDecode(resp.body));
                return;
              }
            } catch (_) {}
          }
        }
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final scene = _scene;
    if (scene == null) {
      return const Center(child: Text('尚无画布。先在 IM 或 Web 端触发 /pilot。'));
    }
    final shapes = (scene['shapes'] as List?)?.cast<Map>() ?? const [];
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(8),
        child: Text('${scene['title']} · v${scene['version']} · ${shapes.length} 个形状',
            style: Theme.of(context).textTheme.labelLarge),
      ),
      Expanded(
        child: Center(
          child: InteractiveViewer(
            minScale: 0.3,
            maxScale: 3,
            child: CustomPaint(
              size: const Size(900, 600),
              painter: _ScenePainter(shapes),
            ),
          ),
        ),
      ),
    ]);
  }
}

class _ScenePainter extends CustomPainter {
  _ScenePainter(this.shapes);
  final List<Map> shapes;

  @override
  void paint(Canvas canvas, Size size) {
    final bg = Paint()..color = const Color(0xFF1F252E);
    canvas.drawRect(Offset.zero & size, bg);
    final node = Paint()
      ..color = const Color(0xFF58A6FF)
      ..style = PaintingStyle.fill;
    final stroke = Paint()
      ..color = const Color(0xFFE6EDF3)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;

    for (final s in shapes) {
      final x = (s['x'] as num?)?.toDouble() ?? 0;
      final y = (s['y'] as num?)?.toDouble() ?? 0;
      final w = (s['w'] as num?)?.toDouble() ?? 120;
      final h = (s['h'] as num?)?.toDouble() ?? 60;
      final type = s['type']?.toString() ?? 'node';
      final rect = Rect.fromLTWH(x, y, w, h);

      if (type == 'arrow') {
        canvas.drawLine(rect.centerLeft, rect.centerRight, stroke);
      } else if (type == 'frame') {
        canvas.drawRect(rect, stroke);
      } else {
        canvas.drawRRect(
            RRect.fromRectAndRadius(rect, const Radius.circular(6)), node);
        canvas.drawRRect(
            RRect.fromRectAndRadius(rect, const Radius.circular(6)), stroke);
      }
      final text = s['text']?.toString() ?? '';
      if (text.isNotEmpty) {
        final tp = TextPainter(
          text: TextSpan(text: text, style: const TextStyle(color: Colors.white, fontSize: 14)),
          textDirection: TextDirection.ltr,
        )..layout(maxWidth: w);
        tp.paint(canvas, Offset(x + (w - tp.width) / 2, y + (h - tp.height) / 2));
      }
    }
  }

  @override
  bool shouldRepaint(_ScenePainter oldDelegate) => oldDelegate.shapes != shapes;
}
