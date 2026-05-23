# 语录 - 管理后台 SPEC

> 设计语言：温暖赭石色调 + 衬线标题 + 克制留白 + 精致动效

---

## 设计系统

### 色彩
```
accent:       #C45D3E  (赭石红)
accent-light:  #E07A5F
accent-dark:  #A34A2F
accent-muted: rgba(196,93,62,0.12)
bg:           #FAFAF8  (暖白)
bg-warm:      #F5F3EF  (米白)
bg-dark:      #EDEBE6
ink:          #1A1A1A
ink-light:    #3D3D3D
muted:        #8B8680
border:       rgba(26,26,26,0.08)
border-strong:rgba(26,26,26,0.12)
success:      #4A7C59
warning:      #C9A227
danger:       #D64545
```

### 字体
- 标题：Noto Serif SC (Google Fonts) — 衬线，厚重感
- 正文：Noto Sans SC — 清晰，现代
- 数字/Mono：JetBrains Mono — 数据展示

### 动效
- 页面加载：卡片依次 stagger 淡入上移 (0.1s 间隔)
- hover：translateY(-2px) + 阴影加深
- 按钮：scale(0.98) 按压反馈
- 侧边栏：subtle shadow + 左边框 accent 色

### 图标
- Lucide Icons (CDN)
- 统一 stroke-width: 1.5

---

## 页面结构

### 全局布局
```
┌─────────────────────────────────────────────┐
│  顶部导航栏 (64px)                           │
│  Logo | 标题        用户头像 | 登出          │
├──────────┬──────────────────────────────────┤
│          │                                  │
│ 侧边栏   │  主内容区                         │
│ (220px)  │  (padding: 32px)                 │
│          │                                  │
│  导航菜单 │                                  │
│          │                                  │
└──────────┴──────────────────────────────────┘
```

### 7个页面

#### 1. 登录页 `/login.html`
- 居中卡片（480px宽）
- Logo + 标题
- 用户名 + 密码输入框
- 登录按钮（accent色）
- 装饰性背景纹理

#### 2. 仪表盘 `/dashboard.html`
- 顶部统计卡片（4个）：总录音数/分析完成/总时长/本月新增
- 最近录音列表（5条）+ "查看全部" 链接
- 最近报告列表（5条）

#### 3. 录音文件列表 `/files.html`
- 顶部搜索框 + 日期筛选 + 状态筛选
- 表格：文件名 | 时长 | 状态 | 上传时间 | 操作
- 翻页控件
- 批量删除勾选框

#### 4. 报告详情 `/report.html?id=xxx`
- 面包屑 ← 返回列表
- 录音信息：文件名、时长、原始文本
- 分析报告（JSON）格式化展示
  - 概要 / 主题 / 共识 / 需求 / 待办 / 风险

#### 5. Prompt管理 `/prompts.html`
- Prompt 列表卡片（显示名称+描述）
- 激活状态 badge
- 新建 / 编辑 / 删除 按钮
- 编辑弹窗（表单+内容编辑器+预览）

#### 6. 用户管理 `/users.html`
- 用户列表表格
- 创建用户 / 重置密码 / 禁用 按钮
- 创建用户弹窗（用户名+邮箱+角色）

#### 7. 设置页 `/settings.html`
- 清理设置：过期时间（小时）+ 周期（cron表达式）
- Prompt 激活状态切换
- 服务商配置（只读显示）

---

## API 对接

Base URL: `http://localhost:8000`

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 登录 |
| `/api/v1/auth/users/me` | GET | 当前用户信息 |
| `/api/v1/auth/users` | GET | 用户列表 |
| `/api/v1/admin/files` | GET | 文件列表 |
| `/api/v1/admin/files/{id}/detail` | GET | 文件详情 |
| `/api/v1/admin/files/{id}/download` | GET | 下载 |
| `POST /files/{id}/delete-batch` | POST | 批量删除 |
| `/api/v1/admin/reports` | GET | 报告列表 |
| `/api/v1/admin/reports/{id}` | GET | 报告详情 |
| `/api/v1/admin/prompts` | GET/POST | Prompt列表/创建 |
| `/api/v1/admin/prompts/{id}` | PUT/DELETE | Prompt更新/删除 |
| `/api/v1/admin/prompts/preview` | POST | Prompt预览 |
| `/api/v1/admin/dashboard/stats` | GET | 仪表盘统计 |

认证：所有 `/api/v1/admin/*` 接口需在请求头携带：
```
Authorization: Bearer <token>
```

---

## 技术栈

- 纯 HTML + CSS + Vanilla JS（无框架依赖）
- 所有页面共享 `styles.css`
- 每个页面独立的 `.js` 文件
- Google Fonts CDN
- Lucide Icons CDN
