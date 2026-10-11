"""搜索父类。

子类决定怎样比较目标。这个文件不写权重，也不写某一个约束的名字。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SiteSearch(ABC):
    """一次选址搜索。

    子类实现 `search`。输入是已经建好的场景和建筑尺寸，输出对象要有 `solutions`，
    里面是候选站址记录。种群、权重和标量化都写在子类里。
    """

    algorithm_name: str = ""

    @abstractmethod
    def search(self, problem: Any, modeling: Any) -> Any:
        """返回带 `solutions` 的结果。`solutions` 是候选站址记录。"""
