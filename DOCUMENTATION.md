# Technical Documentation

## 1. Scope and System Overview

Reverse Shell Controller (RSC) is a Python-based command-and-control
(C2) framework composed of a TCP server, connecting clients, two
dashboard implementations, a payload exporter, and persistent
server-side state.

This document describes the architecture and implementation boundaries
supplied for the project. It does not assume additional capabilities,
deployment mechanisms, or security properties beyond those described
here. RSC should be operated only in isolated, explicitly authorized
environments. A reverse-shell client provides remote command execution,
so access to the server and exported payloads must be treated as
security-sensitive.

### 1.1 Component map

``` text
Reverse Shell Controller
|
+-- modules/
|   +-- server.py             Multi-threaded TCP server (port 4444)
|
+-- client/
|   +-- client.py             Connecting command-execution client
|
+-- web/                      Flask dashboard and SSE frontend
|
+-- dashboard/                Tkinter desktop dashboard
|
+-- exporter/                 Payload source wrapping and export
|
+-- core/
    +-- server_state.py       Persistent server identity and payload registry
    +-- ngrok.py              Local Ngrok admin API detection
```

### 1.2 Component responsibilities

  -----------------------------------------------------------------------
  Component                           Responsibility
  ----------------------------------- -----------------------------------
  `modules/server.py`                 Accepts TCP connections,
                                      authenticates clients, manages
                                      client sessions, and dispatches
                                      commands.

  `client/client.py`                  Connects to the server, performs
                                      authentication, receives commands,
                                      executes them, and returns framed
                                      output.

  `web/`                              Provides a browser-based dashboard
                                      using Flask and Server-Sent Events
                                      (SSE).

  `dashboard/`                        Provides a desktop dashboard
                                      implemented with Tkinter.

  `exporter/`                         Wraps client source into supported
                                      output formats and packages
                                      required dependencies.

  `core/server_state.py`              Persists the HMAC master secret and
                                      payload registry under the user's
                                      configuration directory.

  `core/ngrok.py`                     Detects the local Ngrok admin API
                                      and makes a discovered public URL
                                      available to the export process.
  -----------------------------------------------------------------------

## 2. System Architecture and Threading

The server uses multiple threads to separate connection acceptance,
per-client processing, socket reading, keepalive handling, and token
rotation. This separation prevents a single client operation from
blocking unrelated server activity.

### 2.1 Thread model

The five server thread roles are:

1.  **Accept thread**
2.  **Client Handler thread**
3.  **Client Read Loop thread**
4.  **Keepalive thread**
5.  **Token Rotation thread**

``` text
                         +----------------------+
                         |     TCP Listener     |
                         |       :4444          |
                         +----------+-----------+
                                    |
                              Accept thread
                                    |
                      +-------------+-------------+
                      |                           |
                Client session A             Client session B
                      |                           |
                Handler thread               Handler thread
                      |                           |
                Read Loop thread              Read Loop thread
                      |                           |
                response_queue                response_queue
                      |                           |
                command handling              command handling
                      ^                           ^
                      |                           |
                Keepalive thread             Keepalive thread

                  Token Rotation thread
                    (server-wide role)
```

The diagram represents responsibilities and data flow, not a guarantee
about exact scheduling or thread start order.

#### Accept thread

The **Accept thread** waits for incoming TCP connections on port `4444`.
When a connection is accepted, the server establishes the per-client
processing context and delegates that connection to its client-handling
path. The accept loop remains available to accept additional connections
rather than performing the complete client session inline.

#### Client Handler thread

A **Client Handler thread** manages the lifecycle of an individual
connected client. Its responsibilities include processing the
connection's authentication and coordinating the per-client activities.
Client-specific work is isolated so that one client's session does not
become the execution context for every other connected client.

#### Client Read Loop thread

The **Client Read Loop thread** continuously reads data arriving on its
client's socket. It is the sole socket reader for that connection.
Received data is passed to a thread-safe `queue.Queue` named
`response_queue`, where other server-side logic can consume it without
competing for reads from the socket.

This single-reader rule is a central concurrency invariant. It prevents
multiple threads from independently calling `recv()` on the same socket
and receiving data intended for different logical operations.

#### Keepalive thread

The **Keepalive thread** handles connection-liveness traffic for a
client session. Keepalive traffic shares the same inbound TCP stream as
command output. It must therefore be consumed by the same read loop and
routed through the normal response-processing path, rather than read
directly by a separate thread.

#### Token Rotation thread

The **Token Rotation thread** maintains the server's rotating-token
lifecycle. Authentication tokens are time-dependent and expire. The
server-side rotation mechanism keeps the accepted token state
synchronized with the current rotation interval.

### 2.2 Thread ownership and synchronization

The most important ownership rule is:

> The Client Read Loop thread is the only thread permitted to read from
> a connected client socket.

The other server components interact with received data through the
queue. This avoids read races and provides a clear boundary between
transport I/O and command-response processing.

## 3. Wire Protocol

RSC uses a line-oriented authentication message and a framed
command-response exchange over TCP.

### 3.1 Authentication message

The authentication line has the following format:

``` text
AUTH:<server_uuid>:<payload_uuid>:<token>\n
```

  -----------------------------------------------------------------------
  Field                               Meaning
  ----------------------------------- -----------------------------------
  `AUTH`                              Identifies the message as an
                                      authentication request.

  `server_uuid`                       Identifies the server instance the
                                      client is configured to contact.

  `payload_uuid`                      Identifies the exported payload
                                      instance.

  `token`                             Time-dependent HMAC authentication
                                      token.

  `\n`                                Terminates the authentication line.
  -----------------------------------------------------------------------

The server evaluates the identity information and token before treating
the connection as an authenticated client session.

#### Legacy authentication and identity authentication

The protocol distinguishes **legacy authentication** from **identity
authentication**.

-   **Legacy authentication** is the compatibility path for clients that
    use the older authentication form and do not provide the complete
    server-and-payload identity pair.
-   **Identity authentication** associates the request with both a
    specific server UUID and a specific payload UUID. This gives the
    server an explicit identity to validate against its persistent state
    and payload registry.

The identity form is the format shown above. The distinction is relevant
to compatibility: a legacy client does not carry the same explicit
identity context as an identity-authenticated payload.

### 3.2 Command execution and Sentinel Framing

After authentication, the server can send a shell command to the client.
The client executes the command and returns its output using **Sentinel
Framing**.

The response is delimited by two literal markers:

``` text
<<<RSC_BEGIN>>>
<command output>
<<<RSC_END>>>
```

The markers identify the boundaries of one command response within the
TCP byte stream. They allow the server to distinguish the command's
output from subsequent protocol traffic.

Sentinel Framing is a message-boundary convention layered over TCP. TCP
itself provides an ordered byte stream; it does not preserve
application-level message boundaries. The receiver must therefore
recognize the framing markers and accumulate data until the
corresponding end marker is observed.

The framing markers are protocol delimiters, not cryptographic integrity
checks. They should not be interpreted as proof that the returned
command output is authentic or untampered.

## 4. Server Implementation

The server implementation is located at:

``` text
modules/server.py
```

It coordinates connection acceptance, authentication, client lifecycle,
command dispatch, inbound data processing, and keepalive handling.

### 4.1 The `response_queue` architecture

Each client session has a thread-safe `queue.Queue` called
`response_queue`. The `_client_read_loop` is the **sole reader** of the
client's TCP socket. It places received data into this queue for the
rest of the server to process.

The `send_command` path obtains response data from the queue instead of
reading directly from the socket.

``` text
Client socket
     |
     | recv() -- only in _client_read_loop
     v
_client_read_loop
     |
     | enqueue received data
     v
response_queue (thread-safe)
     |
     +----------------------+
     |                      |
     v                      v
send_command          keepalive/session
response handling     response handling
```

This architecture addresses a common TCP concurrency failure.

Without a single-reader design, a command-handling thread and a
keepalive thread could both call `recv()` on the same socket. Because
TCP delivers an ordered byte stream, either thread could consume bytes
intended for the other. For example, a keepalive response could be
consumed by the command handler and then appear as unexpected command
output, or command output could be consumed by the keepalive path.

With `response_queue`:

1.  Only `_client_read_loop` performs socket reads.
2.  All received bytes enter one synchronized queue.
3.  `send_command` consumes data from the queue.
4.  Keepalive and command-response handling do not compete for socket
    ownership.

The queue therefore separates socket ownership from higher-level
response processing and prevents the described thread race.

### 4.2 Tripwire behavior

The server contains a specific tripwire condition. If it receives the
exact line:

``` text
Nice try dumbass\n
```

the server:

1.  Records an **ERROR-level alert**.
2.  Disconnects the client.

This is a specific protocol-side detection condition. It should not be
confused with general anomaly detection or a comprehensive
intrusion-detection system.

## 5. Client Implementation

The client implementation is located at:

``` text
client/client.py
```

The client connects to the configured server, authenticates, receives
shell commands, executes them, and returns command output using Sentinel
Framing.

### 5.1 Token resolution

When no command-line arguments are supplied, the client uses its
embedded `_RSC_MASTER_SECRET` global to calculate the current rotating
HMAC token locally.

This means the client does not require a separately supplied token
argument for that execution path. The embedded master secret is the
input to the local token calculation; the resulting token is
time-dependent and is expected to match the server's current
authentication window.

The master secret is security-sensitive. Anyone able to extract it from
a payload may be able to reproduce the token derivation associated with
that payload's configuration. Payload storage and distribution must
consequently be treated as sensitive.

### 5.2 Command execution

Once connected and authenticated, the client receives commands from the
server and executes them through its shell-command execution path. It
returns the resulting output enclosed by the `<<<RSC_BEGIN>>>` and
`<<<RSC_END>>>` markers.

The framing convention allows the server to identify the output
associated with a command. It does not change the permissions of the
process: command execution occurs with the operating-system privileges
of the client process.

### 5.3 Hibernation and reconnect behavior

The client implements **Hibernation** after a disconnect. The configured
retry interval is:

``` text
RECONNECT_DELAY = 30
```

After a connection failure or disconnect, the client waits for the
configured interval before attempting to reconnect. It logs a retry
counter so that repeated attempts are visible in its output or logs.

The reconnect path is designed not to terminate the client process
merely because a connection was lost. Instead, the client remains in its
retry lifecycle and attempts to restore the connection after the delay.

This behavior is distinct from a guarantee of successful reconnection.
Network availability, server availability, authentication state, and
payload registration can all affect whether a later attempt succeeds.

## 6. Exporter and Payload Generation

The exporter is located at:

``` text
exporter/
```

Its central responsibility is to transform the client source into one of
the supported output forms and package the result with the dependencies
required by the client.

### 6.1 `ExportManager`

`ExportManager` coordinates payload generation. It takes the client
source and applies the wrapper appropriate to the selected output
format. The wrapper provides a format-specific execution entry point
while retaining the Python client implementation as the underlying
program.

The exporter supports these output extensions:

``` text
.py
.sh
.bat
.js
.exe
```

### 6.2 Format-specific wrappers

The wrapper behavior differs by target format:

  -----------------------------------------------------------------------
  Format                              Wrapper implementation
  ----------------------------------- -----------------------------------
  `.py`                               Uses direct Python `exec` to
                                      execute the wrapped source.

  `.sh`                               Uses a Bash heredoc to provide the
                                      embedded source to the Python
                                      execution path.

  `.bat`                              Uses PowerShell `-EncodedCommand`
                                      as the Windows command wrapper.

  `.js`                               Uses Node.js to pipe the embedded
                                      Python source to Python's standard
                                      input.

  `.exe`                              Generates a PyInstaller
                                      specification for executable
                                      packaging.
  -----------------------------------------------------------------------

These are wrapper and packaging differences. They do not represent five
independent client implementations: the generated artifacts are
different delivery forms for the same underlying Python client logic.

### 6.3 Dependency bundling

The exporter includes the required `core/` package content in the
generated bundle. This is a runtime requirement: the client depends on
packages in `core/`, so a payload that omits required core modules may
fail when executed in an environment where those modules are not
otherwise available.

The dependency boundary is therefore:

``` text
Generated payload
|
+-- Wrapped client source
|
+-- Required core/ package content
```

The exact set of files included in a particular artifact is determined
by the exporter's packaging implementation. This document does not
assume additional third-party dependencies or runtime components beyond
those specified by the project context.

## 7. Security Architecture

RSC uses several mechanisms that serve different security purposes. They
should be understood as separate controls rather than as interchangeable
protections.

### 7.1 Rotating HMAC authentication

Authentication uses a time-dependent HMAC token derived from the master
secret. Tokens expire as the rotation interval advances.

The rotating-token design limits the validity period of an individual
token. It does not make the embedded master secret non-extractable, and
it does not compensate for a compromised server or payload.

### 7.2 Payload identity and integrity gate

Payload identity is checked using the payload UUID before the client
proceeds with its normal execution path. This check binds the payload to
an identity recognized by the server-side state.

The project also defines extracted-blob behavior: extracted blobs exit
silently. This is a behavior of the payload's extraction/validation
path, not evidence that the payload has passed a cryptographic
code-signing or tamper-proofing scheme.

A UUID is an identifier. Unless it is validated through a trusted
mechanism, it is not itself a cryptographic integrity proof. The UUID
check should therefore be understood as an identity gate, not as a
substitute for a cryptographic signature.

### 7.3 Decoy blobs

The client source contains two named decoy blobs:

-   **`_DECOY1_B64`**: decoy content that prints fake version
    information.
-   **`_DECOY2_B64`**: a beacon whose activation triggers the server
    tripwire.

These are distinct behaviors. The first produces misleading version
output; the second is associated with the tripwire condition described
in the server section. Neither should be mistaken for a general-purpose
integrity mechanism.

### 7.4 Persistent server state and payload registry

Persistent state is implemented in:

``` text
core/server_state.py
```

The state is stored under:

``` text
~/.config/reverse-shell/
```

The persisted information includes:

-   The HMAC master secret.
-   A registry of payloads, tracked by payload UUID.

The registry provides the server with a persistent record of payload
identities. Revoking a payload removes its UUID from the registry. A
subsequent authentication attempt using that revoked payload identity
fails the registry validation path.

This makes registry revocation an authentication control. It does not
remotely erase an already exported payload or guarantee that a
disconnected client process has been terminated.

### 7.5 Ngrok URL discovery

Ngrok integration is implemented in:

``` text
core/ngrok.py
```

The module detects the local Ngrok admin API and obtains the public URL
exposed by the local Ngrok session. The exporter can use the discovered
URL when generating a payload, baking that public endpoint into the
exported artifact at export time.

The URL is therefore an export-time configuration input. Its
availability depends on the local Ngrok admin API being detectable and
on a usable public endpoint being reported.

### 7.6 Defense-in-depth summary

  -----------------------------------------------------------------------
  Mechanism               Intended role           Important limitation
  ----------------------- ----------------------- -----------------------
  Rotating HMAC           Time-bounded            The embedded master
                          authentication tokens   secret remains
                                                  sensitive.

  Server and payload      Identity association    UUIDs alone are not
  UUIDs                                           cryptographic integrity
                                                  proofs.

  Payload registry        Tracks authorized       Revocation affects
                          payload identities      subsequent
                                                  authentication; it does
                                                  not erase exported
                                                  files.

  Decoy blobs             Defined decoy output    Decoys are not a
                          and tripwire-associated substitute for
                          behavior                authentication or
                                                  integrity controls.

  Tripwire                Logs an ERROR alert and It is a specific
                          disconnects on the      trigger, not
                          specified input         comprehensive
                                                  detection.

  Payload bundling        Includes required       Packaging completeness
                          runtime package content must be validated for
                                                  each output format.
  -----------------------------------------------------------------------

## 8. Web Dashboard

The browser dashboard is located in:

``` text
web/
```

It uses Flask for the web application and Server-Sent Events (SSE) to
deliver server-side events to connected browser clients.

### 8.1 EventBus and Server-Sent Events

The **EventBus** provides the event-distribution boundary between server
activity and the web interface. Server-side events are published to the
bus, and the SSE endpoint exposes those events to the browser as a
continuously delivered event stream.

``` text
RSC server activity
       |
       v
   EventBus
       |
       v
 Flask SSE endpoint
       |
       | HTTP event stream
       v
 Browser dashboard
```

SSE is a server-to-client streaming mechanism over HTTP. The browser
maintains an event-stream connection and receives events as the server
publishes them. It is not a general bidirectional transport:
browser-to-server actions use the web application's normal
request-handling paths.

The EventBus decouples event production from browser delivery. Server
components can publish events without needing to manage each browser
connection directly.

### 8.2 AppState callback wiring

`AppState` connects the server's callback interface to the web
frontend's event flow. It acts as the integration point between server
lifecycle events and the web application's state/event infrastructure.

At a conceptual level:

1.  The server invokes a registered callback when a relevant event
    occurs.
2.  `AppState` receives the callback.
3.  `AppState` translates or forwards the event into the web
    application's event flow.
4.  The EventBus makes the event available to connected SSE consumers.
5.  The browser dashboard receives the event through its SSE connection.

This arrangement keeps the server implementation independent of the
browser transport. The server emits callbacks; the web layer adapts
those callbacks for frontend consumption.

## 9. Tkinter Dashboard

The desktop dashboard is located in:

``` text
dashboard/
```

It is implemented with Tkinter and provides a desktop interface separate
from the Flask-based web dashboard.

The two dashboard implementations have different presentation and
delivery mechanisms:

  -----------------------------------------------------------------------
  Dashboard               Technology              Event/interface model
  ----------------------- ----------------------- -----------------------
  Web                     Flask and SSE           Browser receives
                                                  server-published events
                                                  through an HTTP event
                                                  stream.

  Desktop                 Tkinter                 Native desktop GUI.
  -----------------------------------------------------------------------

No additional synchronization protocol or feature parity between the two
dashboards is assumed here.

## 10. Persistent Data and Runtime Boundaries

The primary persistent state directory is:

``` text
~/.config/reverse-shell/
```

It contains the server's HMAC master secret and payload registry, as
managed by `core/server_state.py`.

The principal runtime boundaries are:

-   **Network boundary:** TCP connections to the server listener on port
    `4444`.
-   **Client process boundary:** Shell commands execute with the
    privileges of the client process.
-   **Persistent-state boundary:** The master secret and payload
    registry are stored in the user's configuration directory.
-   **Export boundary:** `exporter/` creates format-specific artifacts
    and includes required `core/` package content.
-   **Dashboard boundary:** The web dashboard receives server events
    through the EventBus/SSE path; the Tkinter dashboard is a separate
    desktop interface.

These boundaries are useful when reviewing permissions, deployment
assumptions, failure modes, and operational exposure.

## 11. Operational and Security Considerations

RSC provides remote command execution. Its server, client artifacts,
authentication material, and network exposure must be handled as
privileged security assets.

The following considerations follow directly from the described
architecture:

-   Restrict access to the TCP listener and do not expose it to
    untrusted networks.
-   Protect the persistent configuration directory because it contains
    the HMAC master secret and payload registry.
-   Treat exported payloads as sensitive artifacts because they contain
    client logic and embedded authentication material.
-   Validate that each export includes the required `core/` package
    content.
-   Treat Ngrok public URLs as externally reachable endpoints and
    account for the exposure created when a URL is embedded into an
    artifact.
-   Review the privileges under which the client process runs; shell
    commands inherit those privileges.
-   Treat payload revocation as a server-side authentication action, not
    as remote deletion of an artifact.
-   Do not interpret Sentinel Framing, UUID checks, or decoy behavior as
    cryptographic proof of response authenticity or binary integrity.
-   Test reconnect, token-expiration, and disconnect behavior only in an
    isolated environment with systems for which authorization is
    explicit.

## 12. Source-to-Responsibility Reference

  -----------------------------------------------------------------------
  Path                                Responsibility
  ----------------------------------- -----------------------------------
  `modules/server.py`                 TCP server, connection handling,
                                      command dispatch, response queue,
                                      keepalive coordination, tripwire
                                      behavior.

  `client/client.py`                  Client connection, token
                                      resolution, command execution,
                                      Sentinel Framing, and reconnect
                                      hibernation.

  `exporter/`                         `ExportManager`, format wrappers,
                                      payload generation, and dependency
                                      bundling.

  `core/server_state.py`              Persistent HMAC master secret and
                                      payload UUID registry.

  `core/ngrok.py`                     Local Ngrok admin API detection and
                                      export-time public URL discovery.

  `web/`                              Flask dashboard and SSE delivery.

  `dashboard/`                        Tkinter desktop dashboard.
  -----------------------------------------------------------------------

## 13. Architecture Summary

RSC is organized around a multi-threaded TCP server and a Python client
that communicates over a line-oriented authentication protocol followed
by sentinel-framed command responses. The server enforces a
single-reader model per client socket and uses a thread-safe
`response_queue` to separate transport reads from command-response
processing.

The client derives rotating authentication tokens from its embedded
master secret when no command-line arguments are supplied. It reconnects
after disconnects using a 30-second delay and a retry counter. The
exporter wraps the same client source for several output formats and
includes required `core/` package content. Persistent server state
stores the master secret and payload registry under
`~/.config/reverse-shell/`.

The web dashboard receives server events through an EventBus-to-SSE path
wired by `AppState`, while the Tkinter dashboard provides a separate
desktop interface. Security-related mechanisms include rotating HMAC
tokens, payload UUID registration and revocation, decoy blobs, and the
specified tripwire behavior. Each mechanism has a distinct role and
should be evaluated within the limits described above.
