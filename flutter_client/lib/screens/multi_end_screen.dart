import 'package:flutter/material.dart';
import '../services/sync_service.dart';
import '../services/api_service.dart';

class MultiEndScreen extends StatefulWidget {
  const MultiEndScreen({super.key});

  @override
  State<MultiEndScreen> createState() => _MultiEndScreenState();
}

class _MultiEndScreenState extends State<MultiEndScreen> {
  final _sync = SyncService();
  final _events = <Map<String, dynamic>>[];
  final _roomCtrl = TextEditingController(text: 'demo');
  bool _connected = false;

  Future<void> _connect() async {
    final room = _roomCtrl.text.trim();
    if (room.isEmpty) return;
    await _sync.connect(room);
    _sync.events?.listen((e) {
      setState(() {
        _events.insert(0, e);
        if (_events.length > 200) _events.removeLast();
      });
    });
    setState(() => _connected = true);
  }

  void _publish() {
    _sync.publish('user_event', {
      'from': 'flutter',
      'platform': Theme.of(context).platform.toString(),
      'msg': '来自移动/桌面端的 ping',
    });
  }

  @override
  void dispose() {
    _sync.disconnect();
    _roomCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('多端协同')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _roomCtrl,
                  decoration: const InputDecoration(
                    labelText: 'room_id (= plan_id / session_id)',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: _connected ? null : _connect,
                child: Text(_connected ? '已连接' : '连接'),
              ),
            ]),
            const SizedBox(height: 12),
            Text('Server: ${ApiService.instance.baseUrl}/sync/ws/${_roomCtrl.text}',
                style: const TextStyle(fontSize: 11, color: Colors.white60)),
            const SizedBox(height: 12),
            FilledButton.icon(
              icon: const Icon(Icons.send),
              label: const Text('给其他端发一条 ping'),
              onPressed: _connected ? _publish : null,
            ),
            const SizedBox(height: 16),
            const Text('实时事件流', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.builder(
                itemCount: _events.length,
                itemBuilder: (_, i) {
                  final e = _events[i];
                  final kind = e['kind'] ?? '';
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Text(
                      '[$kind] ${e['payload'] ?? e}',
                      style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
