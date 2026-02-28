# AstrBot AI 图像生成插件 - 开发技术文档

## 1. 架构概述

### 1.1 系统架构图
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   AstrBot Core  │◄──►│  Plugin Main   │◄──►│  API Clients   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │                        │
                              ▼                        ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │  Command Router  │    │ GiteeAIClient  │
                       └──────────────────┘    └─────────────────┘
                              │                        │
                              ▼                        ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │  Image Manager   │◄──►│  OpenAI Client │
                       └──────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │ Local Storage    │
                       └──────────────────┘
```

### 1.2 主要组件
- **main.py**: 插件主入口，定义插件类和命令路由
- **commands/**: 命令处理逻辑
- **gitee/**: Gitee AI API 客户端
- **core/**: 核心功能模块（配置、客户端管理、图片管理等）
- **llm_tools/**: LLM工具函数

## 2. 核心模块详解

### 2.1 插件主类 (AIImage)
继承自 Star 类，负责初始化各组件和定义命令接口

### 2.2 API 客户端 (GiteeAIClient)
- 管理多 API Key 轮询
- 调用 Gitee AI API
- 图片生成和编辑功能

### 2.3 图片管理器 (ImageManager)
- 图片下载和保存
- 文件名生成和管理
- 自动清理过期图片

### 2.4 速率限制器 (RateLimiter)
- 防止频繁调用
- 防抖机制

## 3. 功能开发指南

### 3.1 添加新功能的步骤

#### 步骤1: 定义命令处理器
在 `/workspace/commands/` 目录下创建新的命令处理文件

#### 步骤2: 在 main.py 中注册命令
```python
@ai_gitee_group.command("new-feature")
async def new_feature_command_wrapper(self, event: "AstrMessageEvent", param: str):
    async for result in new_feature_command(self, event, param):
        yield result
```

#### 步骤3: 扩展 API 客户端
在 `/workspace/gitee/api_client.py` 中添加新的 API 调用方法

#### 步骤4: 更新配置模式
在 `_conf_schema.json` 中添加新的配置项

### 3.2 API 客户端扩展示例

```python
async def new_feature_method(self, param1, param2):
    """新功能API调用示例"""
    api_key = self._get_next_api_key()
    client = self.client_manager.get_openai_client(api_key)

    # 构建请求参数
    kwargs = {
        "param1": param1,
        "param2": param2,
        "model": self.model,
    }

    try:
        # 调用API
        response = await client.some_new_api_call(**kwargs)

        # 处理响应
        if hasattr(response, 'image_url'):
            session = await self.client_manager.get_http_session()
            return await self.image_manager.download_image(response.image_url, session)
        else:
            return await self.image_manager.save_base64_image(response.b64_json)

    except Exception as e:
        raise RuntimeError(f"API调用失败: {e}") from e
```

## 4. 命令处理开发规范

### 4.1 命令函数结构
```python
async def feature_command(plugin, event: "AstrMessageEvent", params) -> AsyncGenerator[Any, None]:
    """功能命令处理

    Args:
        plugin: 插件实例
        event: 消息事件
        params: 命令参数

    Yields:
        处理结果
    """
    # 参数验证
    if not params:
        yield event.plain_result("缺少必要参数")
        return

    # 速率限制检查
    user_id = event.get_sender_id()
    async for result in check_rate_limit(plugin, event, "功能名", user_id):
        yield result
        return

    try:
        # 执行功能
        result = await plugin.api_client.new_feature(params)
        yield event.chain_result([Image.fromFileSystem(result)])
    except Exception as e:
        yield event.plain_result(f"处理失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(user_id)
```

### 4.2 参数解析
使用 `/workspace/core/command_utils.py` 中的工具函数解析命令参数

## 5. 图片处理流水线

### 5.1 图片处理流程
```
用户输入 → 参数解析 → 速率限制 → API调用 → 图片下载 → 本地存储 → 返回结果
```

### 5.2 图片管理
- 使用时间戳+随机数生成唯一文件名
- 自动清理超过缓存限制的旧图片
- 支持多种图片格式

## 6. 配置管理

### 6.1 配置文件结构
`_conf_schema.json` 定义了插件的配置项结构

### 6.2 默认配置
在 `/workspace/core/config.py` 中定义各种默认值

## 7. 错误处理策略

### 7.1 API错误处理
- 认证错误：提示API Key问题
- 速率限制：提示稍后再试
- 服务器错误：提示服务不可用
- 其他错误：提供通用错误信息

### 7.2 业务逻辑错误
- 参数错误：提供使用说明
- 处理失败：提供重试建议
- 文件错误：提示文件格式要求

## 8. 性能优化建议

### 8.1 异步处理
- 使用异步I/O操作
- 并发处理多个请求
- 合理使用后台任务

### 8.2 缓存策略
- 图片结果缓存
- API响应缓存
- 频繁操作缓存

### 8.3 资源管理
- 及时释放API连接
- 自动清理临时文件
- 内存使用优化

## 9. 扩展性设计

### 9.1 插件架构
- 模块化设计，便于功能扩展
- 统一的错误处理机制
- 标准化的API接口

### 9.2 功能扩展
- 新功能可在不修改核心代码的情况下添加
- 支持第三方API集成
- 可配置的处理流程

## 10. 安全考虑

### 10.1 输入验证
- 严格验证用户输入
- 防止恶意文件上传
- 参数长度限制

### 10.2 API安全
- API Key安全存储
- 调用频率限制
- 数据传输加密

### 10.3 本地安全
- 临时文件安全删除
- 访问权限控制
- 敏感信息处理