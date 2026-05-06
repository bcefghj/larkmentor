import 'package:flutter/material.dart';
import '../services/api_service.dart';

class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  List<Map<String, dynamic>> _sessions = [];

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final list = await ApiService.instance.listSessions(limit: 50);
      if (!mounted) return;
      setState(() => _sessions = list);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('任务列表'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      body: _sessions.isEmpty
          ? const Center(child: Text('暂无 session\n在飞书中触发任务后会出现在这里', textAlign: TextAlign.center))
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: _sessions.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (_, i) {
                final s = _sessions[i];
                final id = (s['session_id'] ?? '') as String;
                return Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.04),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(id.length > 24 ? '${id.substring(0, 24)}…' : id,
                          style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                      const SizedBox(height: 4),
                      Text('mode: ${s["mode"] ?? "-"} · user: ${(s["user_open_id"] ?? "")}',
                          style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 11)),
                    ],
                  ),
                );
              },
            ),
    );
  }
}
