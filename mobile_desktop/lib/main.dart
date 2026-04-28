// LarkMentor Pilot · Flutter 4-in-1 entry (iOS/Android/macOS/Windows).
//
// The Flutter client is the "Co-pilot GUI" of Agent-Pilot:
//   • Shows DAG plans the Agent is executing;
//   • Renders Doc / Canvas / Slide via embedded WebView that reuses
//     the web dashboard views (single source of truth);
//   • Accepts voice input that is sent back to the bot as a
//     `/pilot <transcript>` command;
//   • Keeps a local Yjs mirror for offline edits.
//
// We intentionally keep external dependencies thin so `flutter run`
// works out-of-the-box on all four targets.

import 'package:flutter/material.dart';
import 'screens/app_shell.dart';
import 'services/settings_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SettingsService.instance.load();
  runApp(const LarkMentorPilotApp());
}

class LarkMentorPilotApp extends StatelessWidget {
  const LarkMentorPilotApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData.dark(useMaterial3: true);
    return MaterialApp(
      title: 'LarkMentor Pilot',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(
        colorScheme: base.colorScheme.copyWith(
          primary: const Color(0xFF58A6FF),
          secondary: const Color(0xFF3FB950),
        ),
        scaffoldBackgroundColor: const Color(0xFF0D1117),
        cardColor: const Color(0xFF161B22),
      ),
      home: const AppShell(),
    );
  }
}
