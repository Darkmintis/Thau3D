"""Geometry sanity: the bug class that made every wall shear."""

import math
import unittest

from thau3d.geometry import box, cylinder, plan_to_gl


def quad_normal(a, b, c):
    ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)


class BoxTest(unittest.TestCase):
    def setUp(self):
        self.mesh = box((1.0, 2.0, 3.0), (2.0, 4.0, 6.0))

    def test_counts(self):
        self.assertEqual(len(self.mesh.positions), 24)
        self.assertEqual(len(self.mesh.normals), 24)
        self.assertEqual(len(self.mesh.indices), 36)

    def test_every_face_is_planar_and_axis_aligned(self):
        for quad in range(6):
            corners = self.mesh.positions[quad * 4 : quad * 4 + 4]
            for axis in range(3):
                values = {round(corner[axis], 6) for corner in corners}
                if len(values) == 1:
                    break
            else:
                self.fail(f"face {quad} is not axis aligned: {corners}")

    def test_normals_match_winding(self):
        for quad in range(6):
            corners = self.mesh.positions[quad * 4 : quad * 4 + 4]
            stored = self.mesh.normals[quad * 4]
            normal = quad_normal(*corners[:3])
            length = math.sqrt(sum(component * component for component in normal))
            self.assertGreater(length, 1e-9, f"degenerate face {quad}")
            normal = tuple(component / length for component in normal)
            dot = sum(a * b for a, b in zip(normal, stored))
            self.assertGreater(dot, 0.99, f"face {quad} normal disagrees with winding")

    def test_bounds(self):
        xs = [point[0] for point in self.mesh.positions]
        ys = [point[1] for point in self.mesh.positions]
        zs = [point[2] for point in self.mesh.positions]
        # plan (x, y, z) -> gl (x, z, -y); box centre (1, 2, 3), size (2, 4, 6)
        self.assertAlmostEqual(min(xs), 0.0)
        self.assertAlmostEqual(max(xs), 2.0)
        self.assertAlmostEqual(min(ys), 0.0)
        self.assertAlmostEqual(max(ys), 6.0)
        self.assertAlmostEqual(min(zs), -4.0)
        self.assertAlmostEqual(max(zs), 0.0)

    def test_yaw_rotates_about_up(self):
        straight = box((0.0, 0.0, 0.0), (4.0, 2.0, 1.0))
        turned = box((0.0, 0.0, 0.0), (4.0, 2.0, 1.0), yaw=math.pi / 2)
        straight_x = max(p[0] for p in straight.positions) - min(p[0] for p in straight.positions)
        turned_z = max(p[2] for p in turned.positions) - min(p[2] for p in turned.positions)
        self.assertAlmostEqual(straight_x, turned_z, places=5)


class CylinderTest(unittest.TestCase):
    def test_caps_and_normals(self):
        mesh = cylinder((0.0, 0.0, 1.0), 0.5, 2.0, segments=12)
        self.assertGreater(len(mesh.indices), 0)
        for normal in mesh.normals:
            length = math.sqrt(sum(component * component for component in normal))
            self.assertAlmostEqual(length, 1.0, places=4)
        ys = [point[1] for point in mesh.positions]
        self.assertAlmostEqual(min(ys), 0.0, places=4)
        self.assertAlmostEqual(max(ys), 2.0, places=4)


class PlanMappingTest(unittest.TestCase):
    def test_plan_to_gl_is_a_rotation(self):
        self.assertEqual(plan_to_gl((0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
        self.assertEqual(plan_to_gl((1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))
        self.assertEqual(plan_to_gl((0.0, 1.0, 0.0)), (0.0, 0.0, -1.0))
        self.assertEqual(plan_to_gl((0.0, 0.0, 1.0)), (0.0, 1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
