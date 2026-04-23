import 'package:flutter/material.dart';

import '../services/settings_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _backendCtrl;
  late final TextEditingController _openIdCtrl;

  @override
  void initState() {
    super.initState();
    _backendCtrl = TextEditingController(text: SettingsService.instance.backendUrl);
    _openIdCtrl = TextEditingController(text: SettingsService.instance.openId);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: _backendCtrl,
            decoration: const InputDecoration(
              labelText: 'Backend URL',
              helperText: '默认：http://118.178.242.26',
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _openIdCtrl,
            decoration: const InputDecoration(
              labelText: '我的 open_id (或任意测试 ID)',
            ),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: () async {
              await SettingsService.instance.setBackendUrl(_backendCtrl.text.trim());
              await SettingsService.instance.setOpenId(_openIdCtrl.text.trim());
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('已保存。下次重启生效。')),
                );
              }
            },
            child: const Text('保存'),
          ),
          const SizedBox(height: 40),
          const Divider(),
          const SizedBox(height: 12),
          const Text(
            'LarkMentor · Agent-Pilot v2\n\n'
            '四端一套代码：iOS / Android / macOS / Windows\n'
            '通过 Yjs CRDT 与后端、飞书 Bot、Web Dashboard 实时同步\n\n'
            'GitHub: https://github.com/bcefghj/larkmentor\n'
            '服务器: http://118.178.242.26',
            style: TextStyle(color: Colors.white70),
          ),
        ],
      ),
    );
  }
}
