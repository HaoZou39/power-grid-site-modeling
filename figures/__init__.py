"""实验图件。

候选地图和三维帕累托图只读取已经算好的记录，不在这里重算目标或帕累托前沿。
"""

from .candidate_maps import CandidateMapMode, plot_candidate_map, rectangle_corners
from .pareto_3d import write_pareto_3d_html

__all__ = ["CandidateMapMode", "plot_candidate_map", "rectangle_corners", "write_pareto_3d_html"]
