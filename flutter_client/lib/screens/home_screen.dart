import 'package:flutter/material.dart';
import '../services/api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  String _status = 'checking…';
  int _toolsCount = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final h = await ApiService.instance.health();
      final tools = await ApiService.instance.listTools();
      if (!mounted) return;
      setState(() {
        _status = '${h["status"]} · ${h["uptime_sec"]?.toStringAsFixed(0) ?? "0"}s';
        _toolsCount = tools.length;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _status = '离线');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Agent-Pilot V1'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFF6366F1), Color(0xFFA855F7), Color(0xFFEC4899)],
                ),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(children: [
                    Text('🛫', style: TextStyle(fontSize: 28)),
                    SizedBox(width: 10),
                    Text('飞书 IM 中的 AI 主驾驶',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
                  ]),
                  const SizedBox(height: 12),
                  Text('状态: $_status',
                      style: const TextStyle(color: Colors.white70)),
                  Text('工具: $_toolsCount 个',
                      style: const TextStyle(color: Colors.white70)),
                ],
              ),
            ),
            const SizedBox(height: 20),
            const Text('5 层 Harness 架构',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            _LayerCard(emoji: '🚂', name: 'Runtime', desc: '8 步 Claude Code harness loop'),
            _LayerCard(emoji: '📚', name: 'Context', desc: 'append-only event log'),
            _LayerCard(emoji: '🛠️', name: 'Capability', desc: 'tools + skills + workforce'),
            _LayerCard(emoji: '🛡️', name: 'Governance', desc: '4 级权限 + audit'),
            _LayerCard(emoji: '🌐', name: 'Surface', desc: '飞书 IM + Web + 你正在用的客户端'),
          ],
        ),
      ),
    );
  }
}

class _LayerCard extends StatelessWidget {
  const _LayerCard({required this.emoji, required this.name, required this.desc});
  final String emoji;
  final String name;
  final String desc;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Row(
        children: [
          Text(emoji, style: const TextStyle(fontSize: 28)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name,
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                Text(desc,
                    style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
