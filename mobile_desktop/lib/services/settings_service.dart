import 'package:shared_preferences/shared_preferences.dart';

class SettingsService {
  SettingsService._();
  static final SettingsService instance = SettingsService._();

  late SharedPreferences _prefs;
  String _backendUrl = 'http://118.178.242.26';
  String _openId = 'ou_local_demo';

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    _backendUrl = _prefs.getString('backendUrl') ?? _backendUrl;
    _openId = _prefs.getString('openId') ?? _openId;
  }

  String get backendUrl => _backendUrl;
  String get wsUrl {
    if (_backendUrl.startsWith('https')) {
      return _backendUrl.replaceFirst('https', 'wss') + '/sync/ws';
    }
    return _backendUrl.replaceFirst('http', 'ws') + '/sync/ws';
  }

  String get openId => _openId;

  Future<void> setBackendUrl(String v) async {
    _backendUrl = v;
    await _prefs.setString('backendUrl', v);
  }

  Future<void> setOpenId(String v) async {
    _openId = v;
    await _prefs.setString('openId', v);
  }
}
