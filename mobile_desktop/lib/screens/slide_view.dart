import 'package:flutter/material.dart';

import '../services/api_service.dart';

/// Native PPT rehearsal view: reads the Slidev outline the backend
/// generated and turns each page into a full-screen slide with
/// speaker notes drawer. Supports swipe to advance.
class SlideView extends StatefulWidget {
  const SlideView({super.key});
  @override
  State<SlideView> createState() => _SlideViewState();
}

class _SlideViewState extends State<SlideView> {
  List<Map<String, dynamic>> _outline = [];
  List<Map<String, dynamic>> _notes = [];
  int _page = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final plans = await ApiService.instance.listPlans(limit: 3);
    for (final p in plans) {
      final detail = await ApiService.instance.getPlan(p['plan_id'].toString());
      if (detail == null) continue;
      for (final s in (detail['steps'] as List?) ?? []) {
        final m = s as Map;
        if (m['tool'] == 'slide.generate') {
          final out = ((m['result'] as Map?)?['outline'] as List?)?.cast<Map>() ?? [];
          if (out.isNotEmpty) {
            setState(() => _outline = out.map((e) => Map<String, dynamic>.from(e)).toList());
          }
        }
        if (m['tool'] == 'slide.rehearse') {
          final nts =
              ((m['result'] as Map?)?['speaker_notes'] as List?)?.cast<Map>() ?? [];
          if (nts.isNotEmpty) {
            setState(() => _notes = nts.map((e) => Map<String, dynamic>.from(e)).toList());
          }
        }
      }
      if (_outline.isNotEmpty) return;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_outline.isEmpty) {
      return const Center(child: Text('尚未生成演示稿，先触发一次 /pilot。'));
    }
    final p = _outline[_page];
    final note = _page < _notes.length ? _notes[_page]['speaker_note']?.toString() ?? '' : '';
    return Column(children: [
      Expanded(
        child: GestureDetector(
          onHorizontalDragEnd: (d) {
            if (d.primaryVelocity == null) return;
            if (d.primaryVelocity! < 0 && _page < _outline.length - 1) {
              setState(() => _page++);
            } else if (d.primaryVelocity! > 0 && _page > 0) {
              setState(() => _page--);
            }
          },
          child: Container(
            color: const Color(0xFF0D1117),
            padding: const EdgeInsets.all(48),
            alignment: Alignment.center,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(p['title']?.toString() ?? '',
                    style: const TextStyle(fontSize: 36, fontWeight: FontWeight.bold)),
                const SizedBox(height: 24),
                for (final b in ((p['bullets'] as List?) ?? []))
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Text('• $b', style: const TextStyle(fontSize: 20)),
                  ),
              ],
            ),
          ),
        ),
      ),
      if (note.isNotEmpty)
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          color: const Color(0xFF161B22),
          child: Text('🎤 ${note}', style: const TextStyle(color: Colors.white70)),
        ),
      Padding(
        padding: const EdgeInsets.all(8),
        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          IconButton(
              icon: const Icon(Icons.chevron_left),
              onPressed: _page > 0 ? () => setState(() => _page--) : null),
          Text('${_page + 1} / ${_outline.length}'),
          IconButton(
              icon: const Icon(Icons.chevron_right),
              onPressed: _page < _outline.length - 1
                  ? () => setState(() => _page++)
                  : null),
        ]),
      ),
    ]);
  }
}
