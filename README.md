# AstrBot AI 图像生成插件 （有免费额度）

[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Bxiaomizhoubaobei%2Bastrbot_plugin_models_ai.svg?type=shield&issueType=security)](https://app.fossa.com/projects/git%2Bgithub.com%2Bxiaomizhoubaobei%2Bastrbot_plugin_models_ai?ref=badge_shield&issueType=security)
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Bxiaomizhoubaobei%2Bastrbot_plugin_models_ai.svg?type=large&issueType=license)](https://app.fossa.com/projects/git%2Bgithub.com%2Bxiaomizhoubaobei%2Bastrbot_plugin_models_ai?ref=badge_large&issueType=license)
[![Language](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License](https://img.shields.io/github/license/xiaomizhoubaobei/astrbot_plugin_models_ai)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/xiaomizhoubaobei/astrbot_plugin_models_ai)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/releases)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/graphs/commit-activity)

> **当前版本**: v0.0.1

本插件为 AstrBot 接入 Gitee AI 的图像生成能力，支持通过自然语言或指令调用，支持多 Key 轮询。

## 功能特性

- 支持通过 LLM 自然语言调用生成图片
- 支持通过指令 `/ai` 生成图片
- 支持多种图片比例和分辨率
- 支持自定义模型
- 支持多 API Key 轮询调用
- 支持自定义负面提示词
- 自动清理旧图片，节省存储空间

## 配置

在 AstrBot 的管理面板中配置以下参数：

| 参数                    | 说明                           | 默认值                       |
|-----------------------|------------------------------|---------------------------|
| `api_key`             | Gitee AI API Key（支持多 Key 轮询） | `[]`                      |
| `model`               | 使用的模型名称                      | `z-image-turbo`           |
| `size`                | 默认图片大小                       | `1024x1024`               |
| `num_inference_steps` | 推理步数                         | `9`                       |
| `negative_prompt`     | 负面提示词，用于指定不希望出现在生成图片中的内容     | `""`                      |

### 配置说明

- **api_key**: 支持配置多个 Key 以实现轮询调用，可有效分摊 API 额度消耗
- **negative_prompt**: 可自定义负面提示词，留空则使用内置默认值（包含 low quality、bad anatomy 等常用负面词）


## Gitee AI API Key获取方法：
1.访问https://ai.gitee.com/serverless-api?model=z-image-turbo

2.<img width="2241" height="1280" alt="PixPin_2025-12-05_16-56-27" src="./images/77f9a713-e7ac-4b02-8603-4afc25991841.png" />

3.免费额度<img width="240" height="63" alt="PixPin_2025-12-05_16-56-49" src="./images/6efde7c4-24c6-456a-8108-e78d7613f4fb.png" />

4.可以涩涩，警惕违规被举报

5.好用可以给个🌟

## 支持的图像尺寸

> ⚠️ **注意**: 仅支持以下尺寸，使用其他尺寸会报错

| 比例   | 可用尺寸                                   |
|------|----------------------------------------|
| 1:1  | 256×256, 512×512, 1024×1024, 2048×2048 |
| 4:3  | 1152×896, 2048×1536                    |
| 3:4  | 768×1024, 1536×2048                    |
| 3:2  | 2048×1360                              |
| 2:3  | 1360×2048                              |
| 16:9 | 1024×576, 2048×1152                    |
| 9:16 | 576×1024, 1152×2048                    |

## 使用方法

### 指令调用

```
/ai <提示词> [比例]
```

示例：
- `/ai 一个可爱的女孩` (使用默认比例 1:1)
- `/ai 一个可爱的女孩 16:9`
- `/ai 赛博朋克风格的城市 9:16`


### 自然语言调用

直接与 bot 对话，例如：
- "帮我画一张小猫的图片"
- "生成一个二次元风格的少女"

## 注意事项

- 请确保您的 Gitee AI 账号有足够的额度。

- 生成的图片会临时保存在 `data/plugins/astrbot_plugin_models_ai/images` 目录下
- 插件会自动清理旧图片，保留最近 50 张，无需手动管理
- `/ai` 命令和 LLM 调用均有 10 秒防抖机制，避免重复请求

## 出图展示区

<img width="1152" height="2048" alt="29889b7b184984fac81c33574233a3a9_720" src="./images/c2390320-6d55-4db4-b3ad-0dde7b447c87.png" />

<img width="1152" height="2048" alt="60393b1ea20d432822c21a61ba48d946" src="./images/3d8195e5-5d89-4a12-806e-8a81e348a96c.png" />

<img width="1152" height="2048" alt="3e5ee8d438fa797730127e57b9720454_720" src="./images/c270ae7f-25f6-4d96-bbed-0299c9e61877.png" />

---

[![GitHub Stars](https://img.shields.io/github/stars/xiaomizhoubaobei/astrbot_plugin_models_ai?style=social)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/xiaomizhoubaobei/astrbot_plugin_models_ai?style=social)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/network/members)
[![GitHub Watchers](https://img.shields.io/github/watchers/xiaomizhoubaobei/astrbot_plugin_models_ai?style=social)](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/watchers)