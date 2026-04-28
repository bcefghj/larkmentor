import 'dart:convert';

import 'package:http/http.dart' as http;

import 'settings_service.dart';

/// REST client for the Agent-Pilot FastAPI endpoints.
class ApiService {
  ApiService._();
  static final ApiService instance = ApiService._();

  String get _base => SettingsService.instance.backendUrl;

  Future<List<Map<String, dynamic>>> listPlans({int limit = 20}) async {
    final uri = Uri.parse('$_base/api/pilot/plans?limit=$limit');
    final resp = await http.get(uri).timeout(const Duration(seconds: 8));
    if (resp.statusCode != 200) return [];
    final body = jsonDecode(resp.body);
    if (body is List) {
      return body.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return [];
  }

  Future<Map<String, dynamic>?> getPlan(String planId) async {
    final uri = Uri.parse('$_base/api/pilot/plan/$planId');
    final resp = await http.get(uri).timeout(const Duration(seconds: 8));
    if (resp.statusCode != 200) return null;
    final body = jsonDecode(resp.body);
    if (body is Map) return Map<String, dynamic>.from(body);
    return null;
  }

  Future<List<Map<String, dynamic>>> listScenarios() async {
    final uri = Uri.parse('$_base/api/pilot/scenarios');
    final resp = await http.get(uri).timeout(const Duration(seconds: 8));
    if (resp.statusCode != 200) return [];
    final body = jsonDecode(resp.body);
    if (body is List) {
      return body.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return [];
  }

  /// Upload a recorded audio file to the backend, get transcript back.
  ///
  /// The backend `/api/pilot/voice/transcribe` endpoint tries Feishu Minutes
  /// → Doubao ASR → Whisper.cpp in order (see `voice_tool.py`).
  Future<String?> transcribe(String localPath) async {
    final uri = Uri.parse('$_base/api/pilot/voice/transcribe');
    final req = http.MultipartRequest('POST', uri);
    req.files.add(await http.MultipartFile.fromPath('audio', localPath));
    req.fields['open_id'] = SettingsService.instance.openId;
    final streamed = await req.send().timeout(const Duration(seconds: 60));
    if (streamed.statusCode >= 400) return null;
    final raw = await streamed.stream.bytesToString();
    final body = jsonDecode(raw);
    if (body is Map && body['text'] is String) return body['text'] as String;
    return null;
  }

  Future<Map<String, dynamic>> launch(String intent) async {
    final uri = Uri.parse('$_base/api/pilot/launch');
    final resp = await http
        .post(
          uri,
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'intent': intent, 'open_id': SettingsService.instance.openId}),
        )
        .timeout(const Duration(seconds: 12));
    if (resp.statusCode >= 400) {
      throw Exception('launch failed: ${resp.statusCode} ${resp.body}');
    }
    return Map<String, dynamic>.from(jsonDecode(resp.body) as Map);
  }
}
