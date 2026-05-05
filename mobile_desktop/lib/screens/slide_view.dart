import 'package:flutter/material.dart';

import '../services/api_service.dart';

/// Native PPT rehearsal view: reads the Slidev outline the backend
/// generated and turns each page into a full-screen slide with
/// speaker notes drawer. Supports swipe to advance.
///
/// v12: accepts an optional [planId] to bind to a specific plan
/// rather than scanning recent plans.
class SlideView extends StatefulWidget {
  final String? planId;
  const SlideView({super.key, this.planId});
  @override
  State<SlideView> createState() => _SlideViewState();
}

class _SlideViewState extends State<SlideView> {
  List<Map<String, dynamic>> _outline = [];
  List<Map<String, dynamic>> _notes = [];
  int _page = 0;
  bool _loading = true;
  String? _error;
  String? _boundPlanId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      if (widget.planId != null && widget.planId!.isNotEmpty) {
        await _loadPlan(widget.planId!);
      } else {
        await _loadFromRecent();
      }
    } catch (e) {
      setState(() => _error = '加载失败: $e');
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _loadPlan(String planId) async {
    final detail = await ApiService.instance.getPlan(planId);
    if (detail == null) {
      setState(() => _error = '计划 $planId 未找到');
      return;
    }
    _boundPlanId = planId;
    _extractSlideData(detail);
  }

  Future<void> _loadFromRecent() async {
    final plans = await ApiService.instance.listPlans(limit: 5);
    for (final p in plans) {
      final detail = await ApiService.instance.getPlan(p['plan_id'].toString());
      if (detail == null) continue;
      _extractSlideData(detail);
      if (_outline.isNotEmpty) {
        _boundPlanId = p['plan_id'].toString();
        return;
      }
    }
    if (_outline.isEmpty) {
      setState(() => _error = '尚未生成演示稿，先触发一次 /pilot。');
    }
  }

  void _extractSlideData(Map<String, dynamic> detail) {
    for (final s in (detail['steps'] as List?) ?? []) {
      final m = s as Map;
      if (m['tool'] == 'slide.generate') {
        final out = ((m['result'] as Map?)?['outline'] as List?)?.cast<Map>() ?? [];
        if (out.isNotEmpty) {
          setState(() => _outline = out.map((e) => Map<String, dynamic>.from(e)).toList());
        }
      }
      if (m['tool'] == 'slide.rehearse') {
        final nts = ((m['result'] as Map?)?['speaker_notes'] as List?)?.cast<Map>() ?? [];
        if (nts.isNotEmpty) {
          setState(() => _notes = nts.map((e) => Map<String, dynamic>.from(e)).toList());
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.slideshow_outlined, size: 64, color: Colors.white30),
            const SizedBox(height: 16),
            Text(_error!, style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              label: const Text('重新加载'),
            ),
          ],
        ),
      );
    }
    if (_outline.isEmpty) {
      return const Center(child: Text('尚未生成演示稿，先触发一次 /pilot。'));
    }
    final p = _outline[_page];
    final note = _page < _notes.length ? _notes[_page]['speaker_note']?.toString() ?? '' : '';
    return Column(children: [
      if (_boundPlanId != null)
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          color: const Color(0xFF161B22),
          child: Text(
            'Plan: ${_boundPlanId!.length > 8 ? _boundPlanId!.substring(_boundPlanId!.length - 8) : _boundPlanId}',
            style: const TextStyle(color: Colors.white38, fontSize: 11),
          ),
        ),
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
          child: Text('🎤 $note', style: const TextStyle(color: Colors.white70)),
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
