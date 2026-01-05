# 贡献指南

感谢您对 AstrBot Models AI 插件项目的关注！我们欢迎任何形式的贡献。

## 📋 目录

- [行为准则](#行为准则)
- [如何贡献](#如何贡献)
- [开发流程](#开发流程)
- [代码规范](#代码规范)
- [提交规范](#提交规范)
- [Pull Request 流程](#pull-request-流程)
- [问题反馈](#问题反馈)
- [获取帮助](#获取帮助)

## 行为准则

参与本项目即表示您同意遵守我们的[行为准则](CODE_OF_CONDUCT.md)。请确保您的行为尊重和包容所有社区成员。

## 如何贡献

### 报告问题

如果您发现了 bug 或有功能建议，请：

1. 先检查 [Issues](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/issues) 看是否已有类似问题
2. 如果没有，创建一个新的 Issue，提供详细的信息：
   - 问题描述
   - 复现步骤
   - 预期行为
   - 实际行为
   - 环境信息（AstrBot 版本、Python 版本等）
   - 相关日志或截图

### 提交代码

我们欢迎代码贡献！请按照以下步骤进行：

1. Fork 本仓库
2. 创建您的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建一个 Pull Request

## 开发流程

### 环境准备

1. 克隆仓库：
   ```bash
   git clone https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai.git
   cd astrbot_plugin_models_ai
   ```

2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

3. 配置插件：
   - 复制配置模板并根据需要修改
   - 配置您的 API 密钥和服务提供商

### 项目结构

```
astrbot_plugin_models_ai/
├── main.py              # 插件主入口
├── config.py            # 配置管理
├── model_manager.py     # 模型管理
├── api_client.py        # API 客户端
├── client_manager.py    # 客户端管理器
├── image_manager.py     # 图像管理
├── rate_limiter.py      # 速率限制
├── metadata.yaml        # 插件元数据
├── requirements.txt     # Python 依赖
└── README.md           # 项目说明
```

### 添加新功能

1. 在对应的模块中实现功能
2. 添加必要的错误处理和日志记录
3. 更新配置文件（如果需要新的配置项）
4. 更新文档（README.md）
5. 添加测试（如果有）

## 代码规范

### Python 代码风格

- 遵循 [PEP 8](https://pep8.org/) 规范
- 使用有意义的变量和函数名
- 添加必要的注释和文档字符串
- 保持函数简洁，单一职责
- 使用类型提示（Type Hints）

示例：
```python
def generate_image(
    prompt: str,
    model: str = "default",
    width: int = 1024,
    height: int = 1024
) -> Optional[bytes]:
    """
    生成图像
    
    Args:
        prompt: 图像生成提示词
        model: 使用的模型名称
        width: 图像宽度
        height: 图像高度
    
    Returns:
        图像的二进制数据，失败时返回 None
    """
    # 实现代码
    pass
```

### 文档规范

- 所有公共函数和类都应有文档字符串
- 使用 Google 风格或 NumPy 风格的文档字符串
- 更新 README.md 说明新功能的使用方法

## 提交规范

### 提交信息格式

使用清晰的提交信息，格式如下：

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type 类型

- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具相关

### 示例

```
feat(api): add support for new image generation model

- Add new model client for XYZ provider
- Update configuration schema
- Add error handling for API failures

Closes #123
```

## Pull Request 流程

### PR 标题

使用与提交信息相同的格式，例如：
- `feat: add support for OpenAI DALL-E`
- `fix: resolve rate limiting issue`

### PR 描述

请提供：

1. **变更说明**：简要描述您做了什么
2. **动机**：为什么需要这个变更
3. **测试**：如何测试您的更改
4. **截图**：如果是 UI 相关的变更，提供截图
5. **关联 Issue**：关联相关的 Issue（使用 `Closes #123` 或 `Fixes #123`）

### PR 检查清单

在提交 PR 前，请确保：

- [ ] 代码符合项目规范
- [ ] 已添加必要的文档
- [ ] 已测试所有更改
- [ ] 没有引入新的警告或错误
- [ ] 提交信息清晰规范
- [ ] PR 描述完整

### 代码审查

- 所有 PR 都需要经过代码审查
- 审查者可能会提出修改建议
- 请积极响应审查意见并及时修改
- CI 检查必须通过才能合并

## 问题反馈

### Bug 报告

使用以下模板：

```markdown
**问题描述**
简要描述遇到的问题

**复现步骤**
1. 步骤一
2. 步骤二
3. ...

**预期行为**
描述您期望发生的行为

**实际行为**
描述实际发生的行为

**环境信息**
- AstrBot 版本:
- 插件版本:
- Python 版本:
- 操作系统:

**日志**
```
相关错误日志
```

**附加信息**
任何其他有用的信息
```

### 功能建议

使用以下模板：

```markdown
**功能描述**
简要描述您希望添加的功能

**动机**
为什么需要这个功能

**建议的解决方案**
您认为应该如何实现

**替代方案**
是否有其他可能的实现方式

**附加信息**
任何其他有用的信息
```

## 获取帮助

如果您在贡献过程中遇到问题：

1. 查看 [README.md](README.md) 了解项目基本信息
2. 搜索现有的 [Issues](https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai/issues)
3. 创建新的 Issue 寻求帮助
4. 参与社区讨论

## 许可证

通过贡献代码，您同意您的贡献将根据项目的许可证进行授权。

## 致谢

感谢所有为本项目做出贡献的开发者！您的贡献让这个项目变得更好。

---

**最后更新**：2026年1月