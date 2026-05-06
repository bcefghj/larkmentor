# Agent-Pilot V1 · Flutter 三端客户端

支持 macOS / Android / iOS / Web 真三端同步（pycrdt-websocket）。

## 启动

```bash
cd flutter_client
flutter pub get
flutter create . --platforms=macos,android,ios,web   # 第一次需要

# Web（最快验证）
flutter run -d chrome \
  --dart-define=AGENT_PILOT_BASE_URL=http://8.136.98.175

# macOS 桌面端
flutter run -d macos \
  --dart-define=AGENT_PILOT_BASE_URL=http://8.136.98.175

# Android APK
flutter build apk \
  --dart-define=AGENT_PILOT_BASE_URL=http://8.136.98.175
```

## 功能

- **主页**：服务健康 / 工具数 / 5 层架构概览
- **任务**：从 `/api/sessions` 拉取最近 50 条
- **多端**：连 `/sync/ws/<room_id>`，与 Web Dashboard 同房间双向广播
- **设置**：切换服务器地址（默认 `http://8.136.98.175`）

## 架构

```
flutter_client/
├── lib/
│   ├── main.dart
│   ├── screens/
│   │   ├── app_shell.dart
│   │   ├── home_screen.dart
│   │   ├── tasks_screen.dart
│   │   ├── multi_end_screen.dart
│   │   └── settings_screen.dart
│   └── services/
│       ├── api_service.dart   # GET /api/* + 配置存储
│       └── sync_service.dart  # WebSocket /sync/ws/<room>
└── pubspec.yaml
```
