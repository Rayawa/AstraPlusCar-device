"""Hardware-free checks for the calibrated keyboard turnaround."""
import unittest
from unittest.mock import Mock

from motion_control import Command, MotionArbiter
from src.actions import SpinAntiClockwise, Stop


class TurnaroundTest(unittest.TestCase):
    def test_z_stops_after_calibrated_time_at_every_selected_speed(self):
        # The prior 5.24 s command produced about 285 degrees on the car.
        self.assertAlmostEqual(MotionArbiter.TURN_DURATION, 3.3, delta=0.1)

        for selected_speed in range(0, 101, 20):
            with self.subTest(selected_speed=selected_speed):
                now = [10.0]
                ctrl = Mock()
                driver = MotionArbiter(ctrl, Mock(), clock=lambda: now[0])
                driver.speed = selected_speed
                driver.handle(Command('z', issued_at=now[0]))
                spin = ctrl.execute.call_args.args[0]
                self.assertIsInstance(spin, SpinAntiClockwise)
                self.assertEqual(spin.speed, driver.TURN_SPEED)

                now[0] += driver.TURN_DURATION - 0.01
                driver.tick()
                self.assertEqual(ctrl.execute.call_count, 1)

                now[0] += 0.02
                driver.tick()
                self.assertIsInstance(ctrl.execute.call_args.args[0], Stop)


if __name__ == '__main__':
    unittest.main()
