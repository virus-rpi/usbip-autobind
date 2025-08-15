# usbip-autobind

**usbip-autobind** is a Python script designed to automatically bind all attached USB devices to the [usbip](https://github.com/usbip/usbip) driver, making it easy to share USB devices over IP. 

I originally used https://github.com/mozram/usbip-autobind but i wanted more functionality so i expanded it.

---

## Features

- **Automatic USB Device Binding**: Detects all attached USB devices and binds them to the usbip driver.
- **Easy Integration**: Simple to run, no complicated setup required.
- **Cross-Platform**: Tested on host on Raspbian and client Arch and Windows 11.
- **Verbose Logging**: Provides detailed output for troubleshooting and monitoring.
- **Web UI**: Provides a webui to configure which client gets which USB device

---

## Requirements

- **Python 3.10+** (may work with previous versions but untested)
- **usbip** installed and configured on your system
- **Root privileges** (binding devices typically requires administrative access)

---

## Installation (Server Side)

1. Install usbip:
   
```bash
sudo apt install usbip
```

2. Enable kernel modules

```bash
modprobe usbip-core usbip-host
```


3. Add a service to start the usbip deamon:

Create the file /etc/systemd/system/usbipd.service with the following content:

```
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
sudo ststemctl enable usbipd
sudo systemctl start usbipd
```

4. Install the requirements:

```bash
sudo apt install python-pyudev python-fastapi python-uvicorn
```

5. Download the usbip-host-autobind.py script
6. Edit the PHYSICAL_PORTS variable. It is a whitelist of usb bus ids that should be bound. You can see the id of a port by pluging something in and running `usbip list -l`
7. Add a service to start the python script (optional but recommended)

Create the file /etc/systemd/system/usbip-autobind.service with the following content:

```
[Unit]
Description=usbip host daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/your/usbip-host-autobind.py

[Install]
WantedBy=multi-user.target
```

Replace the path to the usbip-host-autobind.py with the actual path.

Then run:

```bash
sudo systemctl daemon-reload
sudo ststemctl enable usbip-autobind
sudo systemctl start usbip-autobind
```

Alternatively you can run the script directly with `sudo python3 usbip-host-autobind.py`.

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
