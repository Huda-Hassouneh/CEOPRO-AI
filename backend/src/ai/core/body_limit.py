"""
KEEL - request body size limit.

Every endpoint used to read whatever body it was sent before looking at it, so one 2 GB request (or
a few) could exhaust memory or disk before authentication even ran. This rejects an oversized body
with 413 as soon as its declared size is known, and counts the bytes of a body sent without a size
(chunked) so that can't be used to get around the limit.

- ordinary (JSON) requests: MAX_REQUEST_BODY_BYTES, default 2 MB;
- file uploads (multipart): MAX_UPLOAD_SIZE_BYTES (default 10 MB, the upload endpoints' own limit)
  plus 2 MB for the form around the file.
The Stripe webhook is JSON and small, so it uses the ordinary limit.
"""
import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _json_limit() -> int:
    return int(os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024)))


def _multipart_limit() -> int:
    return int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024))) + 2 * 1024 * 1024


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        limit = _multipart_limit() if headers.get(b"content-type", b"").lower().startswith(b"multipart/") else _json_limit()
        declared = headers.get(b"content-length")
        try:
            if declared is not None and int(declared) > limit:
                raise _TooLarge()
        except ValueError:
            await self._refuse(scope, receive, send, 400, "Invalid Content-Length.")
            return
        except _TooLarge:
            await self._refuse(scope, receive, send, 413, "The request is too large.")
            return

        received = 0
        responded = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal responded
            if message["type"] == "http.response.start":
                responded = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not responded:
                await self._refuse(scope, receive, send, 413, "The request is too large.")

    @staticmethod
    async def _refuse(scope, receive, send, status: int, detail: str) -> None:
        await JSONResponse({"detail": detail}, status_code=status, headers={"Connection": "close"})(scope, receive, send)
