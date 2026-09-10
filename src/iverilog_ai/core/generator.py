"""兼容导出：向量式 testbench 生成器的稳定入口。

实现位于 core.testbench；保留这个短模块名便于脚本和早期设计文档使用，
同时不会复制或引入第二套生成逻辑。
"""

from .testbench import TestbenchGenerationError, TestbenchGenerator, generate_testbench

__all__ = ["TestbenchGenerationError", "TestbenchGenerator", "generate_testbench"]
