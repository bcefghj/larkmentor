// Agent-Pilot v13 · Flutter 4-in-1 entry (iOS/Android/macOS/Windows).

import 'package:flutter/material.dart';
import 'screens/app_shell.dart';
import 'services/settings_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SettingsService.instance.load();
  runApp(const AgentPilotApp());
}

class AgentPilotApp extends StatelessWidget {
  const AgentPilotApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData.dark(useMaterial3: true);
    return MaterialApp(
      title: 'Agent-Pilot v13',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(
        colorScheme: base.colorScheme.copyWith(
          primary: const Color(0xFF58A6FF),
          secondary: const Color(0xFF3FB950),
          surface: const Color(0xFF161B22),
        ),
        scaffoldBackgroundColor: const Color(0xFF0D1117),
        cardColor: const Color(0xFF161B22),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF161B22),
          elevation: 0,
        ),
      ),
      home: const AppShell(),
    );
  }
}
