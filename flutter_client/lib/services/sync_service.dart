import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'api_service.dart';

class SyncService {
  WebSocketChannel? _channel;
  StreamController<Map<String, dynamic>>? _events;

  Stream<Map<String, dynamic>>? get events => _events?.stream;
  String? roomId;

  Future<void> connect(String roomId) async {
    this.roomId = roomId;
    final base = ApiService.instance.baseUrl
        .replaceFirst(RegExp(r'^http'), 'ws');
    final url = '$base/sync/ws/$roomId';
    _channel = WebSocketChannel.connect(Uri.parse(url));
    _events = StreamController<Map<String, dynamic>>.broadcast();

    _channel!.stream.listen(
      (raw) {
        try {
          final m = jsonDecode(raw as String) as Map<String, dynamic>;
          _events?.add(m);
        } catch (_) {}
      },
      onError: (_) {},
      onDone: () {
        _events?.close();
      },
    );

    // 心跳
    Timer.periodic(const Duration(seconds: 30), (t) {
      if (_channel == null) return t.cancel();
      try {
        _channel!.sink.add(jsonEncode({"kind": "ping"}));
      } catch (_) {
        t.cancel();
      }
    });
  }

  void publish(String eventKind, Map<String, dynamic> payload) {
    _channel?.sink.add(jsonEncode({
      "kind": "publish",
      "event_kind": eventKind,
      "payload": payload,
    }));
  }

  void disconnect() {
    _channel?.sink.close();
    _events?.close();
    _channel = null;
    _events = null;
  }
}
