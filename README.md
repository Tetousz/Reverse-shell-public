# Reverse Shell Controller (RSC)

An educational Python-based Command and Control (C2) framework featuring a TCP server, web-based management dashboard, native desktop fallback, and multi-format payload exporter.

> **Security notice:** This project is intended exclusively for educational purposes and authorized testing in isolated environments. Do not deploy it on systems without explicit permission.

## Overview

Reverse Shell Controller (RSC) consists of four primary components:

| Component | Description |
|---|---|
| Server | TCP server listening on port `4444`. |
| Web Dashboard | Flask-based interface running on `127.0.0.1:8000`. |
| Tk Dashboard | Native desktop fallback interface. |
| Exporter | Packages client source code and dependencies into portable ZIP archives. |
| Client | Connects to the configured server. |

### Architecture

```text
                 ┌──────────────────────┐
                 │     Web Dashboard    │
                 │   127.0.0.1:8000     │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │        Server        │
                 │      TCP :4444       │
                 └──────────▲───────────┘
                            │
                    Optional Ngrok
                       TCP Tunnel
                            │
                 ┌──────────▼───────────┐
                 │        Client        │
                 │  Authorized Testing  │
                 └──────────────────────┘
```

## Features

- Flask-based web management dashboard.
- Native Tkinter desktop fallback.
- TCP server operating on port `4444`.
- Multi-format payload export.
- Automatic authentication using rotating HMAC tokens.
- Optional Ngrok TCP tunneling.
- ZIP-based packaging of payloads and required dependencies.

## Supported Payload Formats

The exporter supports the following formats:

| Format | Extension |
|---|---|
| Python | `.py` |
| Shell | `.sh` |
| Windows Batch | `.bat` |
| JavaScript | `.js` |
| Executable | `.exe` |

Generated archives are stored in the `builds/` directory.

## Prerequisites

- Python 3.10 or newer.
- pip.
- Flask.
- Ngrok (optional, for remote connectivity).

The Ngrok binary is included in the repository root.

### Install Flask

Using pip:

```bash
pip install flask
```

On Arch Linux:

```bash
sudo pacman -S python-flask
```

## Installation

Clone the repository:

```bash
git clone <REPOSITORY_URL>
cd Reverse-Shell-Controller
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Verify the Python installation:

```bash
python3 --version
```

## Configuration

### Ngrok Authentication

Ngrok is optional for local testing.

To configure Ngrok, obtain an authentication token from your Ngrok account and execute:

```bash
./ngrok config add-authtoken <TOKEN>
```

### Start the TCP Tunnel

Start the tunnel on port `4444`:

```bash
./ngrok tcp 4444
```

Keep the Ngrok process running while using the application.

**Important:** Ngrok must be running before exporting a payload if remote connectivity is required. The exporter detects the active tunnel and incorporates its forwarding configuration into the generated archive.

If the Ngrok address changes after restarting the tunnel, previously exported payloads must be regenerated.

## Starting the Application

RSC provides two dashboard interfaces.

### Web Dashboard (Recommended)

Start the Flask dashboard:

```bash
python3 -m web.main
```

The browser opens automatically.

Dashboard address:

```text
http://127.0.0.1:8000
```

### Tk Dashboard (Fallback)

If the web interface is unavailable, start the native desktop dashboard:

```bash
python3 -m dashboard.main
```

## Exporting a Payload

1. Start the Web Dashboard.
2. Click **Start Server**.
3. Click **Export Payload**.
4. Select the required output format.
5. Complete the export operation.

The exporter generates a ZIP archive in:

```text
builds/
```

Each archive contains the selected payload and the required `core/` Python package.

### Authentication

Exported payloads use automatic authentication. The exporter embeds the master secret into the generated payload, allowing the client to calculate its rotating HMAC authentication token.

No separate authentication token needs to be supplied through the command line.

### Export Structure

Example archive structure:

```text
payload_py.zip
├── payload_py.py
└── core/
    ├── ...
```

The exact contents depend on the selected payload format.

## Testing

Testing should be performed only in an isolated environment or on systems for which you have explicit authorization.

### Local Testing

Extract the generated archive:

```bash
mkdir -p /tmp/test/
unzip builds/payload_py.zip -d /tmp/test/
```

Navigate to the extracted directory:

```bash
cd /tmp/test/
```

Run the Python payload:

```bash
python3 payload_py.py
```

Verify the connection status through the Web Dashboard.

### Remote Connectivity

Remote connectivity requires an active Ngrok tunnel during payload export.

The exported archive contains the forwarding configuration detected at export time. When the archive is transferred to another authorized test machine, the client uses that configuration to connect back through the tunnel.

The server and Ngrok tunnel must remain active.

If Ngrok restarts and assigns a different forwarding address, export a new payload.

## Troubleshooting

<details>
<summary><strong>Port 4444 is already in use</strong></summary>

Another process may already be listening on TCP port `4444`.

Identify the process:

```bash
sudo lsof -i :4444
```

Alternatively:

```bash
sudo ss -ltnp | grep 4444
```

Stop the conflicting process if appropriate, then restart the application.

</details>

<details>
<summary><strong>Ngrok forwarding address changed</strong></summary>

Free Ngrok addresses can change when the tunnel is restarted.

Previously exported payloads retain their original forwarding configuration.

To resolve this:

1. Start Ngrok again.
2. Verify the current forwarding address.
3. Restart the server if necessary.
4. Export a new payload.

</details>

<details>
<summary><strong>ModuleNotFoundError: No module named 'flask'</strong></summary>

Flask is missing from the active Python environment.

Install it using:

```bash
python3 -m pip install flask
```

Verify the installation:

```bash
python3 -m pip show flask
```

On Arch Linux:

```bash
sudo pacman -S python-flask
```

</details>

<details>
<summary><strong>Dashboard does not open automatically</strong></summary>

Open the dashboard manually:

```text
http://127.0.0.1:8000
```

Ensure the Web Dashboard process is running and that port `8000` is available.

</details>

## Security Considerations

- Use RSC only in controlled environments and on systems you are authorized to test.
- Do not expose management interfaces to untrusted networks.
- Treat exported payloads as sensitive files.
- Embedded authentication secrets must not be distributed publicly.
- Restrict access to the server and its generated builds.
- Stop the server and tunnel when testing is complete.

## License

See the repository's `LICENSE` file for licensing terms.