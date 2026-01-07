import unittest

class Hex:
    """Simple class to represent axial hex coordinates"""
    def __init__(self, q, r):
        self.q = q
        self.r = r
    
    def __eq__(self, other):
        if not isinstance(other, Hex):
            return False
        return self.q == other.q and self.r == other.r
    
    def __repr__(self):
        return f"Hex(q={self.q}, r={self.r})"

def offset_to_axial(col, row):
    """Converts offset (col, row) to axial (q, r)."""
    q = col - (row - (row & 1)) // 2
    r = row
    return Hex(q, r)

class TestOffsetToAxial(unittest.TestCase):
    
    def test_even_rows(self):
        """Test conversion for even-numbered rows"""
        # For even rows: (row & 1) = 0, so q = col - row//2
        
        # row 0
        self.assertEqual(offset_to_axial(0, 0), Hex(0, 0))
        self.assertEqual(offset_to_axial(1, 0), Hex(1, 0))
        self.assertEqual(offset_to_axial(2, 0), Hex(2, 0))
        self.assertEqual(offset_to_axial(3, 0), Hex(3, 0))
        
        # row 2
        self.assertEqual(offset_to_axial(0, 2), Hex(-1, 2))
        self.assertEqual(offset_to_axial(1, 2), Hex(0, 2))
        self.assertEqual(offset_to_axial(2, 2), Hex(1, 2))
        self.assertEqual(offset_to_axial(3, 2), Hex(2, 2))
        
        # row 4
        self.assertEqual(offset_to_axial(1, 4), Hex(-1, 4))
        self.assertEqual(offset_to_axial(2, 4), Hex(0, 4))
        self.assertEqual(offset_to_axial(3, 4), Hex(1, 4))
    
    def test_odd_rows(self):
        """Test conversion for odd-numbered rows"""
        # For odd rows: (row & 1) = 1, so q = col - (row-1)//2
        
        # row 1
        self.assertEqual(offset_to_axial(0, 1), Hex(0, 1))
        self.assertEqual(offset_to_axial(1, 1), Hex(1, 1))
        self.assertEqual(offset_to_axial(2, 1), Hex(2, 1))
        self.assertEqual(offset_to_axial(3, 1), Hex(3, 1))
        
        # row 3
        self.assertEqual(offset_to_axial(0, 3), Hex(-1, 3))
        self.assertEqual(offset_to_axial(1, 3), Hex(0, 3))
        self.assertEqual(offset_to_axial(2, 3), Hex(1, 3))
        self.assertEqual(offset_to_axial(3, 3), Hex(2, 3))
        
        # row 5
        self.assertEqual(offset_to_axial(1, 5), Hex(-1, 5))
        self.assertEqual(offset_to_axial(2, 5), Hex(0, 5))
        self.assertEqual(offset_to_axial(3, 5), Hex(1, 5))
    
    def test_negative_coordinates(self):
        """Test with negative column and row values"""
        self.assertEqual(offset_to_axial(-1, 0), Hex(-1, 0))
        self.assertEqual(offset_to_axial(-1, 1), Hex(-1, 1))
        self.assertEqual(offset_to_axial(0, -1), Hex(1, -1))  # row -1: q = 0 - (-1-1)//2 = 0 - (-2)//2 = 0 - (-1) = 1
        self.assertEqual(offset_to_axial(-2, -3), Hex(0, -3))  # row -3: q = -2 - (-3-1)//2 = -2 - (-4)//2 = -2 - (-2) = 0
    
    def test_pattern_consistency(self):
        """Test that adjacent hexes have correct axial coordinates"""
        # Create a small grid and verify relationships
        test_cases = [
            # (col, row, expected_q)
            (0, 0, 0),   # Even row
            (1, 0, 1),   # Even row, right neighbor
            (0, 1, 0),   # Odd row, should align differently
            (1, 1, 1),   # Odd row, right neighbor
            
            # Diagonal relationship
            (2, 0, 2),   # Even row
            (1, 1, 1),   # Odd row - these might be neighbors in hex grid
            (2, 2, 1),   # Even row - check diagonal
        ]
        
        for col, row, expected_q in test_cases:
            result = offset_to_axial(col, row)
            self.assertEqual(result.q, expected_q, f"Failed for ({col}, {row})")
            self.assertEqual(result.r, row, f"r should equal row for ({col}, {row})")
    
    def test_large_values(self):
        """Test with larger coordinate values"""
        self.assertEqual(offset_to_axial(100, 50), Hex(75, 50))  # Even row: 100 - 50//2 = 100 - 25 = 75
        self.assertEqual(offset_to_axial(100, 51), Hex(75, 51))  # Odd row: 100 - (51-1)//2 = 100 - 25 = 75
        
    def test_visual_grid(self):
        """Create a visual test grid to show the mapping"""
        print("\n=== Visual Grid Test ===")
        print("Offset (col, row) -> Axial (q, r)")
        print("-" * 30)
        
        # Small 3x3 grid
        for row in range(3):
            for col in range(3):
                axial = offset_to_axial(col, row)
                print(f"({col}, {row}) -> ({axial.q}, {axial.r})", end="  ")
            print()
        
        # This is mostly for visual verification
        self.assertTrue(True)  # Dummy assertion

def run_manual_tests():
    """Run some manual tests and print results"""
    print("=== Manual Verification ===")
    
    test_points = [
        (0, 0), (1, 0), (2, 0),
        (0, 1), (1, 1), (2, 1),
        (0, 2), (1, 2), (2, 2),
    ]
    
    for col, row in test_points:
        hex_coord = offset_to_axial(col, row)
        row_parity = "odd" if (row & 1) else "even"
        q_calc = f"{col} - ({row} - {row & 1}) // 2 = {col} - {row - (row & 1)} // 2 = {col} - {(row - (row & 1)) // 2} = {hex_coord.q}"
        print(f"({col}, {row}) [row {row_parity}] -> {hex_coord}  |  {q_calc}")
    
    print("\n=== Quick Formula Check ===")
    print("For even rows: q = col - row//2")
    print("For odd rows:  q = col - (row-1)//2")
    print("-" * 40)

if __name__ == "__main__":
    print("Running comprehensive tests for offset_to_axial()")
    print("=" * 50)
    
    # Run manual visual tests first
    run_manual_tests()
    print("\n" + "=" * 50)
    
    # Run unit tests
    print("\nRunning unit tests...")
    unittest.main(verbosity=2, exit=False)