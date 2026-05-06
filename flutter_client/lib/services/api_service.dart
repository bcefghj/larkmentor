import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  ApiService._();
  static final ApiService instance = ApiService._();

  String baseUrl = const String.fromEnvironment(
    'AGENT_PILOT_BASE_URL',
    defaultValue: 'http://118.178.242.26',
  );

  Future<void> bootstrap() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('base_url');
    if (saved != null && saved.isNotEmpty) baseUrl = saved;
  }

  Future<void> setBaseUrl(String url) async {
    baseUrl = url.trim();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('base_url', baseUrl);
  }

  Future<Map<String, dynamic>> health() async {
    final r = await http.get(Uri.parse('$baseUrl/health')).timeout(const Duration(seconds: 5));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> listSessions({int limit = 20}) async {
    final r = await http.get(Uri.parse('$baseUrl/api/sessions?limit=$limit')).timeout(const Duration(seconds: 5));
    final list = jsonDecode(r.body) as List;
    return list.cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> listTools() async {
    final r = await http.get(Uri.parse('$baseUrl/api/tools')).timeout(const Duration(seconds: 5));
    final list = jsonDecode(r.body) as List;
    return list.cast<Map<String, dynamic>>();
  }
}
