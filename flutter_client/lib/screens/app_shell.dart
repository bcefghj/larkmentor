import 'package:flutter/material.dart';
import 'home_screen.dart';
import 'tasks_screen.dart';
import 'multi_end_screen.dart';
import 'settings_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _idx = 0;

  final _pages = const [
    HomeScreen(),
    TasksScreen(),
    MultiEndScreen(),
    SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _pages[_idx],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _idx,
        onDestinationSelected: (i) => setState(() => _idx = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_rounded), label: '主页'),
          NavigationDestination(icon: Icon(Icons.task_alt_rounded), label: '任务'),
          NavigationDestination(icon: Icon(Icons.devices_rounded), label: '多端'),
          NavigationDestination(icon: Icon(Icons.settings_rounded), label: '设置'),
        ],
      ),
    );
  }
}
