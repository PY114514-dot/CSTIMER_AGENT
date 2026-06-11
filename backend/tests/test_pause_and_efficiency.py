"""
测试停顿分析器 + 转动效率
"""
import pytest
from app.domain.cube_model import parse_moves, Move
from app.domain.pause_analyzer import PauseAnalyzer
from app.domain.move_efficiency import MoveEfficiency, cancel_moves


class TestPauseAnalyzer:
    def test_no_pauses_in_fast_sequence(self):
        analyzer = PauseAnalyzer(threshold_ms=500)
        moves = [(parse_moves("R U R' U'")[i], (i + 1) * 100, i)
                 for i in range(4)]
        ranges = {"cross": (0, 1000), "f2l": (1000, 5000), "oll": (5000, 6000), "pll": (6000, 7000)}
        pauses = analyzer.analyze(moves, ranges)
        assert pauses == []

    def test_pause_detected(self):
        analyzer = PauseAnalyzer(threshold_ms=500)
        # 2 个 move 之间间隔 1.2s, 然后紧接 200ms
        moves = [
            (Move(face="R", power=1), 100, 0),
            (Move(face="U", power=1), 1300, 1),
            (Move(face="R", power=3), 1500, 2),
        ]
        ranges = {"cross": (0, 1000), "f2l": (1000, 5000)}
        pauses = analyzer.analyze(moves, ranges)
        # 只应有 1 个停顿 (1300-100=1200ms, 横跨 cross->f2l 算 observe)
        assert len(pauses) == 1
        assert pauses[0].duration_ms == 1200
        assert pauses[0].type == "observe"

    def test_pause_classify_observe(self):
        analyzer = PauseAnalyzer(threshold_ms=500)
        # 停顿恰好横跨 cross -> f2l
        moves = [
            (Move(face="R", power=1), 100, 0),
            (Move(face="U", power=1), 1200, 1),
        ]
        ranges = {"cross": (0, 1000), "f2l": (1000, 2000)}
        pauses = analyzer.analyze(moves, ranges)
        assert pauses[0].type == "observe"

    def test_pause_classify_lockup(self):
        analyzer = PauseAnalyzer(threshold_ms=500)
        moves = [
            (Move(face="R", power=1), 100, 0),
            (Move(face="U", power=1), 3000, 1),
        ]
        ranges = {"f2l": (0, 5000)}
        pauses = analyzer.analyze(moves, ranges)
        assert pauses[0].type == "lockup"


class TestMoveEfficiency:
    def test_cancel_basic(self):
        # R R' 应抵消
        result = cancel_moves([Move(face="R", power=1), Move(face="R", power=3)])
        assert len(result) == 0

    def test_cancel_2x(self):
        # R R R = R' (4 个减 3 个)
        result = cancel_moves([
            Move(face="R", power=1), Move(face="R", power=1), Move(face="R", power=1),
        ])
        assert len(result) == 1
        assert result[0].power == 3

    def test_no_cancel_different_face(self):
        result = cancel_moves([Move(face="R", power=1), Move(face="U", power=1)])
        assert len(result) == 2

    def test_mixed(self):
        # R U R' U' (sexy move) 没有任何抵消
        result = cancel_moves(parse_moves("R U R' U'"))
        assert len(result) == 4
        # R R R' = R (3 个 1 合成 3, 跟 R' 抵消后剩 1 个 R 3 但再消?)
        # 实际: R(1) R(1) = R(2), R(2) R'(3) = (2+3) mod 4 = 1 -> R
        result = cancel_moves([
            Move(face="R", power=1), Move(face="R", power=1), Move(face="R", power=3),
        ])
        assert len(result) == 1
        assert result[0].power == 1
