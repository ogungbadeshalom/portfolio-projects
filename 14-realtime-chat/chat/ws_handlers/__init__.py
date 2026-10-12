"""WebSocket message handlers for the chat application.

Each module owns one slice of the protocol:
    * ``connection`` -- connect/disconnect lifecycle + the receive loop.
    * ``broadcast``   -- sending messages to a room (message/typing fan-out).
    * ``presence``    -- computing and delivering the online list.
    * ``typing``      -- typing-indicator fan-out.

All handlers are ``async`` and expect to be driven by the fastapi loop.
"""