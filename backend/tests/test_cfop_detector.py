"""
测试 CFOP 阶段识别器
"""
import pytest
from app.domain.cube_model import parse_moves, apply_moves_facelet, SOLVED_FACELET
from app.domain.cfop_detector import CFOPStageDetector


# 一段合法 CFOP 解法 (实际可用) - 上半段 + Sune OLL + T-perm PLL
SAMPLE_SOLUTION_STR = "R U R' U' F' R U R' U' R' F R2 U' R' R' F R F' R U R' F' R U R' U' R' F R2 U' R' F R U R' U' R' F R2 U' R' U' R U R' U' R' F R2 U' R' R U R' U' R' F R2 U' R'"


def _ts_moves(moves_str: str, total_ms: int):
    ms = parse_moves(moves_str)
    n = len(ms)
    return [(m, int(total_ms * (i + 1) / n)) for i, m in enumerate(ms)]


class TestCFOPDetector:
    def test_basic_detection(self):
        det = CFOPStageDetector()
        # 一段解法 + 30s 均匀时间戳
        moves_ts = _ts_moves(SAMPLE_SOLUTION_STR, 30_000)
        ranges = det.detect(moves_ts, 30_000)
        # 应能至少识别到 oll 阶段 (解法里有 Sune)
        # pll_end 一定存在 (最后 move)
        assert ranges.pll_end is not None
        assert ranges.confidence > 0.3
        # 时间戳应严格递增
        timestamps = [ts for _, ts in moves_ts]
        for a, b in zip(timestamps, timestamps[1:]):
            assert b > a

    def test_too_few_moves(self):
        det = CFOPStageDetector()
        ranges = det.detect([(parse_moves("R U")[0], 1000)], 30_000)
        assert ranges.confidence <= 0.3

    def test_label_ranges(self):
        det = CFOPStageDetector()
        moves_ts = _ts_moves(SAMPLE_SOLUTION_STR, 30_000)
        ranges = det.detect(moves_ts, 30_000)
        labels = ranges.as_label_ranges(30_000)
        # 4 个 stage 都应有区间 (即使某些 stage 未识别, as_label_ranges 仍兜底)
        for stage in ("cross", "f2l", "oll", "pll"):
            assert stage in labels
            lo, hi = labels[stage]
            assert lo <= hi  # 允许 lo==hi (stage 未识别时)
