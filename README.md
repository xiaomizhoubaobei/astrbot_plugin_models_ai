# AstrBot AI 图像生成插件

[![Language](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License](https://img.shields.io/github/license/xiaomizhoubaobei/astrbot_plugin_models_ai)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/xiaomizhoubaobei/astrbot_plugin_models_ai)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/releases)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/graphs/commit-activity)
[![GitHub Stars](https://img.shields.io/github/stars/xiaomizhoubaobei/astrbot_plugin_models_ai?style=social)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/xiaomizhoubaobei/astrbot_plugin_models_ai?style=social)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/network/members)
[![GitHub Watchers](https://img.shields.io/github/watchers/xiaomizhoubaobei/astrbot_plugin_models_ai?style=social)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/watchers)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fxiaomizhoubaobei%2Fastrbot_plugin_models_ai.svg?type=shield&issueType=license)](https://app.fossa.com/projects/git%2Bgithub.com%2Fxiaomizhoubaobei%2Fastrbot_plugin_models_ai?ref=badge_shield&issueType=license)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fxiaomizhoubaobei%2Fastrbot_plugin_models_ai.svg?type=shield&issueType=security)](https://app.fossa.com/projects/git%2Bgithub.com%2Fxiaomizhoubaobei%2Fastrbot_plugin_models_ai?ref=badge_shield&issueType=security)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fxiaomizhoubaobei%2Fastrbot_plugin_models_ai.svg?type=small)](https://app.fossa.com/projects/git%2Bgithub.com%2Fxiaomizhoubaobei%2Fastrbot_plugin_models_ai?ref=badge_small)


> **当前版本**: v0.0.5

本插件为 AstrBot 接入多家模型服务提供商AI的图像生成能力，支持通过自然语言或指令调用，支持多 Key 轮询。

## 功能特性

- ✅ 支持通过 LLM 自然语言调用生成图片
- ✅ 支持通过指令 `/ai-gitee generate` 生成图片
- ✅ 支持多种图片比例和分辨率
- ✅ 支持自定义模型
- ✅ 支持多 API Key 轮询调用
- ✅ 支持自定义负面提示词
- ✅ 自动清理旧图片，节省存储空间

## 快速开始

1. 安装插件到 AstrBot
2. 获取 Gitee AI API Key
3. 配置插件参数
4. 开始生成图片

详细的安装和配置说明请查看[快速开始指南](docs/getting-started.md)。

## 文档导航

### 用户指南

- 📖 [快速开始](docs/getting-started.md) - 安装插件并获取 API Key
- ⚙️ [配置说明](docs/configuration.md) - 详细的配置选项和最佳实践
- 🎨 [使用指南](docs/user-guide.md) - 指令调用方法
- 🎭 [AI 图片编辑指南](docs/ai-edit-guide.md) - AI 图片编辑功能详解
- 📐 [文生图功能说明](docs/generate-guide.md) - 文生图功能详解
- 🎨 [风格转换指南](docs/style-guide.md) - 风格转换功能详解（84种风格）
- 📐 [支持的图像尺寸](docs/image-sizes.md) - 所有支持的图片尺寸和比例
- 🖼️ [出图展示区](docs/examples.md) - 生成示例和提示词技巧

### 技术文档

- 🛠️ [故障排除](docs/troubleshooting.md) - 常见问题和解决方案

### 项目信息


- 🤝 [贡献指南](CONTRIBUTING.md) - 如何参与项目贡献
- 📜 [行为准则](CODE_OF_CONDUCT.md) - 社区行为准则

## 支持的图片比例

| 比例   | 说明    |
|------|-------|
| 1:1  | 正方形   |
| 4:3  | 横向    |
| 3:4  | 纵向    |
| 3:2  | 横向    |
| 2:3  | 纵向    |
| 16:9 | 宽屏    |
| 9:16 | 竖屏    |

详细的尺寸列表请参考[支持的图像尺寸](docs/image-sizes.md)。

## 相关链接

- [GitHub 仓库](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai)
- [Gitee AI 平台](https://ai.gitee.com/serverless-api?model=z-image-turbo)
- [问题反馈](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/issues)
- [文档中心](docs/)

---

