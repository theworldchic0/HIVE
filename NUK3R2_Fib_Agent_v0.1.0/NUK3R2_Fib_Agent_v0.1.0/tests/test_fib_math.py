from src.fib_math import calculate_level, calculate_structure

def test_orientation():
    assert calculate_level(0,100,100) == 0
    assert calculate_level(0,100,0) == 100

def test_levels():
    x = calculate_structure(0,100)
    assert round(x["82.6"],4) == 17.4
    assert round(x["78.6"],4) == 21.4
    assert round(x["61.8"],4) == 38.2
    assert round(x["21.4"],4) == 78.6
    assert round(x["17.4"],4) == 82.6
