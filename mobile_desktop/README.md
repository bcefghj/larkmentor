# LarkMentor Pilot · Flutter 客户端

一套代码跑 **iOS / Android / macOS / Windows** 四端，作为 Agent-Pilot 的 **Co-pilot GUI 驾驶舱**。

## 运行

前提：已安装 Flutter SDK ≥ 3.16（<https://docs.flutter.dev/get-started/install>）。

```bash
cd mobile_desktop
flutter pub get

# macOS 桌面
flutter run -d macos

# Windows 桌面（在 Windows 上）
flutter run -d windows

# iOS（需要 Xcode + 苹果开发者账号）
flutter run -d ios

# Android（需要 Android Studio / adb + 真机或模拟器）
flutter run -d android

# Web 预览（可选）
flutter run -d chrome
```

## 默认后端

应用启动后进入「设置」页可修改：

- Backend URL：默认 `http://118.178.242.26`（生产）
- open_id：任意测试字符串，用于区分 Agent-Pilot 历史记录

本地开发时改成 `http://127.0.0.1:8001`（确保后端 `uvicorn dashboard.server:app --port 8001` 在跑）。

## 五个页面

| 页面 | 对应赛题场景 | 说明 |
| --- | --- | --- |
| Agent-Pilot | A / B / E | 启动 Pilot、查看 DAG 执行进度、实时事件流 |
| 文档协作 | C | 内嵌 Dashboard 的 `/dashboard/pilot` WebView，保证四端呈现一致 |
| 画布协作 | C | 纯原生 `CustomPaint` 渲染 tldraw 场景 JSON，离线可用 |
| 演示稿 | D | 读取 slide.generate 的 outline，原生做排练 + 演讲稿 |
| 语音指令 | A | 长按录音 → 后端 ASR → 自动触发 `/pilot <transcript>` |
| 设置 | — | 修改后端地址与 open_id |

## 多端同步原理

所有页面共享同一个 `SyncService`（见 `lib/services/sync_service.dart`），连接到后端 `/sync/ws` WebSocket。

- **事件广播**：Orchestrator 每步都往该通道发消息，四端实时刷新进度条
- **Yjs CRDT**：`SyncService.publishYUpdate` 发送二进制更新，后端 `y_py` 合并，广播给其它客户端
- **离线合并**：`OfflineCache` 把离线期间的 y-update 存 SQLite，重联时 flush 到后端；Yjs 本身保证无冲突

## 打包发布（后续 cycle 执行）

```bash
# macOS DMG
flutter build macos --release
# 产物：build/macos/Build/Products/Release/larkmentor_pilot.app

# Windows MSIX / exe
flutter build windows --release
# 产物：build/windows/x64/runner/Release/larkmentor_pilot.exe

# Android APK（直接分发）
flutter build apk --release
# 产物：build/app/outputs/flutter-apk/app-release.apk

# iOS（需要苹果开发者账号）
flutter build ipa --release
```
