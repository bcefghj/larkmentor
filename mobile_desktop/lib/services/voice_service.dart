import 'dart:async';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Thin wrapper around `package:record`.
///
/// The transcription step itself lives on the backend – we POST the
/// recorded file to `/api/pilot/voice/transcribe` and expect a
/// `{"text": "..."}` response.
class VoiceService {
  VoiceService._();
  static final VoiceService instance = VoiceService._();

  final AudioRecorder _recorder = AudioRecorder();
  String? _currentPath;

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<void> start() async {
    if (!await hasPermission()) return;
    final dir = await getTemporaryDirectory();
    final path = '${dir.path}/pilot_voice_${DateTime.now().millisecondsSinceEpoch}.m4a';
    await _recorder.start(const RecordConfig(encoder: AudioEncoder.aacLc), path: path);
    _currentPath = path;
  }

  Future<File?> stop() async {
    final p = await _recorder.stop();
    _currentPath = null;
    return p == null ? null : File(p);
  }

  bool get isRecording => _currentPath != null;
}
