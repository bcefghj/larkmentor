import 'package:flutter/material.dart';

import 'pilot_home.dart';
import 'doc_view.dart';
import 'canvas_view.dart';
import 'slide_view.dart';
import 'voice_input.dart';
import 'settings_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _index = 0;

  final _pages = const [
    PilotHome(),
    DocView(),
    CanvasView(),
    SlideView(),
    VoiceInputScreen(),
    SettingsScreen(),
  ];

  final _titles = const [
    'Agent-Pilot',
    '文档协作',
    '画布协作',
    '演示稿 / 排练',
    '语音指令',
    '设置',
  ];

  final _icons = const [
    Icons.rocket_launch,
    Icons.description,
    Icons.draw,
    Icons.slideshow,
    Icons.mic,
    Icons.settings,
  ];

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.of(context).size.width >= 800;
    if (wide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: _index,
              onDestinationSelected: (i) => setState(() => _index = i),
              labelType: NavigationRailLabelType.all,
              destinations: [
                for (var i = 0; i < _titles.length; i++)
                  NavigationRailDestination(
                    icon: Icon(_icons[i]),
                    label: Text(_titles[i]),
                  ),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: _pages[_index]),
          ],
        ),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(_titles[_index])),
      body: _pages[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          for (var i = 0; i < _titles.length; i++)
            NavigationDestination(icon: Icon(_icons[i]), label: _titles[i]),
        ],
      ),
    );
  }
}
