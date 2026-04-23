import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/voice_service.dart';

/// Voice-first Agent-Pilot trigger. Long-press to record, release to
/// stop; the recording file is uploaded to the backend for Doubao /
/// Feishu Minutes transcription, and the resulting text is sent as a
/// regular `/pilot <text>` intent.
class VoiceInputScreen extends StatefulWidget {
  const VoiceInputScreen({super.key});
  @override
  State<VoiceInputScreen> createState() => _VoiceInputScreenState();
}

class _VoiceInputScreenState extends State<VoiceInputScreen> {
  bool _recording = false;
  String _lastTranscript = '';
  String? _lastPlanId;

  Future<void> _startRecord() async {
    await VoiceService.instance.start();
    setState(() => _recording = true);
  }

  Future<void> _stopRecord() async {
    final file = await VoiceService.instance.stop();
    setState(() => _recording = false);
    if (file == null) return;
    // TODO: POST file to /api/pilot/voice/transcribe (backend tool is
    // registered but HTTP endpoint will be added in cycle 3). For now
    // fall back to text input so the end-to-end flow still works.
    _promptForText();
  }

  Future<void> _promptForText() async {
    final ctrl = TextEditingController();
    if (!mounted) return;
    final text = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('(语音转写占位) 输入指令'),
        content: TextField(
            controller: ctrl, maxLines: 4, decoration: const InputDecoration(hintText: '例：把本周讨论做成评审 PPT')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text), child: const Text('提交')),
        ],
      ),
    );
    if (text == null || text.trim().isEmpty) return;
    setState(() => _lastTranscript = text);
    try {
      final resp = await ApiService.instance.launch(text);
      setState(() => _lastPlanId = resp['plan_id']?.toString());
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('启动失败: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          GestureDetector(
            onLongPressStart: (_) => _startRecord(),
            onLongPressEnd: (_) => _stopRecord(),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 180,
              height: 180,
              decoration: BoxDecoration(
                color: _recording ? Colors.redAccent : Theme.of(context).colorScheme.primary,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: (_recording ? Colors.redAccent : Colors.blueAccent).withOpacity(0.5),
                    blurRadius: 40,
                    spreadRadius: _recording ? 10 : 0,
                  ),
                ],
              ),
              child: const Center(
                child: Icon(Icons.mic, color: Colors.white, size: 72),
              ),
            ),
          ),
          const SizedBox(height: 24),
          Text(_recording ? '正在录音，松开发送…' : '长按录音  ·  松开发送',
              style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 36),
          if (_lastTranscript.isNotEmpty)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('最近一次指令',
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 6),
                  Text(_lastTranscript),
                  if (_lastPlanId != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text('Plan: $_lastPlanId',
                          style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
                    ),
                ]),
              ),
            ),
        ],
      ),
    );
  }
}
