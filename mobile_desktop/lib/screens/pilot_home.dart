import 'dart:async';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/api_service.dart';
import '../services/sync_service.dart';

class PilotHome extends StatefulWidget {
  const PilotHome({super.key});
  @override
  State<PilotHome> createState() => _PilotHomeState();
}

class _PilotHomeState extends State<PilotHome> {
  final _intentCtrl = TextEditingController();
  List<Map<String, dynamic>> _plans = [];
  String? _selectedPlanId;
  Map<String, dynamic>? _selectedPlan;
  final List<Map<String, dynamic>> _events = [];
  StreamSubscription? _sub;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _sub = SyncService.instance.stream.listen(_onWsMessage);
    SyncService.instance.connect();
    _refreshTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (_selectedPlanId != null) _loadPlan(_selectedPlanId!);
      _refresh();
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    _refreshTimer?.cancel();
    _intentCtrl.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final rows = await ApiService.instance.listPlans(limit: 15);
      if (!mounted) return;
      setState(() => _plans = rows);
    } catch (_) {}
  }

  Future<void> _loadPlan(String planId) async {
    final p = await ApiService.instance.getPlan(planId);
    if (!mounted) return;
    setState(() => _selectedPlan = p);
  }

  Future<void> _select(String planId) async {
    setState(() {
      _selectedPlanId = planId;
      _events.clear();
    });
    await SyncService.instance.join(planId);
    await _loadPlan(planId);
  }

  void _onWsMessage(Map<String, dynamic> msg) {
    if (msg['room'] != _selectedPlanId) return;
    setState(() {
      _events.insert(0, msg);
      while (_events.length > 40) _events.removeLast();
    });
    // Refresh plan on every event so step statuses update live
    if (_selectedPlanId != null) _loadPlan(_selectedPlanId!);
  }

  Future<void> _launch() async {
    final text = _intentCtrl.text.trim();
    if (text.isEmpty) return;
    try {
      final resp = await ApiService.instance.launch(text);
      _intentCtrl.clear();
      await _refresh();
      final id = resp['plan_id']?.toString();
      if (id != null) await _select(id);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('启动失败: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.of(context).size.width >= 900;
    final leftPane = _buildLeftPane();
    final centerPane = _buildCenterPane();
    final rightPane = _buildRightPane();

    if (wide) {
      return Row(children: [
        SizedBox(width: 300, child: leftPane),
        const VerticalDivider(width: 1),
        Expanded(child: centerPane),
        const VerticalDivider(width: 1),
        SizedBox(width: 340, child: rightPane),
      ]);
    }
    return DefaultTabController(
      length: 3,
      child: Column(children: [
        const TabBar(tabs: [
          Tab(text: '启动'),
          Tab(text: '进度'),
          Tab(text: '事件流'),
        ]),
        Expanded(child: TabBarView(children: [leftPane, centerPane, rightPane])),
      ]),
    );
  }

  Widget _buildLeftPane() => Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _intentCtrl,
              maxLines: 4,
              decoration: const InputDecoration(
                labelText: '用自然语言描述任务',
                border: OutlineInputBorder(),
                hintText: '例：把本周讨论做成方案 + 评审 PPT',
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              icon: const Icon(Icons.rocket_launch),
              label: const Text('启动 Pilot'),
              onPressed: _launch,
            ),
            const SizedBox(height: 18),
            Text('最近 Plan', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 6),
            Expanded(
              child: ListView(
                children: _plans.map((p) => _planTile(p)).toList(),
              ),
            ),
          ],
        ),
      );

  Widget _planTile(Map<String, dynamic> p) {
    final id = p['plan_id']?.toString() ?? '';
    final done = p['done_steps'] ?? 0;
    final total = p['total_steps'] ?? 0;
    return Card(
      color: id == _selectedPlanId ? Theme.of(context).colorScheme.primaryContainer : null,
      child: ListTile(
        dense: true,
        onTap: () => _select(id),
        title: Text(p['intent']?.toString() ?? id,
            maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text('$id · $done/$total · ${p['phase']}',
            style: const TextStyle(fontSize: 11)),
      ),
    );
  }

  Widget _buildCenterPane() {
    final plan = _selectedPlan;
    if (plan == null) {
      return const Center(child: Text('选择或启动一个 Plan'));
    }
    final steps = (plan['steps'] as List?) ?? const [];
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: steps.length,
      itemBuilder: (ctx, i) {
        final s = steps[i] as Map;
        final status = s['status']?.toString() ?? 'pending';
        final colour = switch (status) {
          'done' => Colors.green,
          'running' => Colors.amber,
          'failed' => Colors.red,
          _ => Colors.grey,
        };
        return ListTile(
          leading: CircleAvatar(backgroundColor: colour, radius: 6),
          title: Text('${i + 1}. ${s['tool']}',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(s['description']?.toString() ?? ''),
              if ((s['result'] as Map?)?.isNotEmpty ?? false)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Wrap(spacing: 6, runSpacing: 4, children: [
                    for (final k in ['url', 'pptx_url', 'pdf_url', 'share_url'])
                      if ((s['result'] as Map)[k] != null)
                        ActionChip(
                          label: Text('$k →'),
                          onPressed: () {
                            final u = Uri.tryParse((s['result'] as Map)[k].toString());
                            if (u != null) launchUrl(u);
                          },
                        ),
                  ]),
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildRightPane() => Padding(
        padding: const EdgeInsets.all(8),
        child: Column(children: [
          Row(children: [
            Icon(SyncService.instance.connected
                ? Icons.cloud_done
                : Icons.cloud_off),
            const SizedBox(width: 8),
            Text(SyncService.instance.connected ? 'Sync 已连接' : '未连接'),
          ]),
          const Divider(),
          Expanded(
            child: ListView.builder(
              itemCount: _events.length,
              itemBuilder: (ctx, i) {
                final ev = _events[i];
                return ListTile(
                  dense: true,
                  leading: Icon(Icons.bolt,
                      color: ev['kind'] == 'event'
                          ? Colors.blue
                          : ev['kind'] == 'state'
                              ? Colors.green
                              : Colors.amber,
                      size: 16),
                  title: Text(ev['kind']?.toString() ?? '',
                      style: const TextStyle(fontSize: 12)),
                  subtitle: Text(ev.toString(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 10)),
                );
              },
            ),
          ),
        ]),
      );
}
