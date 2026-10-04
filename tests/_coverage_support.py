"""覆盖测试运行环境：让插件包以 ``astrbot_plugin_models_ai`` 名可导入.

为什么需要它
------------
本仓库测试统一按 **顶层包名** ``astrbot_plugin_models_ai`` 导入插件模块
（与 AstrBot 宿主的加载方式一致）。但仓库目录名本身并不叫这个包名，
且 AstrBot 要求插件位于宿主 ``data/plugins/`` 下、以「目录名 = 包名」加载。

因此在「仓库根目录」直接跑 ``pytest`` 时，父目录里没有同名包，导入必然
失败（``No module named 'astrbot_plugin_models_ai'``）。本模块在测试收集
前构造一个**临时包视图**：在同名临时目录下放一个指回仓库根的符号链接
（不支持符号链接的环境退化为复制），再把该临时目录加入 ``sys.path``，
从而让覆盖率工具与 pytest 都能以正确包名导入。

只有「仓库根目录本身不是该包名」时才需要这层垫片；若有人把仓库直接
克隆成 ``astrbot_plugin_models_ai``（目录名即包名），这里会直接返回，
不重复造链。
"""

import shutil
import sys
import tempfile
from pathlib import Path

# 插件包名：测试与宿主统一按此名导入
_PACKAGE_NAME = "astrbot_plugin_models_ai"
# 仓库根目录（本文件位于 tests/ 下）
_REPO_ROOT = Path(__file__).resolve().parents[1]
# 临时包视图的宿主目录（进程内只建一次）
_VIEW_ROOT = Path(tempfile.gettempdir()) / "astrbot-plugin-test-view"
# 已安装的包视图路径（避免重复注入 sys.path）
_installed = False


def ensure_package_view() -> None:
    """确保插件包可按 ``astrbot_plugin_models_ai`` 顶层名导入（幂等）."""
    global _installed
    if _installed:
        return

    # 仓库根目录已按包名命名：直接复用，无需垫片
    if _REPO_ROOT.name == _PACKAGE_NAME:
        _installed = True
        return

    # 仓库根目录已在 sys.path 上：按「顶层包名」导入仍会失败，故继续垫片；
    # 但如果宿主侧已有同名包可达（如已安装 / 已铺链接），则不必重复构造
    if _package_importable():
        _installed = True
        return

    link = _VIEW_ROOT / _PACKAGE_NAME
    _VIEW_ROOT.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir() and not link.is_symlink():
        shutil.rmtree(link)

    try:
        link.symlink_to(_REPO_ROOT, target_is_directory=True)
    except OSError:
        # 符号链接不可用（部分 Windows / 受限容器）：退化为只读复制，
        # 保证测试可运行；覆盖率统计仍基于仓库内真实源码行号。
        shutil.copytree(_REPO_ROOT, link, dirs_exist_ok=True)

    view = str(_VIEW_ROOT)
    if view not in sys.path:
        sys.path.insert(0, view)
    _installed = True


def _package_importable() -> bool:
    """探测 ``astrbot_plugin_models_ai`` 是否已可直接导入."""
    import importlib.util

    try:
        return importlib.util.find_spec(_PACKAGE_NAME) is not None
    except (ImportError, ValueError):
        return False
