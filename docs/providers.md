# 服务商支持说明

插件通过 `provider` 配置项在多服务商之间切换。切换后，`/ai-gitee generate`
指令与 LLM 生图工具 `draw_image` 会统一调用所选服务商，其余指令（比例解析、
防抖、多 Key 轮询、图片清理）行为保持一致。

| provider | 平台 | 当前支持能力 |
| --- | --- | --- |
| `gitee`（默认） | Gitee AI | 文生图、图生图、风格转换、AI 图片编辑、模型列表查询 |
| `qianwen` | 千问云（platform.qianwenai.com） | 文生图（Qwen-Image / 万相 / Z-Image 系列）；图片编辑与图生图暂不支持 |

## 配置项

| 配置项 | 说明 |
| --- | --- |
| `provider` | `gitee` 或 `qianwen` |
| `qianwen_api_key` | 千问云 API Key，仅 `provider=qianwen` 时生效，支持多 Key 轮询 |
| `qianwen_base_url` | 千问云 API 基础地址，默认 `https://maas.qianwenaiapi.com/api/v1` |
| `qianwen_prompt_extend` | 是否开启提示词自动扩写（部分模型不支持，会自动忽略） |
| `model` / `size` | 跨服务商共用；千问云会自动把尺寸的 `宽x高` 转成官方要求的 `宽*高` |

## 千问云支持的模型

模型与端点的对应关系来自官方文档，**不同版本端点不同**，插件已按型号自动选择：

| 模型 | 端点 | 提示词传参 | 调用方式 | 提示词上限 |
| --- | --- | --- | --- | --- |
| `qwen-image-3.0-pro` / `qwen-image-3.0` | `multimodal-generation` | `messages` | 同步 | 2,000 |
| `qwen-image-2.1-pro` | `multimodal-generation` | `messages` | 同步 | 2,000 |
| `qwen-image-2.0-pro` / `qwen-image-2.0` | `multimodal-generation` | `messages` | 同步 | 2,000 |
| `qwen-image-max` / `qwen-image-plus` | `multimodal-generation` | `messages` | 同步 | 2,000 |
| `qwen-image` | `multimodal-generation` | `messages` | 同步 | 2,000 |
| `z-image-turbo` | `multimodal-generation` | `messages` | 同步 | 800 |
| `wan2.6-t2i` | `multimodal-generation` | `messages` | 异步 | 2,100 |
| `wan2.5-t2i-preview` | `text2image/image-synthesis` | `prompt` | 异步 | 2,000 |
| `wan2.2-t2i-plus` / `wan2.2-t2i-flash` | `text2image/image-synthesis` | `prompt` | 异步 | 500 |
| `wan2.1-t2i-plus` / `wan2.1-t2i-turbo` | `text2image/image-synthesis` | `prompt` | 异步 | 500 |
| `wanx2.0-t2i-turbo` | `text2image/image-synthesis` | `prompt` | 异步 | 800 |

### 分辨率与降级策略

各模型可接受的分辨率范围不同，插件按官方口径登记了每型能力：

- **Qwen-Image 3.0 / 2.1-pro / 2.0 系列、`qwen-image`**：自定义 `512*512` ~ `2048*2048`，宽高比 1:8 ~ 8:1，默认取 2K 方图；
- **`qwen-image-max` / `qwen-image-plus`**：仅接受固定预设（`1664*928` / `1472*1104` / `1328*1328` / `1104*1472` / `928*1664`），越界降级为 `1664*928`；
- **`z-image-turbo`**：`512*512` ~ `2048*2048`；
- **`wan2.6-t2i`**：`1280*1280` ~ `1440*1440`。

当你指定的比例映射出的尺寸超出当前模型范围时，插件会**自动降级为该模型的默认尺寸**，
而不是让整次生图失败；提示词超长也会按模型上限自动截断。相关日志可在 `debug_mode`
开启后查看。

### 结果解析

万相 2.6 与更早版本的成功响应字段不同：

- `qwen-image-*` / `wan2.6-t2i` / `z-image-turbo`：`output.choices[].message.content[].image`
- `wan2.5` 及更早版本：`output.results[].url`

插件会按型号优先解析对应格式，并在未命中时自动回退尝试另一种格式，
以降低线上字段调整带来的影响。

## 注意事项

- 千问云图片 URL 有效期为 **24 小时**，插件拿到结果后会立即下载落盘。
- `switch-model` 在千问云下会校验型号，填了未登记的模型会直接提示并列出可选值。
- 切回 `gitee` 即可恢复图片编辑与图生图风格转换能力。
