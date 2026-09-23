#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from abc import ABC
import time
from src.actions.base_action import Advance, SpinAntiClockwise, Stop, Sleep,SpinClockwise, CustomAction, ShiftLeft, \
    TurnRight


class ComplexAction(ABC):

        pass


class TurnLeftInPlace(ComplexAction):
    def __init__(self):
        super().__init__()
        self.action_seq = [
            Advance(speed=30),
            Sleep(0.8),
            SpinAntiClockwise(speed=40),
            Sleep(0.5),
            Stop()
        ]


class TurnRightInPlace(ComplexAction):
    def __init__(self):
        super().__init__()
        self.action_seq = [
            Advance(speed=30),
            Sleep(0.55),
            SpinClockwise(speed=40),
            Sleep(0.48),
            Stop()
        ]


class TurnAround(ComplexAction):
    def __init__(self):
        super().__init__()
        self.action_seq = [
            Stop(),
            Sleep(2),
            Advance(speed=50),
            Stop(),
            Sleep(2),
            SpinAntiClockwise(speed=50),
            Sleep(2),
            Advance(speed=30),
            Sleep(2),
            SpinAntiClockwise(speed=50),
            Sleep(2),
            Stop()

        ]


class Start(ComplexAction):
    def __init__(self):
        super().__init__()
        self.update_controller_speed = True
        self.action_seq = [
            Advance(speed=35),
            Sleep(0.2),
            Advance(speed=25)
        ]


class Parking(ComplexAction):
    def __init__(self):
        super().__init__()
        self.action_seq = [
            Stop(),
            Sleep(1),

            CustomAction(motor_setting=[-85, 65, 60, -55]),
            Sleep(0.75),
            Stop(),

            Sleep(2),
            CustomAction(motor_setting=[65, -58, -55, 55]),
            Sleep(1),
            Stop()
        ]
