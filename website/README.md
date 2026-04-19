# LarkMentor 产品网页部署指引

## 阿里云（已完成）

网页已部署到: **http://118.178.242.26/**

更新网页内容：
```bash
scp index.html root@118.178.242.26:/var/www/flowguard/index.html
```

## Netlify 部署

1. 打开 https://app.netlify.com/
2. 登录（可用 GitHub 账号）
3. 点击 "Add new site" → "Deploy manually"
4. 将 `flowguard/website/` 文件夹直接拖拽到页面上
5. 等待几秒，部署完成
6. Netlify 会分配一个域名如 `xxx.netlify.app`
7. 可在 "Site settings" → "Change site name" 改为 `flowguard.netlify.app`（如果可用）

后续更新只需再次拖拽上传即可。
