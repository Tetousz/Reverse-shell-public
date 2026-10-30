# Reverse Shell Controller --- Setup Guide

> **Purpose:** Install, configure, and run the Reverse Shell Controller
> (RSC).
>
> **Authorized use only:** Use this software only on systems you own or
> are explicitly authorized to administer and test. Do not deploy
> payloads to third-party devices or networks without informed
> permission.

------------------------------------------------------------------------

## Contents

1.  [Prerequisites](#1-prerequisites)
2.  [Installation](#2-installation)
3.  [Ngrok configuration](#3-ngrok-configuration-optional)
4.  [Starting the server](#4-starting-the-server)
5.  [Exporting a payload](#5-exporting-a-payload)
6.  [Testing a local connection](#6-testing-a-local-connection)
7.  [Testing a remote connection](#7-testing-a-remote-connection)
8.  [Troubleshooting](#8-troubleshooting)

## 1. Prerequisites

Ensure the following are available:

  -----------------------------------------------------------------------
  Requirement                         Version / notes
  ----------------------------------- -----------------------------------
  Python                              3.10 or newer

  pip                                 Python package manager

  Flask                               Required by the web dashboard

  Ngrok                               Required only for connections
                                      across different networks; the
                                      repository is expected to include
                                      the binary
  -----------------------------------------------------------------------

Check the installed Python version:

``` bash
python3 --version
```

The output should report Python 3.10 or newer.

## 2. Installation

Clone the repository and enter its directory:

``` bash
git clone https://github.com/Tetousz/Reverse-shell.git
cd Reverse-shell
```

Create and activate a virtual environment. This keeps project
dependencies separate from system-managed Python packages:

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the project dependencies:

``` bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If Flask is not listed in `requirements.txt` or the installation reports
that it is missing, install it into the active environment:

``` bash
python -m pip install flask
```

On Arch Linux, Flask can alternatively be installed through the system
package manager:

``` bash
sudo pacman -S python-flask
```

Do not mix system packages and virtual-environment packages
unintentionally. When using the virtual environment, activate it before
running the application.

## 3. Ngrok configuration (optional)

Ngrok is needed when an authorized test client must connect from a
different network. It is not required for local-only testing.

From the repository root, add your Ngrok authentication token:

``` bash
./ngrok config add-authtoken <YOUR_TOKEN>
```

Replace `<YOUR_TOKEN>` with the token from your Ngrok account. Treat the
token as a secret and do not commit it to the repository or share it
publicly.

Start a TCP tunnel on port `4444`:

``` bash
./ngrok tcp 4444
```

Keep the Ngrok process running while the tunnel is needed. According to
the project workflow, the exporter detects the active tunnel and embeds
its public address in the exported payload.

> **Important:** A public tunnel makes the service reachable beyond the
> local machine. Enable it only for an authorized test, and stop it when
> the test is complete.

## 4. Starting the server

RSC provides two dashboard interfaces. The web dashboard is the
recommended interface.

### Web dashboard (recommended)

From the repository root, with the virtual environment activated:

``` bash
python3 -m web.main
```

The application should open the dashboard in a browser at:

<http://127.0.0.1:8000>

If the browser does not open automatically, navigate to that address
manually.

### Tk dashboard (fallback)

To use the Tk dashboard instead:

``` bash
python3 -m dashboard.main
```

Run the interface you intend to use. Do not assume that starting one
interface also starts the other.

## 5. Exporting a payload

Use the web dashboard to export a payload:

1.  Start the server from the dashboard using **Start Server**.
2.  Select **Export Payload**.
3.  Choose the required output format, for example, `py`.
4.  Locate the generated archive in the `builds/` directory.

The generated ZIP archive contains the payload script and the required
`core/` dependencies.

Only export and run payloads for systems included in an authorized test
scope. Keep generated archives private because they may contain
connection details for the test environment.

## 6. Testing a local connection

Use a temporary directory for the local test:

``` bash
mkdir -p /tmp/rsc-test
unzip builds/payload_py.zip -d /tmp/rsc-test
cd /tmp/rsc-test
python3 payload_py.py
```

After the payload starts, check the dashboard for a new session.

If the archive has a different name because you selected another format,
replace `payload_py.zip` with the actual archive filename. Likewise, use
the script name contained in that archive.

## 7. Testing a remote connection

For a remote-network test, Ngrok must be running when the payload is
exported so that the exporter can include the active tunnel address.

Transfer the exported archive only to a test machine that you own or are
explicitly authorized to use. Extract it there and run the payload using
the appropriate Python interpreter.

The test client should then attempt to connect through the configured
Ngrok address. Confirm the resulting session in the RSC dashboard.

When testing is complete:

1.  Stop the test payload.
2.  Stop the Ngrok tunnel.
3.  Remove test artifacts from machines where they are no longer
    required.
4.  Revoke or rotate any credentials that may have been exposed.

## 8. Troubleshooting

### Port 4444 is already in use

Identify the process listening on port `4444`:

``` bash
sudo lsof -i :4444
```

Stop the conflicting process only if you recognize it and understand the
effect of terminating it. Then restart the RSC server.

### Ngrok forwarding address changed

Ngrok forwarding addresses may change when a tunnel is restarted. Start
the tunnel again, ensure it is active, and export a new payload so that
the generated configuration contains the current address.

### `ModuleNotFoundError: No module named 'flask'`

Flask is not installed in the Python environment used to start the
dashboard.

If using the project virtual environment, activate it and install Flask:

``` bash
source .venv/bin/activate
python -m pip install flask
```

### `requirements.txt` installation fails

Confirm that Python 3.10 or newer is active and that the virtual
environment is enabled:

``` bash
python3 --version
which python
python -m pip --version
```

Then retry the dependency installation:

``` bash
python -m pip install -r requirements.txt
```

------------------------------------------------------------------------

## Operational notes

-   Run the application from the repository root so that
    project-relative paths resolve as expected.
-   Keep the virtual environment active when installing dependencies or
    starting the application.
-   Do not publish Ngrok tokens, generated payload archives, or embedded
    connection details.
-   Restrict testing to systems and networks for which you have explicit
    authorization.
