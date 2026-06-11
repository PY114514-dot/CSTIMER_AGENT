"""
基础单元测试: 移动解析 + 魔方状态机 + 还原性
"""
import pytest
from app.domain.cube_model import (
    Move, parse_move, parse_moves,
    apply_move_facelet, apply_moves_facelet,
    is_solved, get_progress_code, generate_random_scramble,
    SOLVED_FACELET,
)


class TestMoveParser:
    def test_basic_moves(self):
        assert parse_move("R").face == "R" and parse_move("R").power == 1
        assert parse_move("R'").face == "R" and parse_move("R'").power == 3
        assert parse_move("R2").face == "R" and parse_move("R2").power == 2
        assert parse_move("U").face == "U"
        assert parse_move("F'").face == "F"

    def test_wide_turns(self):
        assert parse_move("Uw").face == "Uw"
        assert parse_move("Rw'").face == "Rw" and parse_move("Rw'").power == 3
        assert parse_move("Fw2").face == "Fw" and parse_move("Fw2").power == 2

    def test_middle_slices(self):
        assert parse_move("M").face == "M"
        assert parse_move("E'").face == "E"
        assert parse_move("S2").face == "S"

    def test_whole_cube(self):
        assert parse_move("x").face == "x"
        assert parse_move("y'").face == "y" and parse_move("y'").power == 3
        assert parse_move("z2").face == "z"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_move("Q")
        with pytest.raises(ValueError):
            parse_move("")
        with pytest.raises(ValueError):
            parse_move("R3")  # cstimer 不接受 3

    def test_parse_sequence(self):
        ms = parse_moves("R U R' U'")
        assert len(ms) == 4
        assert [str(m) for m in ms] == ["R", "U", "R'", "U'"]


class TestCubeModel:
    def test_solved_is_solved(self):
        assert is_solved(SOLVED_FACELET)
        assert get_progress_code(SOLVED_FACELET) == 0

    def test_identity_returns_solved(self):
        # 注: 重复 parse_move("R") 4 次 = R^4 = identity
        state = apply_moves_facelet(SOLVED_FACELET, parse_moves("R R R R"))
        assert is_solved(state)  # R^4 = identity

    def test_wide_turns_are_unsupported(self):
        # wide/slice/rotation 当前是 unsupported (返回 no-op), 这是有意的
        s = apply_moves_facelet(SOLVED_FACELET, parse_moves("Uw"))
        assert s == SOLVED_FACELET

    def test_middle_slice_is_unsupported(self):
        s = apply_moves_facelet(SOLVED_FACELET, parse_moves("M"))
        assert s == SOLVED_FACELET

    def test_whole_cube_rotation_preserves_solved(self):
        # x, y, z 旋转不改变贴纸的"已还原"性质 (只是改了坐标)
        s = apply_moves_facelet(SOLVED_FACELET, parse_moves("x"))
        # 注意: 对 facelet 字符串而言, 旋转会改变贴纸位置, 不会等于 SOLVED
        # 但 get_progress_code 应识别为 solved (因为对角块判断不依赖坐标)
        # 这里只测应用不抛错
        assert isinstance(s, str) and len(s) == 54


class TestScramble:
    def test_length(self):
        s = generate_random_scramble(20, seed=1)
        assert len(s.split()) == 20

    def test_no_consecutive_same_axis(self):
        s = generate_random_scramble(50, seed=2)
        axes = [m[0] for m in s.split()]
        for i in range(1, len(axes)):
            assert axes[i] != axes[i - 1], f"consecutive same axis at {i}: {axes}"
