# 30s 离线合并演示脚本（P4.1）

## 目标
在 30 秒内让评委看到：飞行模式下两端各自编辑画布与文档 → 恢复网络 → 不到 2 秒多端自动收敛，无冲突。

## 前置
- 已装好 `larkmentor-macos.dmg` 和 `larkmentor-android.apk`（`scripts/build_flutter_all.sh`）
- 两端已连接同一 room：`canvas:demo-offline`、`doc:demo-offline`
- 后端 `uvicorn dashboard.server:app` 正常运行

## 分镜（0:00–0:30）

| 时间 | 镜头 | 操作 |
|-----:|------|------|
| 0:00 | 全屏分屏 | 左：macOS 桌面端；右：iPhone mirroring；顶部状态栏均为「connected · 离线就绪」 |
| 0:03 | 左侧画布 | 画一个矩形 "架构图 v1"；status 条仍是 connected |
| 0:05 | 右侧画布 | 切飞行模式：status 变红 `offline` 但画布继续可画；画一个椭圆 "补充模块" |
| 0:10 | 左侧文档 | 插入表格 3×3，填 3 行；ACK 绿色 |
| 0:14 | 右侧文档 | 仍飞行模式，输入新标题 "离线补充段落"，插图片 |
| 0:18 | 右侧状态栏 | 关飞行模式；看到 `reconnecting → connected`；2 秒内本地更新 flush 到 hub |
| 0:22 | 两侧画布 | 矩形 + 椭圆 同时出现在两端；顺序不冲突（CRDT 自动合并） |
| 0:26 | 两侧文档 | 表格 + 新段落 + 图片 同时出现；光标与他人 presence 彩色圆点可见 |
| 0:30 | 结束 | 字幕：「Yjs + y-websocket + y-indexeddb 三端收敛耗时 1.8s」 |

## 验证点
1. `/sync/ws` 日志中可见两端同 room 的 `yupdate` 消息反向 rebroadcast；
2. `y-indexeddb` 的 `synced` 事件被记录到 Flutter bridge（`offline:loaded`）；
3. 两端 `awareness.peers.length = 2`；
4. 评委口述：「感谢 Yjs — 离线合并没死锁，没丢字」。

## 录制建议
- OBS 1080p 60fps；两台设备镜像到同一机位；
- 录屏前置 `scripts/demo_offline.sh` 清空 artifacts，避免历史形状干扰；
- 用 ffmpeg 导出 30s 裁切：`ffmpeg -i raw.mp4 -ss 0 -t 30 -c copy out.mp4`。
