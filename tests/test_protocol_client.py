"""Strict, standalone fake-host tests: no actual host installation required."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

import pytest
from nativehtmlkit.client import (RpcClient, SocketStream, encode_frame, read_frame,
                                  ProtocolError, DisconnectedError)
from nativehtmlkit.asyncio_api import AsyncRpcClient, EventDispatcher
from nativehtmlkit.errors import RpcTimeoutError


def socket_client():
    left, right = socket.socketpair()
    return RpcClient(SocketStream(left), ordered_notifications=True), right


def _write(sock, frame):
    sock.sendall(encode_frame(frame))


def test_wire_frame_rejects_malformed_length_and_duplicate_keys():
    import io
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(b'\x00\x00\x00\x00'))
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(b'\x00\x20\x00\x01'))
    payload=b'{"jsonrpc":"2.0","id":"one","id":"two"}'
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(struct.pack('>I',len(payload))+payload))
    # A local encoding failure is the caller's error, not a host protocol violation (FR-PY-12).
    from nativehtmlkit.errors import LocalRequestError
    with pytest.raises(LocalRequestError):
        encode_frame({"jsonrpc":"2.0","foo":float('nan')})


def test_jsonrpc_concurrent_requests_and_errors():
    client, sock = socket_client()
    try:
        f1 = client.call_async('window.list')
        f2 = client.call_async('window.create', {'title':'test'})
        stream=sock.makefile('rb', buffering=0)
        req1,req2 = read_frame(stream),read_frame(stream)
        assert req1['id'] != req2['id']
        assert req1['method']=='window.list'
        _write(sock,{'jsonrpc':'2.0','id':req2['id'],'result':{'window_id':'w1'}})
        _write(sock,{'jsonrpc':'2.0','id':req1['id'],'error':{'code':-32001,'message':'unsupported'}})
        assert f2.result(timeout=2)['window_id']=='w1'
        with pytest.raises(Exception) as err:
            f1.result(timeout=2)
        assert getattr(err.value,'code',None)==-32001
    finally:
        client.close();sock.close()


def test_blocked_call_times_out_with_unknown_outcome():
    client,sock=socket_client()
    try:
        with pytest.raises(RpcTimeoutError) as err:
            client.call('window.list', timeout=.025)
        assert err.value.outcome_unknown
        assert err.value.operation=='window.list'
    finally:
        client.close();sock.close()


def test_async_rpc_never_blocks_event_loop():
    asyncio.run(_async_rpc_never_blocks_event_loop())


async def _async_rpc_never_blocks_event_loop():
    client,sock=socket_client()
    try:
        adapter=AsyncRpcClient(client)
        async def server():
            req=await asyncio.to_thread(read_frame,sock.makefile('rb',buffering=0))
            await asyncio.sleep(.02)
            _write(sock,{'jsonrpc':'2.0','id':req['id'],'result':{'success':True}})
        task=asyncio.create_task(server())
        calls=asyncio.create_task(adapter.call('host.capabilities',timeout=2))
        # An asyncio loop must make progress while the RPC is unresolved.
        marker=[]
        await asyncio.sleep(.005)
        marker.append('progress')
        assert (await calls)['success'] is True
        assert marker == ['progress']
        await task
    finally:
        client.close();sock.close()


def test_ordered_async_events_and_callback_failure_isolated():
    asyncio.run(_ordered_async_events_and_callback_failure_isolated())


async def _ordered_async_events_and_callback_failure_isolated():
    d=EventDispatcher(capacity=4)
    seen=[]
    async def action(v):
        await asyncio.sleep(.005)
        seen.append(v)
        if v==2:
            raise ValueError('intentional failure')
    d.submit(action,1);d.submit(action,2);d.submit(action,3)
    await asyncio.sleep(.06)
    await d.stop()
    assert seen==[1,2,3]


def test_contract_snapshot_includes_required_methods():
    path=Path(__file__).resolve().parents[1] / 'contracts/core-v1-method-matrix.json'
    matrix=json.loads(path.read_text())
    # Method-matrix shape is kept verbatim from the qualified Core snapshot.
    raw=json.dumps(matrix)
    for method in ('host.hello','window.create','document.load','document.command','app.ready'):
        assert method in raw


def test_failed_start_scrubs_host_credentials(monkeypatch):
    # A failed connect must not leak the secret to child processes spawned by
    # an application's exception handler; no real Core host is required.
    missing = r'\\.\pipe\nhk-does-not-exist-5391' if os.name == 'nt' else '/tmp/nhk-does-not-exist-5391.sock'
    monkeypatch.setenv('UI4ME_ENDPOINT', missing)
    monkeypatch.setenv('UI4ME_TOKEN', 'f' * 64)
    monkeypatch.setenv('UI4ME_PROTOCOL_VERSION', '1')
    with pytest.raises(OSError):
        RpcClient.from_environment()
    assert 'UI4ME_TOKEN' not in os.environ
    assert 'UI4ME_ENDPOINT' not in os.environ
    assert 'UI4ME_PROTOCOL_VERSION' not in os.environ


def test_error_hierarchy_preserves_legacy_numeric_rpc_code():
    from nativehtmlkit.errors import NativeHTMLKitError
    from nativehtmlkit.client import RpcError, ProtocolError, DisconnectedError
    assert isinstance(RpcError(-32005,'busy'), NativeHTMLKitError)
    assert RpcError(-32005,'busy').code == -32005
    assert isinstance(ProtocolError('bad frame'), NativeHTMLKitError)
    assert isinstance(DisconnectedError('host closed'), NativeHTMLKitError)
