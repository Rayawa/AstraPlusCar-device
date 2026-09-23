from ctypes import c_bool
from datetime import datetime
from multiprocessing import shared_memory, Value

import cv2
import numpy as np
import pynng
import struct
from src.utils.logger import logger_instance as log
# from pyorbbecsdk import Config
# from pyorbbecsdk import OBError
# from pyorbbecsdk import OBSensorType, OBFormat
# from pyorbbecsdk import Pipeline, FrameSet
# from pyorbbecsdk import VideoStreamProfile
# from src.utils.utils import frame_to_bgr_image

class CameraBroadcaster:
    def __init__(self, camera_info):
        self.height = camera_info.get('height', 480)
        self.width = camera_info.get('width', 640)
        self.fps = camera_info.get('fps', 30)
        self.stop_sign = Value(c_bool, False)
        self.frame = shared_memory.SharedMemory(create=True, size=np.zeros(shape=(self.height, self.width, 3),
                                                                           dtype=np.uint8).nbytes)
        self.memory_name = self.frame.name

    def run(self):
        sender = np.ndarray((self.height, self.width, 3), dtype=np.uint8, buffer=self.frame.buf)

        try:
            with pynng.Sub0() as sock:
                sock.subscribe("")
                sock.dial("ipc:///tmp/pubsub.ipc")

                while True:
                    if self.stop_sign.value:
                        self.frame.close()
                        self.frame.unlink()
                        break
                    msg =  sock.recv_msg()
                    format_string = 'II' 
                    result = struct.unpack(format_string, msg.bytes[:struct.calcsize(format_string)])
                    width= 1920
                    height= 1080
                    #print(result) 
                    yuv420sp = np.frombuffer(msg.bytes[struct.calcsize(format_string):], dtype=np.uint8).reshape(height + height // 2, width)
                    mBgr = cv2.cvtColor(yuv420sp, cv2.COLOR_YUV2BGR_NV21)
                    sender[:] = mBgr[:]
        except (KeyboardInterrupt, SystemExit):
            log.info('Cam broadcaster closing')
            self.frame.close()
            self.frame.unlink()
        # cap = cv2.VideoCapture()
        # cap.open(0, apiPreference=cv2.CAP_V4L2)
        # cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        # cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        # cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        # cap.set(cv2.CAP_PROP_FPS, self.fps)
        # sender = np.ndarray((self.height, self.width, 3), dtype=np.uint8, buffer=self.frame.buf)

        # try:
        #     while True:
        #         if self.stop_sign.value:
        #             self.frame.close()
        #             self.frame.unlink()
        #             break
        #         start = datetime.now()
        #         ret, frame = cap.read()
        #         end1 = datetime.now()
        #         resized_frame = cv2.resize(frame, (self.width, self.height))
        #         sender[:] = resized_frame[:]
        #         end2 = datetime.now()
        #         log.debug(f'{self.memory_name}  read time: {end1 - start}, copy time: {end2 - end1}')
        # except (KeyboardInterrupt, SystemExit):
        #     log.info('Cam broadcaster closing')
        #     self.frame.close()
        #     self.frame.unlink()
        #     import pynng

# import pynng
# import cv2
# import numpy as np
# import struct
# with pynng.Sub0() as sock:
#         sock.subscribe("")
#         sock.dial("ipc:///tmp/pubsub.ipc")

#         #while True:
#         msg =  sock.recv_msg()
#             #(integer_value,) = struct.unpack('>I', msg.bytes)
#            # print('Integer Value:', integer_value)


#         format_string = 'II'  # L�����޷��ų�����(4�ֽ�)��H�����޷��Ŷ�����(2�ֽ�)

#         result = struct.unpack(format_string, msg.bytes[:struct.calcsize(format_string)])
#         width= 1920
#         height= 1080

#         yuv420sp = np.frombuffer(msg.bytes[struct.calcsize(format_string):], dtype=np.uint8).reshape(height + height // 2, width)
#         print(result)  # ���: (262145, 513)


#         # ת����ɫ�ռ�
#         mBgr = cv2.cvtColor(yuv420sp, cv2.COLOR_YUV2BGR_NV21)

#         # д��ͼ���ļ�
#         cv2.imwrite("./readYuv.jpg", mBgr)
#             #print(msg.bytes)

