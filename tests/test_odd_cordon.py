import itertools
from slicepacker.torus import SliceRect
from slicepacker.cordon import worst_position


def test_rectangular_worst_case_including_odd_axes():
    for shape in itertools.product(range(1,5),repeat=3):
        rect = SliceRect((0,0,0),shape)
        _, loss = worst_position(rect)
        expected = min((extent//2 + extent%2) * (rect.chips//extent) for extent in shape)
        assert loss == expected, shape
    assert worst_position(SliceRect((0,0,0),(3,3,3)))[1] == 18
