# usbip-autobind

**usbip-autobind** is a Python script designed to automatically bind all attached USB devices to the [usbip](https://github.com/usbip/usbip) driver, making it easy to share USB devices over IP. I use this to so I can use the same periferals for multiple devices without repluging cables every time i switch. Instead I just have one USB hub connected to a raspberry pi hosting this and i have the client on all my other devices.

I originally used https://github.com/mozram/usbip-autobind but i wanted more functionality so i expanded it.

---

## Features

- **Automatic USB Device Binding**: Detects all attached USB devices and binds them to the usbip driver.
- **Perfect for multiple clients**: The host can handle as many clients as you want and assign any USB device to any client.
- **Easy Integration**: Simple to run, no complicated setup required (except you consider creating services to run in the background complicated)
- **Cross-Platform**: Tested on host on Raspbian and client on Arch and Windows 11.
- **Verbose Logging**: Provides detailed output for troubleshooting and monitoring.
- **Web UI**: Provides a webui to configure which client gets which USB device.
- **API**: Provides an API to do the same stuff as the webui if you want to automate stuff.
- **Whitelist**: Only touches USB ports you allowed it to use.
- **Stable**: Automatic freeing of drivers if something fails or connection retries etc ensure the your usb connections stay attached.
- **Persistent State**: The host memorizes which USB devices were assigned to which client even between reboots and automatically attaches them again.

---

## Requirements (Server Side)

- **Linux** (tested on Raspbian and Arch)
- **Python 3.10+** (may work with previous versions but untested)
- **pip** (Python package manager)
- **systemd** (for running services)
- **Root privileges** (binding devices typically requires administrative access)

## Requirements (Client Side)

- **Linux or Windows** (tested on Arch and Windows 11)
- **Python 3.10+** (may work with previous versions but untested)
- **pip** (Python package manager)
- **Root privileges** (binding devices typically requires administrative access)

---

## Installation (Server Side)

### Automatic (Recommended)

You can use the provided install script to set up everything automatically, including installing usbip, enabling kernel modules, creating required services, and running the server with uvx.

Just run this one-liner (it will fetch the latest install script from GitHub and execute it):

```bash
curl -fsSL https://raw.githubusercontent.com/virus-rpi/usbip-autobind/master/install_usbip_autobind_server.sh | sudo bash
```

The script will prompt you for configuration options (socket host/port, web host/port, physical ports whitelist, assignments file path) and set up a systemd service that runs the server with uvx. The service will always use your chosen settings and ensure usbipd is running.

---

### Manual (Advanced)

1. **Install usbip and uvx:**
   ```bash
   sudo apt install usbip
   # or for other distros:
   # sudo dnf install usbip
   # sudo pacman -Sy usbip
   
   # Install uvx if not already installed
   pip3 install uvx
   # or
   pip install uvx
   ```

2. **Enable kernel modules:**
   ```bash
   sudo modprobe usbip-core usbip-host
   ```

3. **Create and enable the usbipd service:**
   Create the file `/etc/systemd/system/usbipd.service` with:
   ```ini
   [Unit]
   Description=usbip host daemon
   After=network.target

   [Service]
   Type=forking
   ExecStart=/usr/sbin/usbipd -D

   [Install]
   WantedBy=multi-user.target
   ```
   Then run:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable usbipd
   sudo systemctl start usbipd
   ```

4. **Run the server with uvx:**
   You can run the server directly with uvx, specifying your configuration options:
   ```bash
   sudo uvx --from git+https://github.com/virus-rpi/usbip-autobind@master usbip-server \
     --socket-host 0.0.0.0 --socket-port 65432 \
     --web-host 0.0.0.0 --web-port 8080 \
     --physical-ports 1-1,1-2,2-1,2-2 \
     --assignments-file /var/lib/usbip-autobind/assignments.json
   ```
   Example whitelist: `1-1,1-2,2-1,2-2` (these are bus IDs for USB ports; use `usbip list -l` to find yours).

5. **(Optional instead of step 4) Create a systemd service for the server:**
   Create `/etc/systemd/system/usbip-autobind.service` with:
   ```ini
   [Unit]
   Description=usbip-autobind server
   After=network.target usbipd.service
   Requires=usbipd.service

   [Service]
   Type=simple
   ExecStart=uvx --from git+https://github.com/virus-rpi/usbip-autobind@master usbip-server --socket-host 0.0.0.0 --socket-port 65432 --web-host 0.0.0.0 --web-port 8080 --physical-ports <comma-separated-whitelist> --assignments-file /var/lib/usbip-autobind/assignments.json
   Restart=always
   RestartSec=10s

   [Install]
   WantedBy=multi-user.target
   ```
   Then run:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable usbip-autobind
   sudo systemctl start usbip-autobind
   ```
---

## Installation (Client Side) 

### Linux

1. Install usbip:
   
```bash
sudo apt install usbip
```

2. Enable kernel modules

```bash
modprobe usbip-core usbip-host
```

3. Download the usbip-client-autoattach.py
4. Edit the SOCKET_HOST variable and put in the ip address of the server
5. Add a service to start the python script (optional but recommended)

Create the file /etc/systemd/system/usbip-autoattach.service with the following content:

```
[Unit]
Description=USBIP Client Service
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /path/to/your/usbip-client-autoattach.py
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

Replace the path to the usbip-client-autobind.py with the actual path.

Then run:

```bash
sudo systemctl daemon-reload
sudo ststemctl enable usbip-autoattach
sudo systemctl start usbip-autoattach
```

Alternatively you can run the script directly with `sudo python3 usbip-client-autobind.py`.

### Windows

1. Install usbip:
   Just follow the instructions in the readme of https://github.com/vadimgrn/usbip-win2
2. Download the usbip-client-autoattach.py
3. Edit the SOCKET_HOST variable and put in the ip address of the server
4. Add a service to start the python script (optional but recommended)

The easies way to add a service on windows is with nssm. (to install nssm do `winget install nssm`)
To create a service first make a bat file containing:
```bat
@echo off
"C:\path\to\your\python.exe" "C:\path\to\your\usbip-client-autobind.py"
```
Place it at some for services accessible place like C:\usbip\start-client.bat

Then start cmd or powershell as admin and run:
```bat
nssm install USBIP-AutoAttach
```

This should open a gui where you can select the bat file you created as path.
Optionally you can configure a log.txt file in the I/O tab if you want to keep logs. 
You can click through the other tabs and configure the service how you want.
Then just click "Install"

After that run:
```bat
nssm enable USBIP-AutoAttach
nssm start USBIP-AutoAttach
```

Alternatively you can run the script directly with `python usbip-client-autobind.py` in an admin shell.

---

## Usage

- The server script will automatically detect all connected USB devices and bind them to the usbip driver.
- The client should automatically connect to the server
- Then visit the web ui hosted at port 8080 on the server.
  On there you can assign all USB devices at once to one client or assign them individually for more control.
  If a client goes offline and comes back later it will automatically connect to the assigned devices again as long as they are free.
  You can also force free a USB device which tells the client to detach, unbinds the device from usbip and then rebinds it.
  Force reattach does the same, except it tells the client to attach again afterwards.
  At the bottom of the page you can see the raw state of a few variables for troubbleshooting.
- You can also controll the host via an api on the endpoints /assign /assign_all /force_free and /force_reattach

<img width="1133" height="925" alt="Screenshot of the Web UI" src="https://github.com/user-attachments/assets/2efeedfe-21a1-4718-804a-db63b5bb493c" />


---

## How It Works

1. **Device Detection:**  
   The script gets the connected devices at script start and after that watches the USB ports via a udev observer.

2. **Binding Process:**  
   For each detected device, it attempts to bind the device interface to the usbip driver using `usbip` commands.

3. **Attaching:**  
   To attach a device the host sends a command to the client to bind a specific device over a socket connection. If you chage to which client a device should be attached it sends a command to the old client to detach and a attach command to te new client.

---

## Troubleshooting

- **Permission Errors:**  
  Ensure you are running the script with root privileges.

- **usbip Not Found:**  
  Make sure `usbip` is installed and available in your system's PATH.

- **The USB device doesnt show up in the list**:
  Make sure the port you pluged it in is on the whitelist.

- A lot of different errors can occur on linux if you dont properly install the kernel modules. Make sure you execute `modprobe usbip-core usbip-host`
- For connectiong issues check the host ip in the client script and check if a firewall is blocking something
- If your system does not use systemd your a nerdy enough to figure out how to do services yourself

---

## Contributing

Pull requests and issues are welcome!  
If you find a bug or have a feature request, please open an issue in this repository.

---

## License

This project is licensed under the MIT License.

---

## Author

Developed and maintained by [virus-rpi](https://github.com/virus-rpi).
