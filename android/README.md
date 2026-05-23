# EchoMind Android App

EchoMind 配套 Android 客户端，源码待上传。

## 功能

- 前台录音服务（支持暂停 / 继续）
- 上传前选择分析类型 + 填写补充背景说明
- 分析进度实时计时展示
- 内嵌 WebView 查看分享报告
- JWT 登录鉴权，token 过期自动跳转登录页

## 环境要求

- Android Studio Hedgehog 或更高版本
- minSdk 26 / targetSdk 35
- Java 11+

## 配置

安装后首次启动，长按顶部标题区域设置服务器地址，格式：

```
http://192.168.x.x:8088
```

然后用管理员在后台创建好的账号密码登录即可。
