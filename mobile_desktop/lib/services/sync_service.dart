import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/status.dart' as ws_status;

import 'settings_service.dart';

/// Singleton wrapper around the backend's `/sync/ws` WebSocket.
///
/// Protocol reminder (see `core/sync/ws_server.py`):
///   join/leave/state/yupdate/ping → server
///   event/state/yupdate/history/snapshot → client
///
/// We broadcast every received message on a broadcast stream so
/// multiple screens (Pilot home, Doc view, Canvas view) can each
/// subscribe independently without re-opening sockets.
class SyncService {
  SyncService._();
  static final SyncService instance = SyncService._();

  WebSocketChannel? _channel;
  final StreamController<Map<String, dynamic>> _msgs =
      StreamController<Map<String, dynamic>>.broadcast();
  final Set<String> _joinedRooms = <String>{};
  Timer? _pinger;
  bool _connecting = false;

  Stream<Map<String, dynamic>> get stream => _msgs.stream;

  bool get connected => _channel != null;

  Future<void> connect() async {
    if (_channel != null || _connecting) return;
    _connecting = true;
    try {
      final uri = Uri.parse(SettingsService.instance.wsUrl);
      final channel = WebSocketChannel.connect(uri);
      _channel = channel;
      channel.stream.listen(
        (data) {
          try {
            final msg = jsonDecode(data as String);
            if (msg is Map<String, dynamic>) _msgs.add(msg);
          } catch (_) {}
        },
        onDone: _onDone,
        onError: (_) => _onDone(),
        cancelOnError: true,
      );
      // Re-join any previously joined rooms after a reconnect
      for (final r in _joinedRooms) {
        channel.sink.add(jsonEncode({'op': 'join', 'room': r}));
      }
      _pinger?.cancel();
      _pinger = Timer.periodic(const Duration(seconds: 25), (_) => send({'op': 'ping'}));
    } catch (_) {
      _channel = null;
    } finally {
      _connecting = false;
    }
  }

  void _onDone() {
    _channel = null;
    _pinger?.cancel();
    // Reconnect with backoff
    Future.delayed(const Duration(seconds: 2), connect);
  }

  Future<void> join(String room) async {
    _joinedRooms.add(room);
    await connect();
    send({'op': 'join', 'room': room});
  }

  void leave(String room) {
    _joinedRooms.remove(room);
    send({'op': 'leave', 'room': room});
  }

  void publishState(String room, Map<String, dynamic> state) {
    send({'op': 'state', 'room': room, 'state': state});
  }

  void publishYUpdate(String room, String updateB64) {
    send({'op': 'yupdate', 'room': room, 'update_b64': updateB64});
  }

  void send(Map<String, dynamic> payload) {
    try {
      _channel?.sink.add(jsonEncode(payload));
    } catch (_) {}
  }

  Future<void> close() async {
    _pinger?.cancel();
    await _channel?.sink.close(ws_status.normalClosure);
    _channel = null;
  }
}
