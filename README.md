# parosBox

Code deployed on paros raspbery PIs

## Deployment Instructions

1. Create an SD card with Raspberry PI Imager loaded with the OS "Raspberry PI OS Lite (64 Bit)" with these options:
   1. `Set hostname` to name of box (this MUST be set to whatever the config name is in [this repo](https://github.com/UMassCASA/parosConfigs))
   2. `Enable SSH`, use password authentication
   3. `Set Username and Password` to `pi` for the User, and (redacted) for the password
   4. `Configure wireless lan` - set this to the credentials for your phone's wireless hotspot. Also set the wireless country. This way you'll be able to make use of your hotspot during setup.
   5. `Set locale settings` always keep keyboard layout on US, but set time zone to wherever the box will be
   6. Uncheck `enable telemetry`
2. Put this SD card into the raspberry PI, connect your laptop to the ethernet port (ensure that your laptop is set to DHCP on that interface, which is the default), and power on the PI
3. After 1-2 mins you should be able to `ssh pi@<hostname>.local` with the password set in 1.(3)
4. For the next few steps the PI needs internet access. Since the ethernet port is full, use your phone's hotspot which you set the credentials for in 1.(4). Keep in mind that you can also change these credentials by running the `sudo raspi-setup` command in the SSH window after the fact.
5. Once you have internet access, run `sudo apt update` and `sudo apt install git`
6. Ensure that you are in your home directory (`cd ~`) and run `git clone https://github.com/UmassCASA/parosBox.git parosBox`.
7. Change directory: `cd parosBox` and clone the config directory. This is a private repo so it will ask for your github credentials, or you can use SSH key auth if you have that setup, or make a personal access token if you have 2 factor enabled and don't have SSH auth. `git clone https://github.com/UmassCASA/parosConfigs.git config`
8. Run the setup script. `sudo ./setup.sh`
9. Reboot the raspberry PI. On reboot, you should be able to access the SSH connection via the `mgh4` server. If that is true, disconnect your ethernet cable and connect the permanent internet source to the ethernet port, and turn off your phone's hotspot.
