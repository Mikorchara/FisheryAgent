"""Paused SDK I/O draft. All execution entry points refuse before any I/O."""
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import sys
import time

# -I excludes caller cwd/PYTHONPATH. Import only this installed/source backend.
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from apps.ai_backend.sdk_process_protocol import read_async,write_async,ProtocolError,VERSION,MAX_FRAMES,MAX_TOTAL,PAUSED_CODE


def redact(value,key):
    if isinstance(value,str):return value.replace(key,'[REDACTED]') if key else value
    if isinstance(value,list):return [redact(v,key) for v in value]
    if isinstance(value,dict):return {redact(k,key):redact(v,key) for k,v in value.items()}
    return value


async def execute(sock,init):
    raise ProtocolError(PAUSED_CODE)
    import httpx
    from openai import AsyncOpenAI,APIConnectionError,APIStatusError,APITimeoutError
    from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
    if set(init)!={'v','kind','id','stream','kwargs','sdk','offline'} or init['kind']!='init':
        raise ProtocolError('SDK_PROCESS_PROTOCOL')
    if type(init['stream']) is not bool or not isinstance(init['kwargs'],dict):raise ProtocolError('SDK_PROCESS_PROTOCOL')
    sid=init['id'];sdk=init['sdk'];offline=init['offline']
    if set(sdk)!={'base_url','key','connect','read','total'}:raise ProtocolError('SDK_PROCESS_PROTOCOL')
    key=sdk['key'];calls=0;client=None;stream=None;closed=False;error=None;sent_bytes=0;frames=0
    async def emit(kind,**data):
        nonlocal sent_bytes,frames
        value={'v':VERSION,'kind':kind,'id':sid,**data}
        sent_bytes+=len(json.dumps(value,ensure_ascii=False).encode());frames+=1
        if frames>MAX_FRAMES or sent_bytes>MAX_TOTAL:raise ProtocolError('SDK_PROCESS_BYTE_LIMIT')
        await write_async(sock,value)
    mode=offline['mode'] if offline is not None else 'real'
    async def mock(request):
        nonlocal calls
        calls+=1
        if calls!=1:raise RuntimeError('SDK_PROCESS_REQUEST_LIMIT')
        if mode=='crash':os._exit(31)
        if mode=='ipc_drop':sock.close();await asyncio.Event().wait()
        if mode=='block_loop':time.sleep(3600)
        if mode in ('wait','ignore_cancel'):
            while True:
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if mode=='wait':raise
        if mode=='http_error':return httpx.Response(503,json={'error':{'message':'offline'}})
        if init['stream']:
            body=''.join('data: '+json.dumps(v)+'\n\n' for v in offline['chunks'])+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=body.encode())
        return httpx.Response(200,json=offline['response'])
    try:
        http=httpx.AsyncClient(transport=httpx.MockTransport(mock) if offline is not None else None,
            trust_env=False,follow_redirects=False)
        client=AsyncOpenAI(api_key=key or 'local-no-key',base_url=sdk['base_url'],max_retries=0,http_client=http,
            timeout=httpx.Timeout(connect=min(sdk['connect'],sdk['total']),read=min(sdk['read'],sdk['total']),
                                  write=min(sdk['read'],sdk['total']),pool=min(sdk['connect'],sdk['total'])))
        await emit('started')
        async with asyncio.timeout(sdk['total']):
            result=await client.chat.completions.create(**init['kwargs'])
            if init['stream']:
                stream=result
                async for chunk in stream:await emit('data',payload=redact(chunk.model_dump(mode='json'),key))
            else:await emit('data',payload=redact(result.model_dump(mode='json'),key))
    except asyncio.CancelledError:error='USER_CANCELLED'
    except TimeoutError:error='TOTAL_TIMEOUT'
    except (APIConnectionError,APIStatusError,APITimeoutError) as e:error=OpenAICompatibleAdapter._map_error(e).code
    except Exception:error='SDK_PROCESS_REQUEST_FAILED'
    finally:
        try:
            if mode=='hang_close':
                while True:
                    try:await asyncio.Event().wait()
                    except asyncio.CancelledError:pass
            if stream is not None:await stream.close()
            if client is not None:await client.close()
            closed=client is not None and client.is_closed()
        except BaseException:error='SDK_PROCESS_CLEANUP_FAILED'
        if error:await emit('error',code=error)
        await emit('closed',local_io_closed=closed,task_done=True,calls=calls,
                   remote_compute_stopped='unknown')


async def run(sock,bootstrap):
    raise ProtocolError(PAUSED_CODE)
    await write_async(sock,{'v':VERSION,'kind':'hello','nonce':bootstrap['nonce'],'pid':os.getpid()})
    init=await read_async(sock)
    task=asyncio.create_task(execute(sock,init))
    async def control():
        try:
            message=await read_async(sock)
            if message!={'v':VERSION,'kind':'cancel','id':init['id']}:raise ProtocolError('SDK_PROCESS_PROTOCOL')
            task.cancel()
        except BaseException:task.cancel()
    watcher=asyncio.create_task(control())
    try:await task
    finally:
        watcher.cancel()
        try:await watcher
        except BaseException:pass


def main():
    raise ProtocolError(PAUSED_CODE)
    logging.disable(logging.CRITICAL)
    value=sys.stdin.buffer.readline(4097)
    bootstrap=json.loads(value)
    if set(bootstrap)!={'port','nonce','delay'} or not 0<=bootstrap['delay']<=30:return 2
    if bootstrap['delay']:time.sleep(bootstrap['delay'])
    with socket.create_connection(('127.0.0.1',bootstrap['port']),timeout=8) as sock:
        sock.setblocking(False)
        asyncio.run(run(sock,bootstrap))
    return 0


if __name__=='__main__':
    # Refuse without reading stdin, loading the SDK or opening a socket.
    sys.stderr.write(PAUSED_CODE+'\n')
    raise SystemExit(2)
