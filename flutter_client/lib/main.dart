import 'package:flutter/material.dart';
import 'screens/app_shell.dart';
import 'services/api_service.dart';
import 'services/sync_service.dart';

void main() {
  ApiService.instance.bootstrap();
  runApp(const AgentPilotApp());
}

class AgentPilotApp extends StatelessWidget {
  const AgentPilotApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Agent-Pilot V1',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6366F1),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF0A0E27),
      ),
      home: const AppShell(),
    );
  }
}
