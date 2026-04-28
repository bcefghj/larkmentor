# 飞书权限更新后 Bot 无响应解决方案

> **问题**：在飞书开放平台添加权限并发布新版本后，机器人没有更新或无响应  
> **适用场景**：LarkMentor Agent-Pilot v2 权限配置

---

## 🔍 问题诊断清单

### 1. 确认版本发布状态

在飞书开放平台检查：
- **应用发布 → 版本管理与发布**
- 确认新版本状态为 **「已通过审核」** ✅
- 如果是测试企业，应该立即通过

### 2. 确认权限申请状态  

在 **权限管理** 页面确认以下权限已开通：

#### 必须权限（Bot 基础功能）
```
✅ im:message                    # 获取与发送消息
✅ im:message:send_as_bot       # Bot 身份发送消息
✅ im:chat                      # 获取群组信息
✅ contact:user.base:readonly   # 获取用户信息
```

#### Agent-Pilot 核心权限
```
✅ docx:document               # 创建编辑文档
✅ docx:document:readonly      # 读取文档内容
✅ bitable:app                 # 多维表格读写
✅ bitable:app:readonly        # 多维表格只读
```

#### 画板权限（架构图功能）
```
✅ board:whiteboard:node:create  # 创建画板节点
✅ board:whiteboard:node:read    # 查看画板节点
✅ board:whiteboard:node:update  # 更新画板节点
✅ board:whiteboard:node:delete  # 删除画板节点
```

### 3. 确认事件订阅配置

在 **开发配置 → 事件与回调** 确认：
- 接收方式：**「使用长连接接收事件」** ✅
- 已订阅事件：
  - `im.message.receive_v1` ✅
  - `card.action.trigger` ✅

---

## 🛠️ 解决步骤

### 步骤 1：重启服务器上的 Bot 服务

权限更新后，需要重启服务让新权限生效：

```bash
# 连接服务器
ssh root@118.178.242.26

# 重启 LarkMentor 服务
sudo systemctl restart larkmentor

# 检查服务状态
sudo systemctl status larkmentor

# 查看重新连接日志
tail -20 /var/log/larkmentor.log
```

**预期输出**：
```
[INFO] connected to wss://msg-frontier.feishu.cn/ws/v2?... [conn_id=新连接ID]
```

### 步骤 2：测试基础功能

在飞书中私聊 Bot，发送测试消息：

```
帮助
/pilot help  
开启新人模式
```

### 步骤 3：测试 Agent-Pilot 功能

如果基础响应正常，测试 Agent-Pilot：

```
/pilot 生成一个产品方案文档
/pilot 画一张架构图
```

### 步骤 4：查看详细日志

如果仍无响应，查看详细日志：

```bash
# 查看最近的错误日志
grep -i error /var/log/larkmentor.log | tail -10

# 查看消息接收日志
grep "receive message" /var/log/larkmentor.log | tail -5

# 查看权限相关错误
grep -i "permission\|403\|401" /var/log/larkmentor.log | tail -10
```

---

## 🚨 常见问题及解决方案

### 问题 1：Bot 收到消息但不回复

**症状**：日志显示 `receive message` 但没有后续处理

**原因**：缺少发送消息权限或者消息处理异常

**解决**：
1. 确认 `im:message:send_as_bot` 权限已开通
2. 检查 `.env` 配置是否正确
3. 重启 Dashboard 服务：
   ```bash
   sudo systemctl restart larkmentor-dashboard
   ```

### 问题 2：权限申请后仍提示权限不足

**症状**：调用 API 时返回 `99991403 permission denied`

**解决**：
1. **确认版本发布**：权限申请后必须发布新版本
2. **等待生效时间**：新权限可能需要 5-10 分钟生效
3. **清除缓存**：重启 Bot 服务刷新权限缓存

### 问题 3：WebSocket 连接失败

**症状**：日志显示连接错误或频繁重连

**解决**：
1. 检查 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 配置
2. 确认应用状态为「已启用」
3. 检查服务器网络连接

### 问题 4：创建文档/画板失败

**症状**：Agent-Pilot 执行时报权限错误

**解决**：
1. 确认 `docx:document` 权限已开通并生效
2. 确认画板相关的 4 个权限都已申请
3. 检查飞书 API 配额是否超限

---

## 📊 权限生效验证

### 方法 1：通过 Dashboard API 验证

访问：`http://118.178.242.26:8001/api/pilot/scenarios`

**预期响应**：
```json
[
  {
    "key": "A_intent",
    "name": "意图与指令入口",
    ...
  }
]
```

### 方法 2：通过 Agent-Pilot 测试

发送：`/pilot 测试权限`

**预期行为**：
- Bot 回复执行计划
- 成功创建文档/画板
- 生成分享链接

### 方法 3：通过日志验证

查看成功的 API 调用：
```bash
grep -i "success\|created\|generated" /var/log/larkmentor.log
```

---

## ⏰ 权限生效时间表

| 权限类型 | 预期生效时间 | 备注 |
|----------|--------------|------|
| **IM 消息权限** | 立即 | 重启服务后生效 |
| **文档权限** | 5-10 分钟 | 飞书 API 缓存刷新 |  
| **画板权限** | 5-10 分钟 | 新功能权限延迟较高 |
| **多维表格权限** | 立即 | 通常无延迟 |

---

## 🔧 完整验证脚本

保存为 `verify_permissions.sh`：

```bash
#!/bin/bash
echo "=== LarkMentor Agent-Pilot 权限验证 ==="

echo "1. 检查服务状态..."
systemctl status larkmentor --no-pager

echo -e "\n2. 检查 WebSocket 连接..."
tail -5 /var/log/larkmentor.log | grep -E "(connected|ping success)"

echo -e "\n3. 测试 Dashboard API..."
curl -s http://localhost:8001/api/pilot/scenarios | head -100

echo -e "\n4. 检查最近的错误..."
grep -i error /var/log/larkmentor.log | tail -3

echo -e "\n5. 检查权限相关日志..."
grep -i "permission\|403\|401" /var/log/larkmentor.log | tail -3

echo -e "\n=== 验证完成 ==="
```

---

## 📞 紧急联系方式

如果按照上述步骤仍无法解决，可以：

1. **查看 GitHub Issues**：https://github.com/bcefghj/larkmentor/issues
2. **检查飞书开放平台状态**：https://open.feishu.cn/
3. **联系飞书技术支持**：开发者后台右下角「帮助与支持」

**当前服务器状态**：✅ 正常运行  
**最新重启时间**：2026-04-24 02:32:18  
**WebSocket 连接**：✅ 已连接 (`conn_id=7632024309343013844`)