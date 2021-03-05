# Tokemon.io Trading Bot Client

This is the trading bot client which executes the trades you request on the tokemon.io platform.

This bot needs to be running in order for the stop loss, take profit, and other strategies
to execute.

# Installation

If you are on Windows 10, you can download the latest release from the [releases page](https://github.com/tokemon-hq/client/releases).

If you are on Linux or Mac, you can install by checking out this repository and following
the steps below

- Install Python 3 (3.8 recommended)
- Create a virtual environment for this project e.g. `$ python -m venv env`
- Install the required libraries `$ pip install -r requirements.txt`
- Launch the bot client with `$ python main.py gui`
  - note: If you wish to run without the GUI on Linux / Mac (such as in a server
    context), you can omit the gui part and launch simply with `$ python main.py`

# Configuration

Persistent configuration of the bot is stored in a `.env` file in the same directory as the
program (the `main.py` or the downloaded `Tokemon.exe`).

If you launch the program with the GUI, and you have not yet configured the `.env` file, you
can enter values in the GUI directly.

Once you have entered the values, you can connnect/reconnect the bot. The text at the bottom of
the GUI will indicate if there were any connection or configuration problems.

Notes:
 * The `ETHERUM_PROVIDER` is your personal API URL obtained when you sign up at https://infura.io
 * The GUI only allows entering one configured account, but if you define many in the `.env` file
   then they will all be shown.
 * To stop the bot client, simply close the window or `Ctrl + C` python if launched from the terminal

