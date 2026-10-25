"""Paused, unvalidated SDK process draft; versioned JSON frames, never pickle."""
import asyncio
import json
import struct

VERSION=1
CONTRACT='sdk-process-json@1'
MAX_FRAME=2*1024*1024
MAX_TOTAL=8*1024*1024
MAX_FRAMES=4096
PAUSED_CODE='SDK_PROCESS_DEVELOPMENT_PAUSED'


class ProtocolError(ValueError):pass


def _pairs(items):
    value={}
    for key,item in items:
        if key in value:raise ProtocolError('SDK_PROCESS_PROTOCOL')
        value[key]=item
    return value


def encode(value):
    try:body=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    except (ValueError,TypeError,UnicodeError,RecursionError):raise ProtocolError('SDK_PROCESS_PROTOCOL') from None
    if not 0<len(body)<=MAX_FRAME:raise ProtocolError('SDK_PROCESS_FRAME_LIMIT')
    return struct.pack('!I',len(body))+body


def decode(body):
    try:
        value=json.loads(body.decode('utf-8'),object_pairs_hook=_pairs,
            parse_constant=lambda _:(_ for _ in ()).throw(ProtocolError('SDK_PROCESS_PROTOCOL')))
        if not isinstance(value,dict) or type(value.get('v')) is not int or value['v']!=VERSION:
            raise ProtocolError('SDK_PROCESS_PROTOCOL')
        return value
    except (ValueError,UnicodeError,RecursionError):raise ProtocolError('SDK_PROCESS_PROTOCOL') from None


class Decoder:
    def __init__(self):self.buffer=bytearray();self.total=0;self.frames=0
    def feed(self,data):
        self.total+=len(data)
        if self.total>MAX_TOTAL:raise ProtocolError('SDK_PROCESS_BYTE_LIMIT')
        self.buffer.extend(data)
        if len(self.buffer)>=4 and not 0<struct.unpack('!I',self.buffer[:4])[0]<=MAX_FRAME:
            raise ProtocolError('SDK_PROCESS_FRAME_LIMIT')
    def pop(self):
        if len(self.buffer)<4:return None
        length=struct.unpack('!I',self.buffer[:4])[0]
        if not 0<length<=MAX_FRAME:raise ProtocolError('SDK_PROCESS_FRAME_LIMIT')
        if len(self.buffer)<length+4:return None
        self.frames+=1
        if self.frames>MAX_FRAMES:raise ProtocolError('SDK_PROCESS_FRAME_COUNT')
        value=decode(bytes(self.buffer[4:length+4]));del self.buffer[:length+4]
        return value


async def read_async(sock):
    loop=asyncio.get_running_loop()
    async def exact(count):
        value=bytearray()
        while len(value)<count:
            part=await loop.sock_recv(sock,count-len(value))
            if not part:raise ProtocolError('SDK_PROCESS_IPC_LOST')
            value.extend(part)
        return bytes(value)
    size=struct.unpack('!I',await exact(4))[0]
    if not 0<size<=MAX_FRAME:raise ProtocolError('SDK_PROCESS_FRAME_LIMIT')
    return decode(await exact(size))


async def write_async(sock,value):
    await asyncio.get_running_loop().sock_sendall(sock,encode(value))
